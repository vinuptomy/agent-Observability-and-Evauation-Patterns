# Architecture

## Components

| Layer | Module | Responsibility |
|---|---|---|
| Interface | `cli.py`, `api/app.py` | CLI and REST entry points; session id, user id, feedback ingestion |
| Composition | `agents/factory.py`, `agents/prompt_registry.py` | Builds agents from `AgentSpec`: prompt (file or Langfuse), LLM, tools, guardrails, approval |
| Orchestration | `core/agent.py` | Trace-attribute scope, bounded tool-calling loop, tool policy, result assembly |
| Model access | `core/llm.py` | Provider-agnostic `LLMClient`; retries with backoff; generation observations |
| Tools | `core/tools.py`, `agents/enterprise_tools.py` | Typed tools, JSON schema, validation, risk metadata |
| Security | `security/*` | Guardrails, PII redaction, human approval |
| Observability | `observability/*` | Langfuse client, masking, observations, scores, usage/cost |
| Evaluation | `evaluation/*` | Dataset, evaluator functions, offline gate, Langfuse experiments |

## Agent loop

1. `run()` opens a `propagate_attributes` scope: session id, user id, tags
   (`agent`, `environment`, `provider`), release/version and metadata.
2. `_run()` is the root `agent` observation.
3. Input guardrail (`guardrail` observation). If blocked, return a refusal **without calling the
   LLM** and score the trace `input_guardrail_pass=0`.
4. For step 1..`AGENT_MAX_STEPS`:
   * `llm.chat(messages, tools)` — a `generation` observation carrying model, model parameters and
     `usage_details`.
   * For each tool call: allowlist check → approval check (high-risk) → validated execution
     (`tool` observation) → output appended wrapped in `<tool_output>` (untrusted data).
   * If no tool call: output guardrail, score the trace, return.
5. Step budget exhausted → `status=max_steps`, escalation message, score
   `completed_within_step_budget=0`.

## Why the run/`_run` split

Langfuse propagates trace-level attributes through an OpenTelemetry context manager. Entering that
scope **before** the root observation starts is what lets the trace itself carry the session, user
and name — so the public `run()` opens the scope and the decorated `_run()` creates the root span.

## Key design decisions

* **Fail-open observability.** Every Langfuse call is wrapped; export errors are logged at debug
  level. Verified by a smoke test against an unreachable host.
* **Two layers of redaction.** Payloads are serialised and redacted by `to_safe_payload`; the SDK
  `mask` callback then runs on everything exported, including payloads captured by third-party
  instrumentation we do not control.
* **Least privilege per agent.** The tool schemas sent to the model are filtered by the allowlist
  *and* re-checked at execution time (models can hallucinate tool names).
* **Same evaluators, two runners.** Offline CI and Langfuse experiments share the evaluator
  functions, so a green gate and a green experiment mean the same thing.
* **Deterministic mock LLM.** Reproducible tests, demos and CI without an API key.
* **Single composition root.** Swapping provider, retriever, prompt source or approval workflow
  happens in one place.
