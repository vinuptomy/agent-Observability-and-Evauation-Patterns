"""OpenTelemetry instrumentation of the evaluation run itself.

Emits one span per evaluated case (``agentic_eval.case``) plus metrics:
* ``agentic_eval.metric.score``   histogram, attributes: metric, category, passed
* ``agentic_eval.case.result``    counter,   attributes: passed
Exports go wherever your OTel SDK is configured (OTLP → Azure Monitor, Grafana, Jaeger, Phoenix, Langfuse).
Falls back to structured logs if ``opentelemetry-api`` is not installed.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agentic_eval.core.models import CaseResult, EvalReport

logger = logging.getLogger(__name__)


class EvalTelemetry:
    def __init__(self, enabled: bool = True, service_name: str = "agentic-eval") -> None:
        self._tracer = self._hist = self._counter = None
        if not enabled:
            return
        try:
            from opentelemetry import metrics, trace
        except ImportError:
            logger.info("otel_not_installed_falling_back_to_logs")
            return
        self._tracer = trace.get_tracer("agentic_eval", schema_url=None)
        meter = metrics.get_meter("agentic_eval")
        self._hist = meter.create_histogram("agentic_eval.metric.score", unit="1",
                                            description="Normalised metric score (0-1)")
        self._counter = meter.create_counter("agentic_eval.case.result", description="Evaluated cases")
        self.service_name = service_name

    @contextmanager
    def case_span(self, case_id: str, run_id: str) -> Iterator[Any]:
        if self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span("agentic_eval.case",
                                                attributes={"eval.case_id": case_id, "eval.run_id": run_id}) as span:
            yield span

    def record_case(self, result: CaseResult, run_id: str, span: Any = None) -> None:
        logger.info("case_evaluated", extra={"run_id": run_id, "case_id": result.case_id, "passed": result.passed,
                                             "score": round(result.score, 4),
                                             "failed_metrics": [r.metric for r in result.failed_metrics()]})
        if span is not None:
            span.set_attribute("eval.passed", result.passed)
            span.set_attribute("eval.score", result.score)
        for r in result.evaluated:
            if span is not None and r.score is not None:
                span.set_attribute(f"eval.metric.{r.metric}", r.score)
            if self._hist is not None and r.score is not None:
                self._hist.record(r.score, {"metric": r.metric, "category": r.category, "passed": r.passed})
        if self._counter is not None:
            self._counter.add(1, {"passed": result.passed})

    def record_run(self, report: EvalReport) -> None:
        s = report.summary()
        logger.info("run_finished", extra={k: s[k] for k in ("run_id", "total_cases", "pass_rate", "mean_score")})
