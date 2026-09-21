"""The metric contract + registry (plugin mechanism).

Implement :class:`BaseMetric.compute` and decorate the class with :func:`register_metric` to make a
metric available to YAML configs and the CLI. For quick custom checks use :func:`function_metric`.
"""
from __future__ import annotations

import inspect
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from agentic_eval.core.exceptions import ConfigurationError
from agentic_eval.core.models import EvalCase, MetricResult, Trace

if TYPE_CHECKING:  # pragma: no cover
    from agentic_eval.judges.base import BaseJudge

logger = logging.getLogger(__name__)

ComputeOutput = tuple[float, str, dict[str, Any]]


class MetricCategory(str, Enum):
    TASK = "task"                # did the system achieve the goal?
    TOOL = "tool"                # were tools selected / parameterised correctly?
    TRAJECTORY = "trajectory"    # was the reasoning / action path sound & efficient?
    MULTI_AGENT = "multi_agent"  # handoffs, delegation, coordination, role adherence
    RAG = "rag"                  # grounding & retrieval quality
    SAFETY = "safety"            # PII, prompt injection, policy, forbidden actions
    PERFORMANCE = "performance"  # latency, cost, tokens, steps
    QUALITY = "quality"          # rubric / custom quality criteria


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or (hasattr(value, "__len__") and len(value) == 0)


class BaseMetric(ABC):
    """Base class for every metric. Scores are always normalised to ``[0, 1]`` (higher is better)."""

    name: ClassVar[str] = "base"
    category: ClassVar[MetricCategory] = MetricCategory.QUALITY
    requires: ClassVar[tuple[str, ...]] = ()   # EvalCase fields that must be non-empty
    uses_judge: ClassVar[bool] = False
    default_threshold: ClassVar[float] = 0.7

    def __init__(
        self,
        threshold: float | None = None,
        weight: float = 1.0,
        judge: BaseJudge | None = None,
        name: str | None = None,
    ) -> None:
        self.threshold = self.default_threshold if threshold is None else float(threshold)
        if not 0.0 <= self.threshold <= 1.0:
            raise ConfigurationError(f"{self.name}: threshold must be in [0,1], got {self.threshold}")
        self.weight = float(weight)
        self.judge = judge
        if name:
            self.name = name  # instance-level override (e.g. two configured variants)

    # ---- extension points ------------------------------------------------------------
    def is_applicable(self, trace: Trace, case: EvalCase) -> tuple[bool, str]:
        for field in self.requires:
            if _is_empty(getattr(case, field, None)):
                return False, f"case has no '{field}'"
        return True, ""

    @abstractmethod
    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        """Return ``(score_in_0_1, reason, details)``."""

    # ---- template method (do not override) -------------------------------------------
    async def evaluate(self, trace: Trace, case: EvalCase) -> MetricResult:
        base = {"metric": self.name, "category": self.category.value, "threshold": self.threshold,
                "weight": self.weight}
        ok, why = self.is_applicable(trace, case)
        if not ok:
            return MetricResult(**base, skipped=True, passed=True, reason=f"skipped: {why}")
        t0 = time.perf_counter()
        try:
            score, reason, details = await self.compute(trace, case)
            score = max(0.0, min(1.0, float(score)))
            return MetricResult(
                **base, score=round(score, 4), passed=score >= self.threshold, reason=reason,
                details=details, duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        except Exception as exc:  # a broken metric must never crash the whole run
            logger.exception("metric_failed", extra={"metric": self.name, "case_id": case.case_id})
            return MetricResult(
                **base, score=0.0, passed=False, error=f"{type(exc).__name__}: {exc}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, threshold={self.threshold})"


# ---- registry ------------------------------------------------------------------------
_REGISTRY: dict[str, type[BaseMetric]] = {}


def register_metric(cls: type[BaseMetric]) -> type[BaseMetric]:
    if not issubclass(cls, BaseMetric):
        raise TypeError("register_metric expects a BaseMetric subclass")
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        logger.warning("metric_overridden", extra={"metric": cls.name})
    _REGISTRY[cls.name] = cls
    return cls


def create_metric(name: str, **params: Any) -> BaseMetric:
    if name not in _REGISTRY:
        raise ConfigurationError(f"Unknown metric '{name}'. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**params)


def list_metrics() -> dict[str, dict[str, Any]]:
    return {
        n: {
            "category": c.category.value,
            "requires": list(c.requires),
            "uses_judge": c.uses_judge,
            "default_threshold": c.default_threshold,
            "description": (c.__doc__ or "").strip().splitlines()[0] if c.__doc__ else "",
        }
        for n, c in sorted(_REGISTRY.items())
    }


def _normalize(out: Any) -> ComputeOutput:
    if isinstance(out, bool):
        return (1.0 if out else 0.0), "", {}
    if isinstance(out, (int, float)):
        return float(out), "", {}
    if isinstance(out, tuple):
        if len(out) == 2:
            return float(out[0]), str(out[1]), {}
        if len(out) == 3:
            return float(out[0]), str(out[1]), dict(out[2])
    raise TypeError("function_metric must return bool, float, (score, reason) or (score, reason, details)")


def function_metric(
    name: str,
    category: MetricCategory = MetricCategory.QUALITY,
    threshold: float = 0.7,
    requires: tuple[str, ...] = (),
) -> Callable[[Callable[..., Any]], type[BaseMetric]]:
    """Turn a plain (sync or async) ``fn(trace, case)`` into a registered metric class.

    >>> @function_metric("mentions_ticket_id", category=MetricCategory.TASK)
    ... def mentions_ticket(trace, case):
    ...     return "INC-" in trace.output_text
    """

    def decorator(fn: Callable[..., Any]) -> type[BaseMetric]:
        async def compute(self: BaseMetric, trace: Trace, case: EvalCase) -> ComputeOutput:
            out = fn(trace, case)
            if inspect.isawaitable(out):
                out = await out
            return _normalize(out)

        cls = type(
            f"FunctionMetric_{name}",
            (BaseMetric,),
            {"name": name, "category": category, "requires": tuple(requires), "compute": compute,
             "default_threshold": threshold, "__doc__": fn.__doc__ or f"Custom metric '{name}'."},
        )
        return register_metric(cls)

    return decorator
