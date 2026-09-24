# Architecture

## Components

| Layer | Module | Responsibility |
|---|---|---|
| Interface | `cli.py`, `api/app.py` | CLI and REST entry points; session/user ids; feedback annotations |
| Composition | `agents/factory.py` | Builds agents from `AgentSpec`: prompt, LLM, tools, guardrails, approval |
| Orchestration | `core/agent.py` | Context propagation scope, bounded tool-calling loop, tool policy, result assembly |
| Model access | `core/llm.py` | Provider-agnostic `LLMClient`; retries; LLM spans with token counts |
| Tools & retrieval | `core/tools.py`, `agents/enterprise_tools.py`, `core/retrieval.py` | Typed tools, tool spans, retriever span with documents |
| Security | `security/*` | Guardrails, PII redaction, human approval |
| Observability | `observability/*` | OTel/OpenInference spans, attributes, annotations, usage/cost |
| Evaluation | `evaluation/*` | Dataset, agent + RAG metrics, offline gate, Phoenix experiments |

## Agent loop

1. `run()` opens an `using_attributes` scope: session id, user id, tags
   (`agent`, `environment`, `provider`) and metadata (agent version, model, release).
2. `_run()` is the root **agent** span.
3. Input guardrail (**guardrail** span). If blocked, return a refusal **without calling the LLM**
   and annotate the span `input_guardrail_pass=0` (annotator kind `CODE`).
4. For step 1..`AGENT_MAX_STEPS`:
   * `llm.chat(...)` — an **llm** span with model, provider, invocation parameters and token counts.
   * Each tool call: allowlist check → approval check (high-risk) → validated execution
     (**tool** span). The knowledge-base tool nests a **retriever** span carrying the retrieved
     documents (id, content, score).
   * Otherwise: output guardrail, annotate, return.
5. Step budget exhausted → `status=max_steps` with an escalation message.

Retrieved document ids are collected into `AgentResult.retrieved_ids`, which is what the retrieval
metrics score.

## Why the run/`_run` split

OpenTelemetry context attributes must be set **before** the root span starts for every child span to
inherit them. The public `run()` opens the `using_attributes` scope; the decorated `_run()` creates
the root span inside it.

## Trace portability

Nothing in the agent code imports Phoenix directly — only `observability/tracing.py` does, and even
there the span creation uses an OpenInference tracer over standard OTLP. Consequences:

* Point `PHOENIX_COLLECTOR_ENDPOINT` at any OTLP collector and tracing keeps working.
* Phoenix-specific features (datasets, experiments, annotations) go through the REST client and
  degrade gracefully when it is unavailable.

## Key design decisions

* **Fail-open observability.** Every tracing call is guarded; a dead collector cannot break a run.
* **Redact before export.** Payloads are serialised and PII-redacted in `to_safe_payload` before
  being set as span attributes; document content is redacted too.
* **Least privilege per agent.** Tool schemas are filtered by the allowlist *and* re-checked at
  execution time.
* **Annotations off the hot path (optional).** `PHOENIX_ANNOTATE_GUARDRAILS=false` disables the
  per-run REST call in high-volume deployments; span attributes still carry the outcome.
* **Same metrics, two runners.** Offline CI and Phoenix experiments share the metric functions.
