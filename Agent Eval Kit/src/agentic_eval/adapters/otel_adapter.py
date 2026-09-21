"""OpenTelemetry importer — the universal adapter.

Any framework that emits OTel spans with the **GenAI semantic conventions** (``gen_ai.*``) or the
**OpenInference** conventions (Arize Phoenix, LlamaIndex, DSPy, Bedrock, Semantic Kernel, Google ADK,
Strands, smolagents via OpenLLMetry/OpenInference instrumentors) can be evaluated by exporting spans
(OTLP JSON or in-memory SDK spans) and converting them here.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from agentic_eval.core.models import Span, SpanKind, ToolCall, Trace


def _attrs(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    out: dict[str, Any] = {}
    for kv in raw or []:  # OTLP JSON: [{"key": "...", "value": {"stringValue": "..."}}]
        val = kv.get("value", {})
        out[kv["key"]] = next(iter(val.values()), None) if isinstance(val, dict) else val
    return out


def _normalize(span: Any) -> dict[str, Any]:
    if isinstance(span, dict):
        return {
            "name": span.get("name", "span"),
            "span_id": span.get("spanId") or span.get("span_id") or (span.get("context") or {}).get("span_id"),
            "parent_id": span.get("parentSpanId") or span.get("parent_id") or span.get("parent_span_id"),
            "trace_id": span.get("traceId") or span.get("trace_id") or (span.get("context") or {}).get("trace_id"),
            "start": int(span.get("startTimeUnixNano") or span.get("start_time") or 0),
            "end": int(span.get("endTimeUnixNano") or span.get("end_time") or 0),
            "attributes": _attrs(span.get("attributes")),
            "error": (span.get("status") or {}).get("code") in ("STATUS_CODE_ERROR", 2, "ERROR"),
        }
    ctx, parent = span.get_span_context(), getattr(span, "parent", None)  # opentelemetry.sdk ReadableSpan
    return {"name": span.name, "span_id": format(ctx.span_id, "016x"),
            "parent_id": format(parent.span_id, "016x") if parent else None, "trace_id": format(ctx.trace_id, "032x"),
            "start": span.start_time or 0, "end": span.end_time or 0, "attributes": dict(span.attributes or {}),
            "error": getattr(span.status.status_code, "name", "") == "ERROR"}


def _json_attr(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _kind(a: dict[str, Any]) -> SpanKind:
    op = str(a.get("gen_ai.operation.name", "")).lower()
    oi = str(a.get("openinference.span.kind", "")).upper()
    if op in ("invoke_agent", "create_agent") or oi == "AGENT":
        return SpanKind.AGENT
    if op == "execute_tool" or oi == "TOOL":
        return SpanKind.TOOL
    if op in ("chat", "text_completion", "generate_content", "embeddings") or oi in ("LLM", "EMBEDDING"):
        return SpanKind.LLM
    if oi == "RETRIEVER":
        return SpanKind.RETRIEVAL
    if oi == "GUARDRAIL":
        return SpanKind.GUARDRAIL
    return SpanKind.CHAIN


def trace_from_otel_spans(spans: Iterable[Any], final_output: Any = None, input: Any = None) -> Trace:
    norm = sorted((_normalize(s) for s in spans), key=lambda s: s["start"])
    trace = Trace(name="otel", input=input, final_output=final_output)
    if norm:
        trace.trace_id = str(norm[0]["trace_id"] or trace.trace_id)
        trace.start_time = norm[0]["start"] / 1e9
        trace.end_time = max(s["end"] for s in norm) / 1e9
    agent_of: dict[str, str | None] = {}
    by_id = {s["span_id"]: s for s in norm}
    for s in norm:
        a = s["attributes"]
        kind = _kind(a)
        own_agent = a.get("gen_ai.agent.name") or a.get("agent.name") or (s["name"] if kind == SpanKind.AGENT else None)
        parent_agent = agent_of.get(s["parent_id"]) if s["parent_id"] else None
        agent = own_agent or parent_agent
        agent_of[s["span_id"]] = agent
        common = dict(span_id=s["span_id"] or None, parent_id=s["parent_id"], agent=agent, name=s["name"],
                      start_time=s["start"] / 1e9, end_time=s["end"] / 1e9,
                      error=a.get("error.type") or ("error" if s["error"] else None),
                      input_tokens=int(a.get("gen_ai.usage.input_tokens") or a.get("llm.token_count.prompt") or 0),
                      output_tokens=int(a.get("gen_ai.usage.output_tokens") or a.get("llm.token_count.completion") or 0),
                      model=a.get("gen_ai.request.model") or a.get("llm.model_name"))
        common = {k: v for k, v in common.items() if v is not None}
        if kind == SpanKind.TOOL:
            name = a.get("gen_ai.tool.name") or a.get("tool.name") or s["name"]
            args = _json_attr(a.get("gen_ai.tool.call.arguments") or a.get("tool.parameters") or a.get("input.value") or {})
            args = args if isinstance(args, dict) else {"input": args}
            out = _json_attr(a.get("gen_ai.tool.call.result") or a.get("output.value"))
            common["name"] = name
            trace.spans.append(Span(kind=kind, tool_call=ToolCall(name=name, arguments=args, output=out,
                                                                  error=common.get("error")),
                                    input=args, output=out, **common))
        elif kind == SpanKind.RETRIEVAL:
            docs = [v for k, v in a.items() if k.startswith("retrieval.documents.") and k.endswith(".document.content")]
            trace.spans.append(Span(kind=kind, output=docs, input=a.get("input.value"), **common))
        else:
            trace.spans.append(Span(kind=kind, output=_json_attr(a.get("output.value")), **common))
        # nested agent invocation by a different agent == delegation / handoff
        if kind == SpanKind.AGENT and parent_agent and own_agent and parent_agent != own_agent:
            trace.spans.append(Span(kind=SpanKind.HANDOFF, name=f"{parent_agent}->{own_agent}", agent=parent_agent,
                                    handoff_from=parent_agent, handoff_to=own_agent, start_time=s["start"] / 1e9,
                                    end_time=s["start"] / 1e9))
        if trace.input is None and s["parent_id"] not in by_id:
            trace.input = a.get("input.value")
    return trace
