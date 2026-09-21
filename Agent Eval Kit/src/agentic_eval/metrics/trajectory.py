"""Trajectory metrics — was the path of actions correct, efficient and loop-free?

Match modes follow the conventions of LangChain *agentevals*: strict, unordered, superset, subset,
plus ``in_order`` (expected steps appear as a subsequence, extra steps allowed).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from agentic_eval.core.exceptions import ConfigurationError
from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory, register_metric
from agentic_eval.core.models import EvalCase, SpanKind, Trace
from agentic_eval.judges import prompts
from agentic_eval.metrics.base_llm import LLMJudgeMetric
from agentic_eval.utils.text import lcs_length

_MODES = ("strict", "in_order", "unordered", "superset", "subset")
_SOURCES = ("tools", "agents", "steps")


def actual_trajectory(trace: Trace, source: str) -> list[str]:
    if source == "tools":
        return trace.tool_names
    if source == "agents":
        return trace.agent_sequence
    steps: list[str] = []  # interleaved agent activations and tools, e.g. "triage_agent", "search_kb"
    for s in sorted(trace.spans_of(SpanKind.AGENT, SpanKind.TOOL), key=lambda x: x.start_time):
        label = s.agent if s.kind == SpanKind.AGENT else s.name
        if label and (not steps or steps[-1] != label):
            steps.append(label)
    return steps


@register_metric
class TrajectoryMatch(BaseMetric):
    """Compares the actual trajectory (tools | agents | steps) with ``expected_trajectory``."""

    name = "trajectory_match"
    category = MetricCategory.TRAJECTORY
    requires = ("expected_trajectory",)
    default_threshold = 0.8

    def __init__(self, mode: str = "in_order", source: str = "tools", **kw: Any) -> None:
        super().__init__(**kw)
        if mode not in _MODES or source not in _SOURCES:
            raise ConfigurationError(f"trajectory_match: mode in {_MODES}, source in {_SOURCES}")
        self.mode, self.source = mode, source

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        mode = case.trajectory_mode or self.mode
        exp, act = list(case.expected_trajectory), actual_trajectory(trace, self.source)
        if mode == "strict":
            score = 1.0 if exp == act else lcs_length(exp, act) / max(len(exp), len(act), 1)
        elif mode == "in_order":
            score = lcs_length(exp, act) / len(exp)
        elif mode == "unordered":
            overlap = sum((Counter(exp) & Counter(act)).values())
            score = 2 * overlap / (len(exp) + len(act)) if (exp or act) else 1.0
        elif mode == "superset":
            score = sum(1 for e in set(exp) if e in act) / len(set(exp))
        else:  # subset
            score = 1.0 if not act else sum(1 for a in act if a in exp) / len(act)
        return score, f"{mode} match on {self.source}: {score:.2f}", {"expected": exp, "actual": act, "mode": mode}


@register_metric
class StepEfficiency(BaseMetric):
    """optimal_steps / actual tool steps (1.0 = no wasted actions)."""

    name = "step_efficiency"
    category = MetricCategory.TRAJECTORY
    default_threshold = 0.7

    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        ok = bool(case.expected_trajectory) or "optimal_steps" in case.constraints
        return (True, "") if ok else (False, "no expected_trajectory / constraints.optimal_steps")

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        optimal = int(case.constraints.get("optimal_steps", len(case.expected_trajectory)))
        actual = len(trace.tool_calls)
        if actual == 0:
            return (1.0 if optimal == 0 else 0.0), "no tool steps executed", {"optimal": optimal, "actual": 0}
        score = min(1.0, optimal / actual)
        return score, f"{actual} steps vs optimal {optimal}", {"optimal": optimal, "actual": actual}


@register_metric
class LoopDetection(BaseMetric):
    """Penalises repeated identical tool calls (same name + arguments) — a classic agent failure mode."""

    name = "loop_detection"
    category = MetricCategory.TRAJECTORY
    default_threshold = 0.8

    def __init__(self, max_identical_calls: int = 1, **kw: Any) -> None:
        super().__init__(**kw)
        self.max_identical_calls = max_identical_calls

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        sigs = Counter(f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True, default=str)}" for tc in trace.tool_calls)
        total = sum(sigs.values())
        if total == 0:
            return 1.0, "no tool calls", {}
        repeats = {k.split(":", 1)[0]: v for k, v in sigs.items() if v > self.max_identical_calls}
        excess = sum(v - self.max_identical_calls for v in sigs.values() if v > self.max_identical_calls)
        score = 1 - excess / total
        return score, "no loops" if not repeats else f"repeated calls: {repeats}", {"repeated": repeats}


@register_metric
class TrajectoryQuality(LLMJudgeMetric):
    """LLM judge: logical, efficient and well-delegated action trajectory."""

    name = "trajectory_quality"
    category = MetricCategory.TRAJECTORY
    template = prompts.TRAJECTORY_QUALITY

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"task": case.input, "reference": " -> ".join(case.expected_trajectory),
                "trajectory": " -> ".join(actual_trajectory(trace, "steps"))}
