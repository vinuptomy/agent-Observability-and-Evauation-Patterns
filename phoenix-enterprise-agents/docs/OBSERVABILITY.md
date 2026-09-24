# Observability with Phoenix, OpenTelemetry and OpenInference

## What is captured

| Signal | Where | Use |
|---|---|---|
| Spans with OpenInference kinds (`agent`, `llm`, `tool`, `retriever`, `guardrail`) | Phoenix Traces | Read the agent trajectory; spot the failing step |
| `llm.token_count.{prompt,completion,total}`, model, provider | LLM spans | Cost and latency attribution per agent and model |
| `retrieval.documents` (id, content, score) | Retriever spans | RAG debugging and retrieval evaluation |
| `session.id`, `user.id`, `tag.tags`, `metadata` | Context propagation | Sessions view, per-user investigation, filtering |
| Span annotations (`CODE`, `HUMAN`, `LLM`) | Guardrails, `/v1/feedback`, judges | Online quality signal on the exact span |
| Structured logs with `run_id` | stdout JSON | SIEM / APM correlation |
| Datasets & experiments | `agentctl-px eval --mode phoenix` | Offline quality compared run over run |

## Recommended enterprise KPIs

| KPI | Definition | Starting target |
|---|---|---|
| Task success rate | `status=completed` for benign traffic | ≥ 90% |
| Escalation rate | `status=max_steps` | ≤ 5% |
| Guardrail block rate | share of runs annotated `input_guardrail_pass=0` | Track the trend; investigate spikes |
| Retrieval hit rate | share of runs retrieving the expected article | ≥ 90% |
| p95 latency | end-to-end span duration | ≤ 8 s interactive |
| Avg tokens / run | LLM span token counts | Budget per agent |
| Tool error rate | tool spans with error status | ≤ 2% |
| User feedback | `user_feedback` annotations | ≥ 0.8 positive |

## Portability: one instrumentation, many backends

Because spans are plain OTLP with OpenInference attributes:

* **Phoenix** (self-hosted or cloud) gives agent-aware views, datasets and experiments.
* **Arize AX** consumes the same spans for production monitoring at scale.
* **Generic OTLP backends** (Tempo, Datadog, Honeycomb, Azure Monitor via a collector) still show
  the hierarchy, durations and attributes — you lose the LLM-specific views, not the telemetry.

Sending to two backends at once is a collector configuration problem, not a code change.

## Production practices

1. **Sampling.** Phoenix/OTel support head sampling at the tracer provider; start at 100% in
   dev/staging and reduce in production, keeping errors and blocked runs.
2. **Batching.** The exporter is registered with `batch=True`; always `flush()` in short-lived jobs.
3. **Projects and environments.** Use `PHOENIX_PROJECT_NAME` per environment (or a `environment`
   tag) so dev traffic never skews production metrics.
4. **Retention and access.** Self-hosted Phoenix keeps trace content inside your network; set
   retention to match your data-protection policy and restrict UI access — traces contain business
   content even after PII redaction.
5. **Online evaluation.** Sample production spans and score them with `phoenix.evals` classifiers,
   writing results back as `LLM` annotations; combine with human feedback from `/v1/feedback`.
6. **Annotations at volume.** Set `PHOENIX_ANNOTATE_GUARDRAILS=false` and rely on span attributes
   if the extra REST call per run is material.
