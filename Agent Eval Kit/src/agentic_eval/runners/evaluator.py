"""The Evaluator — orchestrates target execution, trace capture and concurrent metric scoring.

Three entry points cover every integration style:

* ``run(target, cases)``            — execute your agent per case (live, CI regression)
* ``evaluate_traces(pairs)``        — score traces captured elsewhere (logs, OTel, LangSmith export)
* ``evaluate_trace(trace, case)``   — score one trace (unit tests, online guardrails)

``target`` may be sync or async, take the case input string and return either the final answer or a
fully-built :class:`Trace` (useful when an adapter produces the trace, e.g. AutoGen).
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from agentic_eval.collectors.tracer import Tracer
from agentic_eval.core.config import EvalConfig, load_config
from agentic_eval.core.exceptions import ConfigurationError
from agentic_eval.core.metric import BaseMetric, create_metric
from agentic_eval.core.models import CaseResult, EvalCase, EvalReport, Trace, utcnow_iso
from agentic_eval.judges import create_judge
from agentic_eval.judges.base import BaseJudge
from agentic_eval.observability.telemetry import EvalTelemetry
from agentic_eval.security.audit import AuditLogger

logger = logging.getLogger(__name__)
Target = Callable[[str], Any | Awaitable[Any]]


class Evaluator:
    def __init__(
        self,
        metrics: Sequence[BaseMetric],
        judge: BaseJudge | None = None,
        concurrency: int = 4,
        case_timeout_s: float = 120.0,
        telemetry: EvalTelemetry | None = None,
        audit: AuditLogger | None = None,
        name: str = "eval-run",
        keep_traces: bool = True,
        config_snapshot: dict[str, Any] | None = None,
    ) -> None:
        if not metrics:
            raise ConfigurationError("at least one metric is required")
        names = [m.name for m in metrics]
        if len(names) != len(set(names)):
            raise ConfigurationError(f"duplicate metric names: {names} — pass name=... to disambiguate")
        for m in metrics:
            if m.uses_judge and m.judge is None:
                if judge is None:
                    raise ConfigurationError(f"metric '{m.name}' needs a judge — pass judge=create_judge(...)")
                m.judge = judge
        self.metrics = list(metrics)
        self.judge = judge
        self.concurrency = concurrency
        self.case_timeout_s = case_timeout_s
        self.telemetry = telemetry or EvalTelemetry(enabled=False)
        self.audit = audit
        self.name = name
        self.keep_traces = keep_traces
        self.config_snapshot = config_snapshot or {"metrics": names}

    # ---- construction from YAML --------------------------------------------------------
    @classmethod
    def from_config(cls, config: EvalConfig | str) -> Evaluator:
        cfg = load_config(config) if isinstance(config, str) else config
        judge_params = dict(cfg.judge.params)
        judge_params.setdefault("redact_pii", cfg.security.redact_pii_for_judge)
        metrics = [create_metric(m.name, **m.params) for m in cfg.metrics]
        judge = create_judge(cfg.judge.provider, cfg.judge.model, **judge_params) if any(
            m.uses_judge for m in metrics) else None
        return cls(
            metrics=metrics, judge=judge, concurrency=cfg.runner.concurrency,
            case_timeout_s=cfg.runner.case_timeout_s,
            telemetry=EvalTelemetry(cfg.observability.otel_enabled, cfg.observability.service_name),
            audit=AuditLogger(cfg.security.audit_log) if cfg.security.audit_log else None,
            name=cfg.name, config_snapshot=cfg.redacted_dict())

    # ---- scoring ----------------------------------------------------------------------
    async def aevaluate_trace(self, trace: Trace, case: EvalCase, run_id: str = "adhoc") -> CaseResult:
        with self.telemetry.case_span(case.case_id, run_id) as span:
            results = await asyncio.gather(*(m.evaluate(trace, case) for m in self.metrics))
            result = CaseResult(case_id=case.case_id, trace_id=trace.trace_id, tags=case.tags, results=list(results),
                                trace_summary=trace.summary(), trace=trace if self.keep_traces else None)
            self.telemetry.record_case(result, run_id, span)
        if self.audit:
            self.audit.log("case_evaluated", run_id=run_id, case_id=case.case_id, trace_id=trace.trace_id,
                           passed=result.passed, score=round(result.score, 4),
                           failed=[r.metric for r in result.failed_metrics()])
        return result

    def evaluate_trace(self, trace: Trace, case: EvalCase) -> CaseResult:
        return _run_sync(self.aevaluate_trace(trace, case))

    # ---- execution --------------------------------------------------------------------
    async def _execute(self, target: Target, case: EvalCase) -> Trace:
        tracer = Tracer(name=case.case_id, input=case.input, metadata={"case_id": case.case_id, "tags": case.tags})
        async with tracer:
            try:
                if inspect.iscoroutinefunction(target):
                    out = await asyncio.wait_for(target(case.input), self.case_timeout_s)
                else:  # to_thread copies contextvars -> the tracer stays active inside sync agents
                    out = await asyncio.wait_for(asyncio.to_thread(target, case.input), self.case_timeout_s)
                    if inspect.isawaitable(out):
                        out = await asyncio.wait_for(out, self.case_timeout_s)
            except asyncio.TimeoutError:
                tracer.trace.error = f"TimeoutError: exceeded {self.case_timeout_s}s"
                out = None
            except Exception as exc:  # the agent failing is a *result*, not a crash of the evaluator
                tracer.trace.error = f"{type(exc).__name__}: {exc}"
                logger.warning("target_failed", extra={"case_id": case.case_id, "error": tracer.trace.error})
                out = None
        if isinstance(out, Trace):
            out.metadata.setdefault("case_id", case.case_id)
            return out
        if tracer.trace.final_output is None and out is not None:
            tracer.set_output(out)
        return tracer.trace

    async def arun(self, target: Target, cases: Iterable[EvalCase]) -> EvalReport:
        cases = list(cases)
        report = EvalReport(name=self.name, config=self.config_snapshot)
        self._audit_start(report, cases)
        sem = asyncio.Semaphore(self.concurrency)

        async def one(case: EvalCase) -> CaseResult:
            async with sem:
                trace = await self._execute(target, case)
                return await self.aevaluate_trace(trace, case, report.run_id)

        report.cases = list(await asyncio.gather(*(one(c) for c in cases)))
        return self._finish(report)

    def run(self, target: Target, cases: Iterable[EvalCase]) -> EvalReport:
        return _run_sync(self.arun(target, cases))

    async def aevaluate_traces(self, pairs: Iterable[tuple[Trace, EvalCase]]) -> EvalReport:
        pairs = list(pairs)
        report = EvalReport(name=self.name, config=self.config_snapshot)
        self._audit_start(report, [c for _, c in pairs])
        sem = asyncio.Semaphore(self.concurrency)

        async def one(trace: Trace, case: EvalCase) -> CaseResult:
            async with sem:
                return await self.aevaluate_trace(trace, case, report.run_id)

        report.cases = list(await asyncio.gather(*(one(t, c) for t, c in pairs)))
        return self._finish(report)

    def evaluate_traces(self, pairs: Iterable[tuple[Trace, EvalCase]]) -> EvalReport:
        return _run_sync(self.aevaluate_traces(pairs))

    # ---- helpers ----------------------------------------------------------------------
    def _audit_start(self, report: EvalReport, cases: list[EvalCase]) -> None:
        if self.audit:
            ds_hash = hashlib.sha256(json.dumps([c.model_dump() for c in cases], sort_keys=True,
                                                default=str).encode()).hexdigest()
            cfg_hash = hashlib.sha256(json.dumps(self.config_snapshot, sort_keys=True, default=str).encode()).hexdigest()
            self.audit.log("run_started", run_id=report.run_id, name=self.name, cases=len(cases),
                           dataset_sha256=ds_hash, config_sha256=cfg_hash,
                           judge=getattr(self.judge, "provider", None), judge_model=getattr(self.judge, "model", None))

    def _finish(self, report: EvalReport) -> EvalReport:
        report.finished_at = utcnow_iso()
        self.telemetry.record_run(report)
        if self.audit:
            s = report.summary()
            self.audit.log("run_finished", run_id=report.run_id, pass_rate=s["pass_rate"], mean_score=s["mean_score"])
        return report


def _run_sync(coro: Awaitable[Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    raise RuntimeError("An event loop is already running (e.g. Jupyter/FastAPI) — use the async 'a*' methods.")
