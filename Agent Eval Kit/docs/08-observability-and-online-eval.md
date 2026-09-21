# 08 · Observability & online (production) evaluation

## Signals emitted by the kit

| Signal | Content | Enable |
|---|---|---|
| **Structured JSON logs** (stderr) | `case_evaluated` (run_id, case_id, passed, score, failed_metrics), `run_finished`, `target_failed`, `online_eval_failed` | `observability.json_logs: true` or `configure_logging("INFO", json_format=True)` |
| **OTel spans** | one `agentic_eval.case` span per case with `eval.case_id`, `eval.run_id`, `eval.passed`, `eval.score`, `eval.metric.<name>` | `observability.otel_enabled: true` + `pip install ".[otel]"` |
| **OTel metrics** | histogram `agentic_eval.metric.score` {metric, category, passed}; counter `agentic_eval.case.result` {passed} | same |
| **Reports** | JSON (machine), Markdown (humans, PR summaries), JUnit (CI test UIs) | `reporting.formats` |
| **Audit log** | hash-chained run/case events with dataset & config SHA-256 | `security.audit_log` |
| **Langfuse scores / LangSmith feedback** | per-metric score + reason attached to the original production trace/run | exporters below |

If OpenTelemetry isn't installed, telemetry degrades gracefully to logs only. Configure the OTel SDK the
standard way (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, …) and send to Azure Monitor / Application
Insights, Grafana, Datadog, Honeycomb, Elastic, Dynatrace or any OTLP backend.

**Useful dashboard panels:** p50/mean of `agentic_eval.metric.score` by `metric` over time; failure count by
`category`; pass rate per release; top failing metrics; judge error rate (log field `error`).

## Online evaluation in production

`OnlineEvaluator` scores live traffic asynchronously — sampled, non-blocking, bounded and failure-isolated
(a failing evaluation never affects the user request).

```python
from agentic_eval import OnlineEvaluator, Tracer, create_metric, create_judge

online = OnlineEvaluator(
    metrics=[create_metric(n) for n in ("pii_leakage", "policy_compliance", "loop_detection",
                                        "tool_reliability", "coordination_efficiency", "answer_relevancy")],
    judge=create_judge("azure_openai", model="gpt-4o-mini"),
    sample_rate=0.05,            # evaluate 5 % of traffic
    max_queue=1000,              # back-pressure: excess is dropped and counted in online.dropped
    workers=2,
    on_result=lambda r: alert_if_failed(r),     # sync or async callback
)

# FastAPI example
@app.on_event("startup")
async def _start(): await online.start()

@app.on_event("shutdown")
async def _stop(): await online.stop()

@app.post("/chat")
async def chat(req: ChatRequest):
    async with Tracer(name="chat", input=req.message) as tracer:     # same decorators/adapters as offline
        answer = await supervisor(req.message)
        tracer.set_output(answer)
    online.submit(tracer.trace)                                       # returns immediately
    return {"answer": answer}
```

Use **reference-free metrics** online (no ground truth exists for live requests) — see
[03](03-metrics-catalogue.md#reference-free-metrics). `submit(trace, case)` also accepts an `EvalCase` if you
can attach expectations (e.g. `forbidden_tools` for a given channel, budgets per tenant).

## Exporting scores to Langfuse / LangSmith

Attach scores to the traces your team already inspects:

```python
from agentic_eval.observability.exporters import LangfuseScoreExporter, LangSmithFeedbackExporter

# the trace must carry the backend id in metadata
tracer.trace.metadata["langfuse_trace_id"] = langfuse_trace_id     # or "langsmith_run_id"

report = evaluator.run(target, cases)          # keep_traces=True (default) for exporters
LangfuseScoreExporter().export(report)         # reads LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST
LangSmithFeedbackExporter().export(report)     # reads LANGSMITH_API_KEY
```

With `OnlineEvaluator`, call the exporter inside `on_result` (wrap the single `CaseResult` in an
`EvalReport(cases=[result])`) — note online results don't keep traces, so pass the id through
`case.metadata` / your own mapping, or export directly from `result.results`.

## The feedback loop

```
production trace ──► OnlineEvaluator ──► failed metric / user thumbs-down
        ▲                                         │
        │                                         ▼
  deploy fix ◄── CI gate ◄── new EvalCase (tag: regression) ◄── triage in Langfuse/LangSmith/Phoenix
```

1. Sample and score production traffic with reference-free metrics.
2. Route failures (and negative user feedback) to a review queue.
3. Convert reviewed failures into `EvalCase`s with expectations; commit them to the dataset.
4. The CI gate prevents the regression from ever shipping again.
