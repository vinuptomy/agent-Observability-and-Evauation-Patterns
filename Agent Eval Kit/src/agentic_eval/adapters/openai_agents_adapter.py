"""OpenAI Agents SDK adapter — a ``TracingProcessor`` that mirrors SDK spans into Traces.

    from agents import add_trace_processor, Runner
    processor = AgentEvalTracingProcessor()
    add_trace_processor(processor)
    result = await Runner.run(triage_agent, "...")
    trace = processor.pop_latest(final_output=result.final_output)
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from agentic_eval.collectors.tracer import _jsonable
from agentic_eval.core.models import Span, SpanKind, ToolCall, Trace


def _ts(value: Any) -> float:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()
    return float(value) if value else time.time()


class AgentEvalTracingProcessor:
    """Implements the SDK's TracingProcessor protocol (duck-typed — no hard dependency)."""

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}
        self._agent_of_span: dict[str, str] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    # protocol ----------------------------------------------------------------------------
    def on_trace_start(self, trace: Any) -> None:
        with self._lock:
            self._traces[trace.trace_id] = Trace(trace_id=trace.trace_id.replace("trace_", "")[:32] or trace.trace_id,
                                                 name=getattr(trace, "name", "openai-agents"),
                                                 metadata={"openai_trace_id": trace.trace_id})
            self._order.append(trace.trace_id)

    def on_trace_end(self, trace: Any) -> None:
        t = self._traces.get(trace.trace_id)
        if t:
            t.end_time = time.time()

    def on_span_start(self, span: Any) -> None:
        data = span.span_data
        if getattr(data, "type", "") == "agent":
            self._agent_of_span[span.span_id] = data.name

    def on_span_end(self, span: Any) -> None:
        t = self._traces.get(span.trace_id)
        if t is None:
            return
        data = span.span_data
        kind = getattr(data, "type", "custom")
        agent = self._resolve_agent(span)
        common = dict(span_id=span.span_id, parent_id=span.parent_id, agent=agent, start_time=_ts(span.started_at),
                      end_time=_ts(span.ended_at), error=str(span.error)[:500] if span.error else None)
        if kind == "agent":
            t.spans.append(Span(kind=SpanKind.AGENT, name=data.name, **common))
        elif kind == "function":
            tc = ToolCall(name=data.name, arguments=_parse(getattr(data, "input", None)),
                          output=_jsonable(getattr(data, "output", None)), error=common["error"])
            t.spans.append(Span(kind=SpanKind.TOOL, name=data.name, tool_call=tc, input=tc.arguments,
                                output=tc.output, **common))
        elif kind == "handoff":
            t.spans.append(Span(kind=SpanKind.HANDOFF, name="handoff", handoff_from=data.from_agent,
                                handoff_to=data.to_agent, **common))
        elif kind in ("generation", "response"):
            usage = getattr(data, "usage", None) or getattr(getattr(data, "response", None), "usage", None) or {}
            get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
            t.spans.append(Span(kind=SpanKind.LLM, name=getattr(data, "model", None) or "model",
                                model=getattr(data, "model", None), input_tokens=int(get("input_tokens", 0) or 0),
                                output_tokens=int(get("output_tokens", 0) or 0), **common))
        elif kind == "guardrail":
            t.spans.append(Span(kind=SpanKind.GUARDRAIL, name=data.name,
                                output={"triggered": getattr(data, "triggered", False)}, **common))

    def shutdown(self) -> None:  # pragma: no cover
        pass

    def force_flush(self) -> None:  # pragma: no cover
        pass

    # helpers -----------------------------------------------------------------------------
    def _resolve_agent(self, span: Any) -> str | None:
        if getattr(span.span_data, "type", "") == "agent":
            return span.span_data.name
        return self._agent_of_span.get(span.parent_id) if span.parent_id else None

    def pop_latest(self, final_output: Any = None) -> Trace:
        with self._lock:
            trace_id = self._order.pop()
            trace = self._traces.pop(trace_id)
        trace.final_output = _jsonable(final_output)
        trace.spans.sort(key=lambda s: s.start_time)
        return trace


def _parse(raw: Any) -> dict[str, Any]:
    import json
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {"input": v}
    except (TypeError, ValueError):
        return {"input": raw}
