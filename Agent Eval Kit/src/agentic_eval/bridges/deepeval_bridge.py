from __future__ import annotations

from typing import Any

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory
from agentic_eval.core.models import EvalCase, Trace


class DeepEvalMetric(BaseMetric):
    """Wrap any DeepEval metric instance (they expose ``a_measure`` / ``score`` / ``reason``).

        from deepeval.metrics import ToolCorrectnessMetric, GEval
        DeepEvalMetric(ToolCorrectnessMetric(), category=MetricCategory.TOOL)
    """

    def __init__(self, deepeval_metric: Any, category: MetricCategory = MetricCategory.QUALITY, **kw: Any) -> None:
        kw.setdefault("name", f"deepeval:{getattr(deepeval_metric, '__name__', type(deepeval_metric).__name__)}")
        kw.setdefault("threshold", getattr(deepeval_metric, "threshold", None))
        super().__init__(**kw)
        self._metric = deepeval_metric
        self.category = category  # type: ignore[misc]

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        try:
            from deepeval.test_case import LLMTestCase, ToolCall
        except ImportError as exc:
            raise ImportError("pip install 'agentic-eval-kit[deepeval]'") from exc
        tc = LLMTestCase(
            input=case.input, actual_output=trace.output_text, expected_output=case.expected_output,
            retrieval_context=trace.retrieved_contexts or None, context=case.reference_contexts or None,
            tools_called=[ToolCall(name=t.name, input_parameters=t.arguments, output=t.output) for t in trace.tool_calls],
            expected_tools=[ToolCall(name=n) for n in case.expected_tools])
        await self._metric.a_measure(tc)
        return float(self._metric.score or 0.0), str(getattr(self._metric, "reason", "") or ""), {}
