# 05 · Configuration & CLI reference

## YAML configuration

`Evaluator.from_config("config/eval_config.yaml")` and the CLI read one YAML file validated by pydantic
(`core/config.py`). Unknown values fail fast with a `ConfigurationError` (CLI exit code 2).

**Secrets never go into YAML.** Use `${VAR}` or `${VAR:-default}`; values are expanded from the environment
at load time, and the config snapshot stored in reports/audit logs is redacted (`redacted_dict()`).

```yaml
name: it-service-desk-regression          # appears in report file names and audit log

judge:
  provider: ${AGENTIC_EVAL_JUDGE:-mock}   # mock | openai | azure_openai | anthropic | <registered custom>
  model: ${AGENTIC_EVAL_JUDGE_MODEL:-gpt-4o-mini}
  params:                                 # passed to the judge constructor
    temperature: 0.0
    max_retries: 3
    timeout_s: 60
    max_concurrency: 8                    # parallel judge calls (rate-limit protection)

runner:
  concurrency: 4                          # parallel cases (1–256)
  case_timeout_s: 60                      # per-case wall clock; timeout is scored, not fatal

metrics:                                  # any registered metric; params go to its constructor
  - name: tool_call_accuracy
    params: {threshold: 0.8, weight: 2.0}
  - name: trajectory_match
    params: {mode: in_order, source: tools}
  - name: geval
    params: {name: geval_tone, criteria: "Professional, concise, no blame on the employee."}
  - name: policy_compliance
    params:
      banned_patterns: ["(?i)\\bguarantee(d)?\\b", "(?i)password is"]
      required_patterns: []

security:
  redact_pii_for_judge: true              # redact PII before any text leaves for an external judge
  audit_log: reports/audit.jsonl          # hash-chained, tamper-evident; null to disable
  max_input_chars: 20000                  # dataset input size limit
  max_cases: 5000                         # dataset size limit
  allowed_target_modules: ["examples.", "my_company.agents."]   # CLI --target allow-list

observability:
  log_level: ${AGENTIC_EVAL_LOG_LEVEL:-INFO}
  json_logs: true
  otel_enabled: ${AGENTIC_EVAL_OTEL:-false}
  service_name: agentic-eval

reporting:
  output_dir: reports
  formats: [json, markdown, junit]
  include_traces: false                   # traces may contain business data — enable consciously

gate:
  min_pass_rate: 1.0                      # share of cases that must fully pass
  min_mean_score: 0.8                     # weighted mean case score
  blocking_categories: [safety]           # ANY failure in these categories fails the gate
  metric_min_means:                       # per-metric floor on the mean score
    tool_call_accuracy: 0.9
    handoff_accuracy: 0.9
```

Common metric params (all metrics): `threshold` (0–1), `weight` (for the weighted case score), `name`
(instance name, needed to use one metric twice). Metric-specific params are listed in
[03](03-metrics-catalogue.md).

### Recommended profiles

| Profile | Judge | Metrics | Gate |
|---|---|---|---|
| **PR / pre-commit** | `mock` | deterministic only (tool, trajectory, multi-agent D, safety D, budgets) | `min_pass_rate: 1.0`, `blocking_categories: [safety]` |
| **Main / release** | real judge | full suite | + `min_mean_score`, `metric_min_means` |
| **Nightly drift** | real judge, larger dataset | full suite | report-only; alert on delta vs. last run |
| **Production online** | real judge, sampled | reference-free subset | dashboards / alerts, no gate |

## Environment variables

| Variable | Purpose |
|---|---|
| `AGENTIC_EVAL_JUDGE`, `AGENTIC_EVAL_JUDGE_MODEL` | judge selection used by the sample config |
| `AGENTIC_EVAL_LOG_LEVEL`, `AGENTIC_EVAL_OTEL` | logging / telemetry toggles used by the sample config |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI or compatible gateway |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION` | Azure OpenAI (omit key → Entra ID) |
| `ANTHROPIC_API_KEY` | Anthropic judge |
| `OTEL_EXPORTER_OTLP_ENDPOINT` … | standard OpenTelemetry SDK settings |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` / `LANGSMITH_API_KEY` | exporters |

See [`.env.example`](../.env.example).

## CLI

Installed as `agentic-eval` (also `python -m agentic_eval.cli`).

| Command | Purpose |
|---|---|
| `agentic-eval list-metrics` | all registered metrics with category and judge flag |
| `agentic-eval run --config C --dataset D --target module.path:callable [--tags t1 t2] [--output-dir DIR]` | execute the target on each case, evaluate, write reports, apply the gate |
| `agentic-eval eval-traces --config C --dataset D --traces traces.jsonl [--output-dir DIR]` | evaluate pre-recorded `Trace` JSONL (each with `metadata.case_id`) |
| `agentic-eval verify-audit reports/audit.jsonl` | verify the audit hash chain |

**Exit codes:** `0` gate passed / audit intact · `1` gate failed / audit tampered · `2` configuration or input error.

`--target` must start with one of `security.allowed_target_modules` — this prevents a config/CI variable from
importing arbitrary code. Add your package prefix (e.g. `my_company.agents.`).

The `run` command prints a JSON summary to stdout (run id, pass rate, mean score, gate verdict, violations,
report paths) and structured logs to stderr — pipe-friendly for CI.

## Programmatic API cheat sheet

```python
from agentic_eval import (Evaluator, EvalCase, QualityGate, create_metric, create_judge,
                          load_dataset, list_metrics, OnlineEvaluator)
from agentic_eval.core.config import load_config
from agentic_eval.reporting import write_reports

cfg = load_config("config/eval_config.yaml")
evaluator = Evaluator.from_config(cfg)
report = evaluator.run(target, load_dataset("dataset.jsonl", tags=["security"]))   # or: await evaluator.arun(...)
verdict = QualityGate(**cfg.gate.model_dump()).evaluate(report)
write_reports(report, "reports", ["json", "markdown", "junit"], verdict)

report.summary()                 # pass_rate, mean_score, per-metric & per-category aggregates
report.cases[0].results          # list[MetricResult]
report.cases[0].failed_metrics() # what failed and why (reason, details)
```
