"""Task / outcome metrics — did the system achieve the user's goal?"""
from __future__ import annotations

from typing import Any

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory, register_metric
from agentic_eval.core.models import EvalCase, Trace
from agentic_eval.judges import prompts
from agentic_eval.metrics.base_llm import LLMJudgeMetric, actions_summary
from agentic_eval.utils.text import token_f1


@register_metric
class TaskCompletion(LLMJudgeMetric):
    """LLM judge: did the system accomplish the user's goal (actions executed + outcome communicated)?"""

    name = "task_completion"
    category = MetricCategory.TASK
    template = prompts.TASK_COMPLETION

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"task": case.input, "reference": case.expected_output, "actions": actions_summary(trace),
                "candidate": trace.output_text}


@register_metric
class AnswerCorrectness(LLMJudgeMetric):
    """LLM judge: semantic/factual agreement of the final answer with the reference answer."""

    name = "answer_correctness"
    category = MetricCategory.TASK
    requires = ("expected_output",)
    template = prompts.ANSWER_CORRECTNESS

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"task": case.input, "reference": case.expected_output, "candidate": trace.output_text}


@register_metric
class AnswerRelevancy(LLMJudgeMetric):
    """LLM judge: does the answer address the request without irrelevant content?"""

    name = "answer_relevancy"
    category = MetricCategory.TASK
    template = prompts.ANSWER_RELEVANCY

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"task": case.input, "candidate": trace.output_text}


@register_metric
class GEval(LLMJudgeMetric):
    """G-Eval: custom natural-language rubric (per metric via ``criteria`` or per case via ``rubric``)."""

    name = "geval"
    category = MetricCategory.QUALITY
    template = prompts.GEVAL

    def __init__(self, criteria: str | None = None, evaluation_steps: list[str] | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.criteria = criteria
        self.evaluation_steps = evaluation_steps or [
            "Identify what the criterion requires.", "Check the candidate for each requirement.",
            "Penalise unsupported or incorrect statements.", "Assign the score."]

    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        return (True, "") if (self.criteria or case.rubric) else (False, "no criteria or case.rubric")

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:
        return {"criteria": case.rubric or self.criteria, "steps": " ".join(
            f"{i}. {s}" for i, s in enumerate(self.evaluation_steps, 1)), "task": case.input,
            "reference": case.expected_output, "candidate": trace.output_text}


@register_metric
class AnswerSimilarity(BaseMetric):
    """Deterministic token-F1 (SQuAD-style) similarity between answer and reference."""

    name = "answer_similarity"
    category = MetricCategory.TASK
    requires = ("expected_output",)
    default_threshold = 0.5

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        score = token_f1(case.expected_output, trace.output_text)
        return score, f"token F1 = {score:.2f}", {}


@register_metric
class KeywordCoverage(BaseMetric):
    """Deterministic: fraction of ``expected_keywords`` present in the final answer."""

    name = "keyword_coverage"
    category = MetricCategory.TASK
    requires = ("expected_keywords",)
    default_threshold = 1.0

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        text = trace.output_text.casefold()
        missing = [k for k in case.expected_keywords if k.casefold() not in text]
        score = 1 - len(missing) / len(case.expected_keywords)
        return score, "all keywords present" if not missing else f"missing: {missing}", {"missing": missing}
