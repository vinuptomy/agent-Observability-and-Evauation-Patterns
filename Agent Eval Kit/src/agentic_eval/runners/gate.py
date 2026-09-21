"""Quality gate — turns an EvalReport into a release decision (CI/CD exit code)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agentic_eval.core.models import EvalReport


class GateResult(BaseModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)


class QualityGate(BaseModel):
    min_pass_rate: float = 1.0
    min_mean_score: float = 0.0
    blocking_categories: list[str] = Field(default_factory=lambda: ["safety"])
    metric_min_means: dict[str, float] = Field(default_factory=dict)

    def evaluate(self, report: EvalReport) -> GateResult:
        s = report.summary()
        v: list[str] = []
        if s["pass_rate"] < self.min_pass_rate:
            v.append(f"pass_rate {s['pass_rate']:.2%} < {self.min_pass_rate:.2%}")
        if s["mean_score"] < self.min_mean_score:
            v.append(f"mean_score {s['mean_score']:.3f} < {self.min_mean_score:.3f}")
        for name, minimum in self.metric_min_means.items():
            m = s["metrics"].get(name)
            if m and m["mean"] < minimum:
                v.append(f"{name} mean {m['mean']:.3f} < {minimum:.3f}")
        for case in report.cases:
            for r in case.failed_metrics():
                if r.category in self.blocking_categories:
                    v.append(f"blocking {r.category} failure: {case.case_id}/{r.metric}")
        return GateResult(passed=not v, violations=v)
