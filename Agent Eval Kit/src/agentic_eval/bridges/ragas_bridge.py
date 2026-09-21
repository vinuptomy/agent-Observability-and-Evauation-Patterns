from __future__ import annotations

from typing import Any

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory
from agentic_eval.core.models import EvalCase, Trace


class RagasMetric(BaseMetric):
    """Wrap any Ragas single-turn metric instance.

        from ragas.metrics import Faithfulness
        RagasMetric(Faithfulness(llm=evaluator_llm), threshold=0.8)
    """

    category = MetricCategory.RAG

    def __init__(self, ragas_metric: Any, category: MetricCategory = MetricCategory.RAG, **kw: Any) -> None:
        kw.setdefault("name", f"ragas:{getattr(ragas_metric, 'name', type(ragas_metric).__name__)}")
        super().__init__(**kw)
        self._metric = ragas_metric
        self.category = category  # type: ignore[misc]

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        try:
            from ragas.dataset_schema import SingleTurnSample
        except ImportError as exc:
            raise ImportError("pip install 'agentic-eval-kit[ragas]'") from exc
        sample = SingleTurnSample(user_input=case.input, response=trace.output_text,
                                  retrieved_contexts=trace.retrieved_contexts or case.reference_contexts or None,
                                  reference=case.expected_output, reference_contexts=case.reference_contexts or None)
        score = await self._metric.single_turn_ascore(sample)
        return float(score), f"ragas score {float(score):.3f}", {}
