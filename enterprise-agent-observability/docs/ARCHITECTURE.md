# Architecture

## Components

| Layer | Module | Responsibility |
|---|---|---|
| Interface | `cli.py`, `api/app.py` | CLI and REST entry points; session and user IDs |
| Composition | `agents/factory.py` | Builds agents from `AgentSpec`: prompt, LLM, tools, guardrails, approval |
| Orchestration | `core/agent.py` | Bounded tool-calling loop, tool policy, result assembly |
| Model access | `core/llm.py` | Provider-agnostic `LLMClient` protocol; retries with backoff |
| Tools | `core/tools.py`, `agents/enterprise_tools.py` | Typed tools, JSON schema, validation, risk metadata |
| Security | `security/*` | Guardrails, PII, approvals |
| Observability | `observability/*` | Opik spans, trace metadata, feedback scores, usage/cost |
| Evaluation | `evaluation/*` | Datasets, metrics, local gate, Opik experiments |

## Agent loop

1. Update the trace with agent name, version, model, environment, `thread_id=session_id`.
2. Input guardrail. If blocked, return a refusal **without calling the LLM** and log feedback `input_guardrail_pass=0`.
3. For step 1..`AGENT_MAX_STEPS`:
   * `llm.chat(messages, tools)`, recording token usage.
   * If there are tool calls, for each: allowlist check → approval check (high-risk) → validated execution → append output wrapped in `<tool_output>` (untrusted).
   * Otherwise, run the output guardrail and return.
4. If the step budget is exhausted, return `status=max_steps` with an escalation message.

## Opik trace hierarchy

```
trace  agent:it_helpdesk          tags=[it_helpdesk, prod, azure]  thread_id=<session>
└─ span agent.run                 (general)   redacted input/output
   ├─ span guardrail.input        (guardrail)
   ├─ span llm.chat               (llm)       usage, model, provider
   ├─ span tool:search_knowledge_base (tool)  risk metadata, validated args
   ├─ span llm.chat               (llm)
   └─ span guardrail.output       (guardrail)
feedback scores: input_guardrail_pass, output_guardrail_pass
metadata: status, steps, tools, latency_ms, tokens, estimated_cost_usd, agent_version
```

## Key design decisions

* **Fail-open observability.** Tracing errors are swallowed and logged at debug level; the business flow never depends on Opik availability.
* **Redact before export.** Span I/O is serialised and PII-redacted inside our decorator (`capture_input=False` on Opik), so raw PII never leaves the process.
* **Least privilege per agent.** Tool schemas sent to the model are filtered by the allowlist, *and* calls are re-checked at execution time (the model can hallucinate tool names).
* **Deterministic mock LLM.** Makes tests, demos and CI reproducible; the same trace and eval pipeline is used for real models.
* **Single composition root.** Swapping a provider, retriever or approval workflow happens in one place.
