"""Microsoft AutoGen AgentChat (0.4+) adapter — converts a ``TaskResult`` into a Trace.

    result = await team.run(task="...")
    trace = trace_from_autogen_result(result, task="...")

Message types handled: TextMessage, ToolCallRequestEvent, ToolCallExecutionEvent, HandoffMessage,
ToolCallSummaryMessage (plus model usage). Works with RoundRobin, Selector and Swarm teams.
"""
from __future__ import annotations

import json
import time
from typing import Any

from agentic_eval.collectors.tracer import _jsonable
from agentic_eval.core.models import Span, SpanKind, ToolCall, Trace


def _type(msg: Any) -> str:
    return getattr(msg, "type", None) or type(msg).__name__


def trace_from_autogen_result(task_result: Any, task: str | None = None, user_source: str = "user") -> Trace:
    messages = list(getattr(task_result, "messages", task_result))
    trace = Trace(name="autogen", input=task)
    now = time.time()
    pending: dict[str, Span] = {}
    last_speaker: str | None = None
    for i, msg in enumerate(messages):
        t = now + i * 1e-3
        source = getattr(msg, "source", None)
        kind = _type(msg)
        usage = getattr(msg, "models_usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        if source == user_source:
            trace.input = trace.input or getattr(msg, "content", None)
            continue
        if kind == "ToolCallRequestEvent":
            for call in getattr(msg, "content", []):
                try:
                    args = json.loads(getattr(call, "arguments", "{}") or "{}")
                except ValueError:
                    args = {"raw": getattr(call, "arguments", None)}
                span = Span(kind=SpanKind.TOOL, name=call.name, agent=source, start_time=t,
                            tool_call=ToolCall(name=call.name, arguments=args), input=args)
                pending[getattr(call, "id", call.name)] = span
                trace.spans.append(span)
            if in_tok or out_tok:
                trace.spans.append(Span(kind=SpanKind.LLM, name="model", agent=source, input_tokens=in_tok,
                                        output_tokens=out_tok, start_time=t, end_time=t))
        elif kind == "ToolCallExecutionEvent":
            for res in getattr(msg, "content", []):
                span = pending.pop(getattr(res, "call_id", None), None)
                if span is not None and span.tool_call is not None:
                    span.end_time = t
                    span.output = span.tool_call.output = _jsonable(getattr(res, "content", None))
                    if getattr(res, "is_error", False):
                        span.error = span.tool_call.error = str(getattr(res, "content", "tool error"))[:500]
        elif kind == "HandoffMessage":
            target = getattr(msg, "target", None)
            trace.spans.append(Span(kind=SpanKind.HANDOFF, name=f"{source}->{target}", agent=source,
                                    handoff_from=source, handoff_to=target, input=getattr(msg, "content", None),
                                    start_time=t, end_time=t))
        else:  # TextMessage, ToolCallSummaryMessage, StopMessage, ...
            trace.spans.append(Span(kind=SpanKind.AGENT, name=kind, agent=source,
                                    output=_jsonable(getattr(msg, "content", None)), input_tokens=in_tok,
                                    output_tokens=out_tok, start_time=t, end_time=t))
            if last_speaker and source and source != last_speaker:
                trace.metadata.setdefault("speaker_transitions", []).append([last_speaker, source])
        if source:
            last_speaker = source
    for s in reversed(trace.spans):
        if s.kind == SpanKind.AGENT and s.output:
            trace.final_output = s.output
            break
    trace.metadata["stop_reason"] = getattr(task_result, "stop_reason", None)
    trace.end_time = now + len(messages) * 1e-3
    return trace
