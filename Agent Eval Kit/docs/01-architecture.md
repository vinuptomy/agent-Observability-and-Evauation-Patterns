# 01 · Architecture

## Design principles

1. **Evaluate the trajectory, not just the answer.** In multi-agent systems most failures (wrong delegation,
   tool misuse, loops, leaked secrets, privileged actions) are invisible in the final text. Every metric
   therefore operates on a full `Trace` of agent, LLM, tool, retrieval, handoff and guardrail spans.
2. **Framework-agnostic by normalisation.** Adapters translate each framework's native events into one
   `Trace` model. Metrics never import a framework. Adding a framework means writing an adapter, not
   touching metrics.
3. **Deterministic first, LLM-judge second.** Cheap, reproducible metrics (F1, budget, regex, checksum) run
   everywhere; LLM judges are reserved for semantic questions (correctness, faithfulness, role adherence).
4. **Secure by default.** PII is redacted before leaving for a judge; agent output given to a judge is
   treated as untrusted; dynamic imports are allow-listed; every run is written to a hash-chained audit log.
5. **A failing agent is a result, not a crash.** Target exceptions and timeouts are recorded on the trace and
   scored; the evaluator itself keeps running (per-case isolation).
6. **Minimal core, optional extras.** Core depends only on `pydantic` and `PyYAML`. Framework and provider
   SDKs are lazily imported extras.

## Component view

```
                      ┌────────────────────────── agentic_eval ─────────────────────────────┐
  your agents         │                                                                      │
  ───────────         │  collectors/        adapters/                                        │
  LangGraph   ──────► │  Tracer ◄────────── langchain · crewai · autogen · openai_agents     │
  CrewAI      ──────► │  @trace_agent       otel (GenAI semconv + OpenInference)             │
  AutoGen     ──────► │  @trace_tool                 │                                       │
  Agents SDK  ──────► │  handoff()                   ▼                                       │
  OTel spans  ──────► │                     core/models.Trace ──► runners/Evaluator ──┐      │
  custom code ──────► │                                            │  (async, bounded │      │
                      │                          metrics/ ◄────────┘   concurrency,    │      │
                      │   task · tool · trajectory · multi_agent       timeouts)       │      │
                      │   rag · safety · performance · custom          │               │      │
                      │          │ uses                                 ▼               │      │
                      │   judges/ (redaction, retries, JSON)     runners/QualityGate    │      │
                      │   bridges/ (Ragas, DeepEval)                    │               │      │
                      │                                                 ▼               ▼      │
                      │   security/ audit · pii · injection    reporting/  observability/      │
                      │                                        json·md·junit  logs·OTel·       │
                      │                                                       Langfuse·LangSmith│
                      └──────────────────────────────────────────────────────────────────────┘
```

## Data model (`core/models.py`)

| Model | Purpose | Key fields |
|---|---|---|
| `Span` | One step | `kind` (AGENT, LLM, TOOL, HANDOFF, RETRIEVAL, GUARDRAIL, CHAIN), `agent`, `name`, `parent_id`, timings, `input`/`output`, `tool_call`, `handoff_from/to`, tokens, `cost_usd`, `error` |
| `ToolCall` | Tool invocation | `name`, `arguments`, `output`, `error` |
| `Trace` | One end-to-end run | `input`, `final_output`, `spans`, `error`, `metadata` + helpers: `tool_names`, `tool_calls`, `agent_sequence`, `handoffs`, `retrieved_contexts`, `step_count`, `agents`, `total_tokens`, `total_cost_usd`, `duration_ms`, `errors`, `output_text`, `summary()` |
| `EvalCase` | One test case (the "ground truth") | `input`, `expected_output`, `expected_tools`, `expected_tool_args`, `forbidden_tools`, `expected_trajectory`, `expected_agents`, `expected_handoffs`, `agent_roles`, `reference_contexts`, `rubric`, `constraints`, `canary`, `tags`, `metadata` |
| `MetricResult` | One metric on one case | `score ∈ [0,1]`, `threshold`, `passed`, `weight`, `reason`, `details`, `skipped`, `error` |
| `CaseResult` | All metrics on one case | `results`, `passed`, weighted `score`, `trace_summary` |
| `EvalReport` | A run | `cases`, `config`, `summary()` (pass rate, mean score, per-metric and per-category stats) |

## Metric contract (`core/metric.py`)

```python
class BaseMetric(ABC):
    name: ClassVar[str]
    category: ClassVar[MetricCategory]    # TASK, TOOL, TRAJECTORY, MULTI_AGENT, RAG, SAFETY, PERFORMANCE, QUALITY
    requires: ClassVar[tuple[str, ...]]   # EvalCase fields that must be non-empty — otherwise the metric is SKIPPED
    uses_judge: ClassVar[bool]
    default_threshold: ClassVar[float]

    async def compute(self, trace, case) -> float | bool | (score, reason) | (score, reason, details)
```

`evaluate()` (template method) handles applicability checks, error capture, clamping, threshold comparison
and timing. Metrics are registered by name (`@register_metric`) so YAML config and the CLI can create them.

**Skip vs. fail.** A metric whose required ground truth is missing is *skipped*, not failed. This lets one
configuration serve heterogeneous datasets: a RAG case without `expected_handoffs` simply doesn't get
`handoff_accuracy`.

## Execution flow (`Evaluator.run`)

1. For each case, open a `Tracer` (context-var based, async-safe) and call `target(case.input)`.
   Sync targets run in a worker thread with the context copied, so the tracer stays active.
2. Adapters/decorators inside the target append spans to the active tracer. If the target returns a
   `Trace`, it is used directly.
3. All metrics run concurrently on the trace; LLM-judge calls share the judge's semaphore.
4. Results are aggregated into `CaseResult` → `EvalReport`; telemetry and audit events are emitted.
5. `QualityGate.evaluate(report)` returns a verdict with human-readable violations.

## Extension points

| Extend | How | Doc |
|---|---|---|
| New framework | Write an adapter that produces `Span`s on `Tracer.current()` or returns a `Trace` | [02](02-integration-guide.md#writing-your-own-adapter) |
| New metric | `@function_metric` for a one-liner, `BaseMetric` subclass + `@register_metric` for reusable metrics | [03](03-metrics-catalogue.md#custom-metrics) |
| New judge / LLM gateway | Subclass `BaseJudge`, implement `_complete`, `register_judge(name, cls)` | [06](06-llm-judges.md#custom-judge) |
| Third-party metric | `RagasMetric(...)`, `DeepEvalMetric(...)` | [03](03-metrics-catalogue.md#bridges-to-ragas-and-deepeval) |
| New sink | Consume `EvalReport` (pydantic) or `OnlineEvaluator(on_result=...)` | [08](08-observability-and-online-eval.md) |
