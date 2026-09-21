"""Multi-agent metrics — handoffs, participation, coordination, recovery, role adherence, collaboration.

These capture failure modes from the MAST taxonomy of multi-agent failures (Cemri et al., 2025):
specification/role violations, inter-agent misalignment (wrong / ping-pong handoffs, lost context) and
verification failures (errors propagating unrecovered).
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory, register_metric
from agentic_eval.core.models import EvalCase, SpanKind, Trace
from agentic_eval.judges import prompts
from agentic_eval.metrics.base_llm import LLMJudgeMetric
from agentic_eval.utils.text import f1, gini, lcs_length


@register_metric
class HandoffAccuracy(BaseMetric):
    """F1 between expected and actual (from, to) handoff pairs; optional order check."""

    name = "handoff_accuracy"
    category = MetricCategory.MULTI_AGENT
    requires = ("expected_handoffs",)
    default_threshold = 0.8

    def __init__(self, check_order: bool = False, **kw: Any) -> None:
        super().__init__(**kw)
        self.check_order = check_order

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        exp_list = [tuple(h) for h in case.expected_handoffs]
        act_list = trace.handoffs
        exp, act = set(exp_list), set(act_list)
        hit = exp & act
        precision = len(hit) / len(act) if act else 0.0
        recall = len(hit) / len(exp)
        score = f1(precision, recall)
        order = lcs_length(exp_list, act_list) / len(exp_list)
        if self.check_order:
            score *= order
        return score, f"handoff precision={precision:.2f} recall={recall:.2f} order={order:.2f}", {
            "missing": [list(h) for h in exp - act], "unexpected": [list(h) for h in act - exp],
            "actual": [list(h) for h in act_list], "order_ratio": order}


@register_metric
class AgentParticipation(BaseMetric):
    """Were the right agents involved? F1 of expected vs participating agents."""

    name = "agent_participation"
    category = MetricCategory.MULTI_AGENT
    requires = ("expected_agents",)
    default_threshold = 0.8

    def __init__(self, penalize_unexpected: bool = True, **kw: Any) -> None:
        super().__init__(**kw)
        self.penalize_unexpected = penalize_unexpected

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        exp, act = set(case.expected_agents), set(trace.agents)
        recall = len(exp & act) / len(exp)
        precision = len(exp & act) / len(act) if act else 0.0
        score = f1(precision, recall) if self.penalize_unexpected else recall
        return score, f"agents recall={recall:.2f} precision={precision:.2f}", {
            "missing": sorted(exp - act), "unexpected": sorted(act - exp)}


@register_metric
class CoordinationEfficiency(BaseMetric):
    """Detects ping-pong delegation, duplicate handoffs and handoff budget overruns."""

    name = "coordination_efficiency"
    category = MetricCategory.MULTI_AGENT
    default_threshold = 0.7

    def __init__(self, max_exchanges_per_pair: int = 2, **kw: Any) -> None:
        super().__init__(**kw)
        self.max_exchanges_per_pair = max_exchanges_per_pair

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        hs = trace.handoffs
        if not hs:
            return 1.0, "no handoffs (single-agent run)", {"handoffs": 0}
        pairs = Counter(frozenset(h) for h in hs)
        excess = sum(max(0, c - self.max_exchanges_per_pair) for c in pairs.values())
        duplicates = sum(1 for a, b in zip(hs, hs[1:], strict=False) if a == b)
        score = 1 - (excess + duplicates) / len(hs)
        budget = case.constraints.get("max_handoffs")
        if budget and len(hs) > budget:
            score *= budget / len(hs)
        return max(0.0, score), f"{len(hs)} handoffs, {excess} ping-pong, {duplicates} duplicate", {
            "handoffs": len(hs), "ping_pong_excess": excess, "duplicates": duplicates, "budget": budget}


@register_metric
class ErrorRecovery(BaseMetric):
    """Were intermediate errors recovered (final answer produced) or did they propagate across agents?"""

    name = "error_recovery"
    category = MetricCategory.MULTI_AGENT
    default_threshold = 0.5

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        errs = trace.errors
        if not errs:
            return 1.0, "no errors", {"errors": 0}
        failing_agents = sorted({s.agent or "unknown" for s in errs})
        recovered = trace.error is None and bool(trace.output_text.strip())
        score = max(0.5, 1 - 0.1 * (len(failing_agents) - 1)) if recovered else 0.0
        return score, ("recovered" if recovered else "unrecovered") + f" from {len(errs)} error(s)", {
            "errors": [{"agent": s.agent, "span": s.name, "error": (s.error or "")[:200]} for s in errs],
            "failing_agents": failing_agents, "recovered": recovered}


@register_metric
class WorkloadBalance(BaseMetric):
    """Informational: 1 − Gini coefficient of work (LLM + tool steps) across agents."""

    name = "workload_balance"
    category = MetricCategory.MULTI_AGENT
    default_threshold = 0.0

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        work = Counter(s.agent or "unknown" for s in trace.spans_of(SpanKind.LLM, SpanKind.TOOL))
        if len(work) <= 1:
            return 1.0, "single agent did all work", {"work": dict(work)}
        g = gini(list(work.values()))
        return 1 - g, f"gini={g:.2f}", {"work": dict(work)}


@register_metric
class RoleAdherence(LLMJudgeMetric):
    """LLM judge per agent: did each agent stay within its declared role (``agent_roles``)?"""

    name = "role_adherence"
    category = MetricCategory.MULTI_AGENT
    requires = ("agent_roles",)
    template = prompts.ROLE_ADHERENCE

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        jobs, agents = [], []
        for agent, role in case.agent_roles.items():
            outputs = [json.dumps(s.output, default=str)[:1500] for s in trace.spans_of(SpanKind.AGENT)
                       if s.agent == agent and s.output is not None]
            tools = [tc.name for s in trace.spans_of(SpanKind.TOOL) if s.agent == agent and (tc := s.tool_call)]
            if not outputs and not tools:
                continue
            agents.append(agent)
            jobs.append(self.ask_judge(agent_name=agent, role=role,
                                       candidate=f"tools used: {tools}\noutputs: {' | '.join(outputs)}"))
        if not jobs:
            return 1.0, "no declared agent participated", {}
        results = await asyncio.gather(*jobs)
        per_agent = {a: round(r[0], 3) for a, r in zip(agents, results, strict=True)}
        worst = min(per_agent, key=per_agent.get)  # type: ignore[arg-type]
        return sum(per_agent.values()) / len(per_agent), f"lowest adherence: {worst}", {"per_agent": per_agent}


@register_metric
class CollaborationQuality(LLMJudgeMetric):
    """LLM judge over the inter-agent transcript: purposeful handoffs, context preserved, no duplication."""

    name = "collaboration_quality"
    category = MetricCategory.MULTI_AGENT
    template = prompts.COLLABORATION_QUALITY

    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        return (True, "") if len(trace.agents) > 1 else (False, "single-agent run")

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        lines = []
        for s in sorted(trace.spans_of(SpanKind.AGENT, SpanKind.HANDOFF), key=lambda x: x.start_time):
            if s.kind == SpanKind.HANDOFF:
                lines.append(f"[handoff] {s.handoff_from} -> {s.handoff_to}: {json.dumps(s.input, default=str)[:300]}")
            else:
                lines.append(f"[{s.agent}] {json.dumps(s.output, default=str)[:300]}")
        return {"task": case.input, "transcript": "\n".join(lines[:60]), "candidate": trace.output_text}
