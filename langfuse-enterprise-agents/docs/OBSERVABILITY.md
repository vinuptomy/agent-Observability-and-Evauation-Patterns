# Observability with Langfuse

## What is captured

| Signal | Where | Use |
|---|---|---|
| Traces and observations (`agent`, `guardrail`, `generation`, `tool`) | Langfuse Tracing | Debug a single run; read the agent's trajectory |
| `usage_details` and model parameters per generation | Langfuse | Token and cost attribution per agent, model, user |
| Session id | `propagate_attributes(session_id=…)` | Review a whole conversation in the Sessions view |
| User id | `propagate_attributes(user_id=…)` | Per-user analytics, complaint investigation |
| Tags | agent name, environment, provider | Fast filtering in the traces list |
| Environment / release | Langfuse client config | Separate dev/staging/prod; attribute regressions to a deployment |
| Trace scores | `score_current_trace` (guardrails), `POST /v1/feedback` (end users) | Online quality signal |
| Observation metadata | status, steps, tools, latency, tokens, estimated cost | Dashboards and alerting |
| Structured logs | stdout JSON with `run_id` | SIEM / APM correlation |
| Datasets & experiments | `agentctl-lf eval --mode langfuse` | Offline quality, compared run over run |

## Recommended enterprise KPIs

| KPI | Definition | Starting target |
|---|---|---|
| Task success rate | `status=completed` for benign traffic | ≥ 90% |
| Escalation rate | `status=max_steps` (also a run-level evaluator) | ≤ 5% |
| Guardrail block rate | share of traces with `input_guardrail_pass=0` | Track the trend; investigate spikes |
| p95 latency | `latency_ms` (run-level evaluator in experiments) | ≤ 8 s interactive |
| Avg tokens / run | `usage_details.total` | Budget per agent |
| Cost / 1k runs | Langfuse cost from usage + model pricing | Budget per business unit |
| Tool error rate | tool observations with `error` | ≤ 2% |
| User feedback score | `user_feedback` scores via `/v1/feedback` | ≥ 0.8 positive |

## Production practices

1. **Sampling.** `LANGFUSE_SAMPLE_RATE=1.0` in dev/staging. In high-volume production, sample
   (e.g. 0.2) and keep full traces for errors and blocked requests by running those through a
   separate, unsampled client if needed.
2. **Environments.** `APP_ENV` becomes the Langfuse environment, so one project can host dev,
   staging and prod without polluting metrics.
3. **Releases.** Set `RELEASE` to the git SHA in CI/CD; every trace becomes attributable to a
   deployment.
4. **Masking and retention.** Keep `REDACT_PII_IN_TRACES=true`; configure data retention in the
   Langfuse project to match your data-protection policy; prefer self-hosting for confidential
   workloads (EU data residency).
5. **Access control.** Langfuse organisations, projects and RBAC; restrict who can read raw traces,
   since they contain business content even after masking.
6. **Online evaluation.** Configure Langfuse evaluators on a sample of production traces, and feed
   the `/v1/feedback` endpoint from your UI so human judgement lands on the same traces.
7. **Alerting.** Export KPIs (or use Langfuse metrics/API) into your monitoring stack for spikes in
   block rate, escalations, errors and cost.
8. **Flush on exit.** Short-lived jobs must call `flush()`/`shutdown()` — the CLI and API lifespan
   already do.
