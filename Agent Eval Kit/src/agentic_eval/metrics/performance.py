"""Operational budget metrics — latency, cost, tokens, steps (per case via ``constraints`` or global)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from agentic_eval.core.metric import BaseMetric, ComputeOutput, MetricCategory, register_metric
from agentic_eval.core.models import EvalCase, Trace


class BudgetMetric(BaseMetric):
    category = MetricCategory.PERFORMANCE
    default_threshold = 1.0
    constraint_key: ClassVar[str] = ""
    unit: ClassVar[str] = ""
    measure: ClassVar[Callable[[Trace], float]]

    def __init__(self, budget: float | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.budget = budget

    def _budget(self, case: EvalCase) -> float | None:
        return case.constraints.get(self.constraint_key, self.budget)

    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        return (True, "") if self._budget(case) is not None else (False, f"no {self.constraint_key} budget")

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        budget = float(self._budget(case))  # type: ignore[arg-type]
        actual = float(type(self).measure(trace))
        score = 1.0 if actual <= budget else (budget / actual if actual else 0.0)
        return score, f"{actual:g}{self.unit} vs budget {budget:g}{self.unit}", {"actual": actual, "budget": budget}


@register_metric
class LatencyBudget(BudgetMetric):
    """End-to-end latency within ``max_latency_ms``."""
    name = "latency_budget"
    constraint_key = "max_latency_ms"
    unit = "ms"
    measure = staticmethod(lambda t: round(t.duration_ms, 2))


@register_metric
class CostBudget(BudgetMetric):
    """Total LLM cost within ``max_cost_usd``."""
    name = "cost_budget"
    constraint_key = "max_cost_usd"
    unit = "$"
    measure = staticmethod(lambda t: t.total_cost_usd)


@register_metric
class TokenBudget(BudgetMetric):
    """Total tokens within ``max_tokens``."""
    name = "token_budget"
    constraint_key = "max_tokens"
    measure = staticmethod(lambda t: t.total_tokens)


@register_metric
class StepBudget(BudgetMetric):
    """LLM + tool steps within ``max_steps`` (runaway-agent protection)."""
    name = "step_budget"
    constraint_key = "max_steps"
    measure = staticmethod(lambda t: t.step_count)
