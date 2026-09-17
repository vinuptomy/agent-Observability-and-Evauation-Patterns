# Observability with Opik

## What is captured

| Signal | Where | Use |
|---|---|---|
| Traces and spans | Opik | Debug individual runs; see every LLM and tool step |
| Token usage per LLM span | Opik `usage` | Cost attribution per agent, model and session |
| Trace metadata | `status, steps, tools, latency_ms, total_tokens, estimated_cost_usd, agent_version, environment` | Filtering, dashboards, regressions per version |
| Tags | agent name, environment, provider | Slice the traces list |
| Threads | `thread_id = session_id` | Review whole conversations |
| Online feedback scores | `input_guardrail_pass`, `output_guardrail_pass` | Monitor attack volume and false positives |
| Structured logs | stdout JSON | SIEM / Azure Monitor / Datadog correlation (`run_id`) |
| Experiments | `agentctl eval --mode opik` | Compare prompts and models on the same dataset |

## Recommended enterprise KPIs

| KPI | Definition | Starting target |
|---|---|---|
| Task success rate | `status=completed` for benign traffic | ≥ 90% |
| Escalation rate | `status=max_steps` | ≤ 5% |
| Guardrail block rate | `input_guardrail_pass=0` share | Track trend; investigate spikes |
| p95 latency | `latency_ms` | ≤ 8 s interactive |
| Avg tokens / run | `total_tokens` | Budget per agent |
| Cost / 1k runs | `estimated_cost_usd` | Budget per business unit |
| Tool error rate | tool spans with `error` | ≤ 2% |
| Online quality | Opik online-evaluation rules (LLM judge sampling) | Hallucination ≤ 0.1 |

## Production practices

1. **Sampling.** Trace 100% in dev/staging; in high-volume prod consider sampling plus 100% of errors and blocks.
2. **Online evaluation.** Configure Opik online-evaluation rules on the project to score a sample of production traces with LLM judges.
3. **Alerting.** Export metrics or use Opik's alerting features for block-rate spikes, error spikes, and cost anomalies.
4. **Retention and privacy.** Keep `REDACT_PII_IN_TRACES=true`; set retention aligned with GDPR/data-protection policy; prefer self-hosted Opik for confidential workloads.
5. **Version everything.** `agent_version` in metadata plus experiment config lets you attribute regressions to prompt, model or tool changes.
6. **Human feedback.** Collect thumbs-up/down in your UI and log them as feedback scores against the `trace_id` returned by the API.
