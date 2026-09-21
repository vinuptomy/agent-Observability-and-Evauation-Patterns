# 11 · Troubleshooting & FAQ

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `ConfigurationError: metric 'task_completion' needs a judge` | Judge metric without a judge | `Evaluator([...], judge=create_judge("mock"))` or set `judge:` in YAML |
| `ConfigurationError: duplicate metric names` | Same metric configured twice | Give each instance a distinct `name` param |
| `Unknown metric 'x'` | Custom metric module not imported | Import the module defining it before `Evaluator.from_config` |
| `Unknown judge provider` | Typo or custom judge not registered | `register_judge("name", Cls)` before creating the evaluator |
| `ImportError: pip install 'agentic-eval-kit[langchain]'` | Optional extra missing | Install the extra named in the message |
| CLI exit code 2: target not allowed | `--target` outside the allow-list | Add your package prefix to `security.allowed_target_modules` |
| All multi-agent metrics skipped | Case lacks `expected_agents` / `expected_handoffs` | Add expectations (skipped ≠ failed) |
| `handoff_accuracy` 0 although routing looks right | Agent names in dataset ≠ names in trace | Print `report.cases[0].trace_summary` and align names (LangGraph node names, CrewAI roles, …) |
| Empty trace (no spans) | Adapter created outside the Evaluator's tracer, or framework runs in a thread/process that loses context vars | Create the handler/adapter *inside* `target`; for thread pools pass `tracer=Tracer.current()` explicitly; for separate processes return a `Trace` or use OTel import |
| `RuntimeError` about running event loop | Calling `evaluator.run()` inside async code (Jupyter, FastAPI) | Use `await evaluator.arun(...)` |
| `latency_budget` fails only in CI | Shared runners are slower | Use higher budgets in CI or run budgets in a dedicated perf job |
| Judge metric has `error` set | Timeout, rate limit, non-JSON reply | Increase `timeout_s` / `max_retries`, lower `max_concurrency`, check model supports JSON mode |
| `audit log TAMPERED at line N` | File edited, truncated or two runs wrote concurrently | Investigate; use one audit file per pipeline run/job |
| Mock judge scores look arbitrary | It's a lexical heuristic by design | Use a real judge for quality signals; mock is for pipeline tests |

## FAQ

**Do I need to change my agent code?**
No for LangChain/LangGraph (callback), CrewAI (callbacks), AutoGen (result conversion), OpenAI Agents SDK
(trace processor) and OTel-instrumented frameworks. For custom code, add decorators — they are no-ops outside
evaluation.

**Is it a replacement for Ragas / DeepEval / LangSmith / Langfuse / Phoenix?**
No — it's the glue and the multi-agent layer. It uses their methods, can wrap Ragas and DeepEval metrics
directly, and exports scores to Langfuse and LangSmith. You get one dataset, one gate and one report across
all of them, independent of the agent framework.

**How many test cases do I need?**
Start with 10–20 golden cases covering each intent and route, plus 3–5 adversarial cases. Grow to 100+ as
production failures come in. For LLM-judged metrics, larger sets reduce noise.

**How do I deal with non-deterministic agents?**
Use deterministic metrics for gating where possible, `in_order`/`superset` trajectory modes instead of
`strict`, `min_pass_rate` slightly below 1.0 on large suites, and repeat critical cases (duplicate them with
different `case_id`s) to measure stability.

**Can it evaluate agents written in .NET / Java / Copilot Studio?**
Yes — as a black box via an HTTP target, and with full trajectory metrics if the service emits OpenTelemetry
spans (import them with `trace_from_otel_spans`). Semantic Kernel (.NET) emits GenAI semconv spans natively.

**Can I run it air-gapped?**
Yes. The core has two dependencies; use the `mock` judge or an on-prem OpenAI-compatible model via
`base_url`.

**Where do I start with an existing app?**
1. Pick the adapter from [02](02-integration-guide.md). 2. Write 5 cases. 3. Run with deterministic metrics
and the mock judge. 4. Add safety cases and the gate. 5. Switch to a real judge on `main`. 6. Add
`OnlineEvaluator` in production.
