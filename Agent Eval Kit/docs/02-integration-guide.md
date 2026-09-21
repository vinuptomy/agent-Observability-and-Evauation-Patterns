# 02 · Integration guide — plugging the module into existing agentic apps

This guide shows how to attach `agentic-eval-kit` to an **existing** application without restructuring it.
Every path ends in the same place: a `Trace` that the `Evaluator` scores.

## The universal pattern (read this first)

```python
from agentic_eval import Evaluator, create_metric, create_judge, load_dataset

def target(user_input: str):          # 1. a thin wrapper around your existing entry point
    ...                               #    attach an adapter / use decorators, call your app
    return answer                     #    return the final answer (str/dict) OR a Trace

evaluator = Evaluator(                # 2. choose metrics (or Evaluator.from_config("config/eval_config.yaml"))
    [create_metric("task_completion"), create_metric("tool_call_accuracy"), create_metric("handoff_accuracy")],
    judge=create_judge("mock"),       #    "azure_openai" / "openai" / "anthropic" in real runs
)
report = evaluator.run(target, load_dataset("evals/dataset.jsonl"))   # 3. run (use `await evaluator.arun` in async code)
```

**Why it works with any framework.** Before calling `target`, the `Evaluator` opens a `Tracer` and makes it
the *current* tracer via a context variable. Every adapter and decorator calls `Tracer.current()` and appends
spans to it — so you do not pass the tracer around. Sync targets are run in a worker thread with the context
copied; async targets are awaited directly.

Your target can be **sync or async**, and may return:

* a plain answer (`str`, `dict`, pydantic model) → becomes `trace.final_output`
* a `Trace` → used as-is (adapters that build their own trace, e.g. AutoGen/OpenAI Agents SDK)

Choose your integration path:

