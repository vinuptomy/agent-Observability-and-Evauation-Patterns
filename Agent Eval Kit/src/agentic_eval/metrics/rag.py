"""Retrieval-augmented generation metrics (RAG triad: faithfulness, context relevance, answer relevancy)."""
from __future__ import annotations

from typing import Any

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory, register_metric
from agentic_eval.core.models import EvalCase, Trace
from agentic_eval.judges import prompts
from agentic_eval.metrics.base_llm import LLMJudgeMetric, actions_summary
from agentic_eval.utils.text import token_recall


def _contexts(trace: Trace, case: EvalCase) -> list[str]:
    return trace.retrieved_contexts or case.reference_contexts


@register_metric
class Faithfulness(LLMJudgeMetric):
    """LLM judge: are the answer's claims grounded in retrieved context (hallucination check)?"""

    name = "faithfulness"
    category = MetricCategory.RAG
    template = prompts.FAITHFULNESS

    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        return (True, "") if _contexts(trace, case) else (False, "no retrieved or reference contexts")

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"context": "\n---\n".join(_contexts(trace, case))[:12000], "actions": actions_summary(trace),
                "candidate": trace.output_text}


@register_metric
class ContextRelevance(LLMJudgeMetric):
    """LLM judge: relevance of retrieved context to the request."""

    name = "context_relevance"
    category = MetricCategory.RAG
    template = prompts.CONTEXT_RELEVANCE

    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        return (True, "") if trace.retrieved_contexts else (False, "no retrieval spans")

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"task": case.input, "context": "\n---\n".join(trace.retrieved_contexts)[:12000]}


@register_metric
class ContextRecall(BaseMetric):
    """Deterministic: how much of each ``reference_contexts`` passage was actually retrieved."""

    name = "context_recall"
    category = MetricCategory.RAG
    requires = ("reference_contexts",)
    default_threshold = 0.7

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        chunks = trace.retrieved_contexts
        if not chunks:
            return 0.0, "nothing retrieved", {}
        per_ref = [max(token_recall(ref, c) for c in chunks) for ref in case.reference_contexts]
        score = sum(per_ref) / len(per_ref)
        return score, f"mean reference recall {score:.2f}", {"per_reference": [round(x, 3) for x in per_ref]}
