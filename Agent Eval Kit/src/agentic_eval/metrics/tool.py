"""Tool-use metrics — selection, parameterisation and reliability."""
from __future__ import annotations

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory, register_metric
from agentic_eval.core.models import EvalCase, Trace
from agentic_eval.utils.text import f1, soft_equal


@register_metric
class ToolCallAccuracy(BaseMetric):
    """F1 between the expected tool set and the tools actually called (selection correctness)."""

    name = "tool_call_accuracy"
    category = MetricCategory.TOOL
    requires = ("expected_tools",)
    default_threshold = 0.8

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        expected, actual = set(case.expected_tools), set(trace.tool_names)
        hit = expected & actual
        precision = len(hit) / len(actual) if actual else 0.0
        recall = len(hit) / len(expected)
        score = f1(precision, recall)
        return score, f"precision={precision:.2f} recall={recall:.2f}", {
            "missing": sorted(expected - actual), "unexpected": sorted(actual - expected),
            "precision": precision, "recall": recall}


@register_metric
class ToolArgumentAccuracy(BaseMetric):
    """Fraction of expected argument key/values matched by the best call of each expected tool."""

    name = "tool_argument_accuracy"
    category = MetricCategory.TOOL
    requires = ("expected_tool_args",)
    default_threshold = 0.8

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        per_tool: dict[str, float] = {}
        for tool, expected in case.expected_tool_args.items():
            calls = [tc for tc in trace.tool_calls if tc.name == tool]
            if not calls:
                per_tool[tool] = 0.0
                continue
            if not expected:
                per_tool[tool] = 1.0
                continue
            per_tool[tool] = max(
                sum(1 for k, v in expected.items() if k in tc.arguments and soft_equal(v, tc.arguments[k]))
                / len(expected) for tc in calls)
        score = sum(per_tool.values()) / len(per_tool)
        bad = {k: v for k, v in per_tool.items() if v < 1.0}
        return score, "all arguments correct" if not bad else f"argument mismatches: {bad}", {"per_tool": per_tool}


@register_metric
class ToolReliability(BaseMetric):
    """1 − tool error rate (share of tool calls that raised / returned an error)."""

    name = "tool_reliability"
    category = MetricCategory.TOOL
    default_threshold = 0.9

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        calls = trace.tool_calls
        if not calls:
            return 1.0, "no tool calls", {"total": 0}
        failed = [tc.name for tc in calls if tc.error]
        return 1 - len(failed) / len(calls), f"{len(failed)}/{len(calls)} tool calls failed", {"failed": failed}