| You have… | Use | Effort |
|---|---|---|
| LangGraph / LangChain | [Callback handler](#langgraph--langchain) | 1 line |
| CrewAI | [CrewAIAdapter](#crewai) | 2 lines |
| AutoGen AgentChat | [TaskResult converter](#autogen-agentchat) | 1 line |
| OpenAI Agents SDK | [Tracing processor](#openai-agents-sdk) | 2 lines |
| Anything emitting OpenTelemetry | [OTel importer](#any-framework-via-opentelemetry) | 0 code changes |
| Custom Python orchestration | [Decorators](#custom-code-decorators) | 1 decorator per agent/tool |
| A remote agent (REST, queue, other language) | [HTTP / black-box targets](#remote-or-non-python-agents) | wrapper function |
| Logs/traces already stored | [Offline trace evaluation](#offline-trace-evaluation) | converter |

---

## LangGraph / LangChain

```bash
pip install "agentic-eval-kit[langchain]"
```

```python
from agentic_eval.adapters.langchain_adapter import AgentEvalCallbackHandler

app = build_graph()                                   # your compiled LangGraph — unchanged

def target(user_input: str) -> str:
    handler = AgentEvalCallbackHandler()              # binds to the Evaluator's active Tracer
    result = app.invoke({"messages": [("user", user_input)]}, config={"callbacks": [handler]})
    return result["messages"][-1].content
```

What is captured:

| LangChain event | Span |
|---|---|
| Graph node start/end (`metadata["langgraph_node"]`) | `AGENT` span named after the node |
| Transition between nodes | `HANDOFF` (`from → to`) |
| `on_tool_start/end/error` | `TOOL` span with arguments, output, error |
| `on_chat_model_start` / `on_llm_end` | `LLM` span with model, token usage |
| `on_retriever_start/end` | `RETRIEVAL` span with document contents (feeds RAG metrics) |

Options: `AgentEvalCallbackHandler(agent_key="langgraph_node", ignore_nodes=("__start__", "__end__"))`.
If your agents are sub-graphs or you tag runs differently, set `agent_key` to the metadata key holding the
agent name. For supervisor graphs built with `langgraph-supervisor`/`create_react_agent`, node names become the
agent names you reference in `expected_agents` / `expected_handoffs`.

Async: use `await app.ainvoke(..., config={"callbacks": [handler]})` inside an `async def target`.

Runnable: [`examples/integrations/langgraph_supervisor.py`](../examples/integrations/langgraph_supervisor.py)

---

## CrewAI

```bash
pip install "agentic-eval-kit[crewai]"
```

```python
from agentic_eval.adapters.crewai_adapter import CrewAIAdapter

def target(user_input: str):
    adapter = CrewAIAdapter()
    crew = adapter.instrument(build_crew())           # sets crew.step_callback / task_callback
    output = crew.kickoff(inputs={"request": user_input})
    return adapter.finish(output)                     # Trace incl. final output + token usage
```

Mapping: each agent step → `TOOL` span (tool name, parsed input, observation) and `LLM` span (the agent's
thought); each completed task → `AGENT` span with its output; a change of task owner → `HANDOFF`; `CrewOutput.token_usage` → LLM usage span. Agent names are the CrewAI `role` strings, so use those
in `expected_agents`. If you already use `step_callback`, call `adapter.step_callback(step)` from your own
callback instead of `instrument()`.

Runnable: [`examples/integrations/crewai_crew.py`](../examples/integrations/crewai_crew.py)

---

## AutoGen AgentChat

```bash
pip install "agentic-eval-kit[autogen]"
```

```python
from agentic_eval.adapters.autogen_adapter import trace_from_autogen_result

async def target(user_input: str):
    result = await team.run(task=user_input)          # RoundRobinGroupChat, SelectorGroupChat, Swarm, ...
    return trace_from_autogen_result(result, task=user_input)
```

Mapping: `TextMessage` source changes → `AGENT` spans and handoffs; `ToolCallRequestEvent` +
`ToolCallExecutionEvent` → `TOOL` spans (arguments parsed from JSON, errors from `is_error`);
`HandoffMessage` → explicit `HANDOFF`; `models_usage` → tokens. Also works for `team.run_stream(...)` if you
collect the final `TaskResult`.

Runnable: [`examples/integrations/autogen_team.py`](../examples/integrations/autogen_team.py)

---

## OpenAI Agents SDK

```bash
pip install "agentic-eval-kit[openai-agents]"
```

```python
from agents import Runner, add_trace_processor
from agentic_eval.adapters.openai_agents_adapter import AgentEvalTracingProcessor

PROCESSOR = AgentEvalTracingProcessor()
add_trace_processor(PROCESSOR)                       # once, at startup (keeps the default exporter)

async def target(user_input: str):
    result = await Runner.run(triage_agent, user_input)
    return PROCESSOR.pop_latest(final_output=result.final_output)
```

Mapping: agent / generation / response / function / handoff / guardrail spans of the SDK map one-to-one to
`AGENT` / `LLM` / `TOOL` / `HANDOFF` / `GUARDRAIL`. Use `set_trace_processors([PROCESSOR])` instead if you want
to *replace* the default OpenAI exporter (e.g. for data-residency reasons).

Runnable: [`examples/integrations/openai_agents_sdk.py`](../examples/integrations/openai_agents_sdk.py)

---

## Any framework via OpenTelemetry

The universal path — **no code changes in the agent**. Works for anything instrumented with the
**OpenTelemetry GenAI semantic conventions** (`gen_ai.operation.name`, `gen_ai.agent.name`,
`gen_ai.tool.name`, `gen_ai.usage.*`) or **OpenInference** (`openinference.span.kind`, `llm.token_count.*`,
`retrieval.documents.*`): Semantic Kernel, LlamaIndex, Google ADK, AWS Bedrock Agents / Strands, DSPy,
Pydantic AI, smolagents, Haystack, Arize Phoenix, OpenLLMetry/Traceloop instrumentors, Azure AI Foundry tracing.

```python
from agentic_eval.adapters.otel_adapter import trace_from_otel_spans

# A) in-process (tests): capture with the SDK's in-memory exporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider(); provider.add_span_processor(SimpleSpanProcessor(exporter))
# ... set provider as global / pass to your framework's instrumentor ...

def target(user_input: str):
    exporter.clear()
    answer = my_semantic_kernel_app(user_input)
    return trace_from_otel_spans(exporter.get_finished_spans(), final_output=answer, input=user_input)

# B) out-of-process: OTLP/JSON exported by a collector or file exporter
trace = trace_from_otel_spans(json.load(open("spans.json")), final_output=answer)
```

Mapping rules: `invoke_agent` / `AGENT` → agent span; a nested agent span owned by a different agent →
`HANDOFF(parent → child)`; `execute_tool` / `TOOL` → tool span (arguments from `gen_ai.tool.call.arguments`
or `tool.parameters`); `chat` / `LLM` → LLM span with token counts; `RETRIEVER` → retrieval span.
Both OTLP-JSON (`[{"key": ..., "value": {...}}]`) and plain-dict attributes are accepted.

Runnable offline: [`examples/integrations/otel_any_framework.py`](../examples/integrations/otel_any_framework.py)
(fixture: `examples/sample_traces/otel_genai_spans.json`).

---

## Custom code (decorators)

For hand-written orchestrators, FastAPI services or frameworks without an adapter:

```python
from agentic_eval import trace_agent, trace_tool, handoff, Tracer

@trace_tool()                                  # name defaults to the function name
def create_ticket(summary: str, priority: str) -> dict: ...

@trace_agent("triage_agent")
def triage(request: str) -> dict: ...

@trace_agent("supervisor")
async def supervisor(request: str) -> str:     # sync and async both supported
    plan = triage(request)
    handoff("supervisor", "resolution_agent", payload=plan)
    ...
    t = Tracer.current()
    if t:                                      # optional: LLM usage, retrieval, guardrails
        t.record_llm(prompt=request, output=answer, model="gpt-4o", input_tokens=812, output_tokens=96, cost_usd=0.004)
        t.record_retrieval(query=request, documents=[doc.text for doc in docs])
        t.record_guardrail("input_injection_filter", triggered=False)
    return answer
```

**Decorators are no-ops when no tracer is active**, so they are safe to leave in production code — zero
overhead outside evaluation. Tool exceptions are recorded on the span and re-raised (your error handling is
unchanged). The complete reference implementation is
[`examples/enterprise_it_service_desk/agents.py`](../examples/enterprise_it_service_desk/agents.py).

You can also record manually: `with Tracer.current().span("agent", "planner", agent="planner"): ...`.

---

## Remote or non-Python agents

Evaluate a deployed agent (Java/.NET/Node service, Copilot Studio, Azure AI Foundry Agent Service) as a black
box, and enrich with whatever telemetry it exposes:

```python
import httpx
from agentic_eval import Tracer

def target(user_input: str) -> str:
    r = httpx.post("https://agents.internal/api/chat", json={"message": user_input}, timeout=60)
    r.raise_for_status()
    body = r.json()
    t = Tracer.current()
    for step in body.get("steps", []):               # if the service returns its tool/agent steps
        if step["type"] == "tool":
            t.record_tool_call(step["name"], step.get("args", {}), output=step.get("result"), agent=step.get("agent"))
        elif step["type"] == "handoff":
            t.record_handoff(step["from"], step["to"])
    return body["answer"]
```

If the service emits OpenTelemetry, pull its spans by `trace_id` from your backend and use
`trace_from_otel_spans` — you get full trajectory metrics without changing the service.

---

## Offline trace evaluation

Evaluate traces you already have (production logs, recorded sessions, other teams' runs):

```python
from agentic_eval import Evaluator, Trace, load_dataset

cases = {c.case_id: c for c in load_dataset("evals/dataset.jsonl")}
traces = [Trace.model_validate_json(line) for line in open("traces.jsonl")]
report = Evaluator.from_config("config/eval_config.yaml").evaluate_traces(
    [(t, cases[t.metadata["case_id"]]) for t in traces])
```

CLI equivalent: `agentic-eval eval-traces --config ... --dataset ... --traces traces.jsonl`
(each trace must carry `metadata.case_id`). For unlabelled production traces, use reference-free metrics
(see [03](03-metrics-catalogue.md#reference-free-metrics)) with `EvalCase(input=...)`.

---

## Using it inside pytest

Agent evaluations fit naturally into your existing test suite:

```python
import pytest
from agentic_eval import Evaluator, QualityGate, create_metric, load_dataset

CASES = load_dataset("evals/dataset.jsonl")
EVALUATOR = Evaluator([create_metric(n) for n in ("tool_call_accuracy", "handoff_accuracy", "forbidden_tool_usage")])

@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_agent_case(case):
    result = EVALUATOR.run(my_target, [case]).cases[0]
    assert result.passed, [f"{r.metric}: {r.reason}" for r in result.failed_metrics()]

def test_release_gate():
    report = EVALUATOR.run(my_target, CASES)
    verdict = QualityGate(min_pass_rate=0.95, blocking_categories=["safety"]).evaluate(report)
    assert verdict.passed, verdict.violations
```

---

## Writing your own adapter

An adapter only needs to produce spans. Two styles:

```python
from agentic_eval import Span, SpanKind, ToolCall, Trace, Tracer

# Style 1 — streaming: append to the active tracer from the framework's callbacks/hooks
class MyFrameworkHook:
    def __init__(self):
        self.tracer = Tracer.current() or Tracer()
    def on_tool(self, agent, name, args, result):
        self.tracer.record_tool_call(name, args, output=result, agent=agent)
    def on_delegate(self, src, dst):
        self.tracer.record_handoff(src, dst)

# Style 2 — post-hoc: convert the framework's result object into a Trace
def trace_from_my_result(result) -> Trace:
    trace = Trace(input=result.task, final_output=result.answer)
    for ev in result.events:
        trace.spans.append(Span(kind=SpanKind.TOOL, name=ev.tool, agent=ev.agent,
                                tool_call=ToolCall(name=ev.tool, arguments=ev.args, output=ev.output)))
    return trace
```

Checklist for a good adapter: set `agent` on every span (multi-agent metrics depend on it), emit explicit
`HANDOFF` spans where the framework delegates, record tokens/cost on LLM spans, record tool errors in
`error`, and keep payloads JSON-serialisable (the tracer truncates large payloads to 4 000 chars).

## Mapping your agents to test expectations

| EvalCase field | Must match |
|---|---|
| `expected_agents` | the `agent` names produced by your adapter (LangGraph node names, CrewAI roles, AutoGen agent names, Agents SDK `Agent.name`) |
| `expected_handoffs` | `[from, to]` pairs of those names |
| `expected_tools` / `expected_trajectory` | tool names as registered in the framework |
| `expected_tool_args` | `{tool: {arg: value}}` — only the keys you care about |

Tip: run one case with `Evaluator(..., keep_traces=True)` and print `report.cases[0].trace_summary` to see
exactly which agent and tool names your framework produces before writing expectations.
