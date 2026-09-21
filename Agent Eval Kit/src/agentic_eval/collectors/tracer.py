"""``Tracer`` — records agent, LLM, tool, handoff and retrieval spans into a :class:`Trace`.

It uses ``contextvars`` so it is safe with asyncio concurrency and ``asyncio.to_thread``; code deep inside
your agents can call ``Tracer.current()`` without passing the tracer around. When no tracer is active,
all instrumentation becomes a no-op, so instrumented code runs unchanged in production.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from agentic_eval.core.models import Span, SpanKind, ToolCall, Trace

_current_tracer: ContextVar[Tracer | None] = ContextVar("agentic_eval_tracer", default=None)
_current_span: ContextVar[Span | None] = ContextVar("agentic_eval_span", default=None)


def _jsonable(value: Any, limit: int = 4000) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…[truncated]"
    if isinstance(value, dict):
        return {str(k): _jsonable(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v, limit) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(), limit)
    return _jsonable(repr(value), limit)


class Tracer:
    def __init__(self, name: str = "agent-run", input: Any = None, metadata: dict[str, Any] | None = None) -> None:
        self.trace = Trace(name=name, input=_jsonable(input), metadata=metadata or {})
        self._token: Token[Tracer | None] | None = None

    # ---- activation -----------------------------------------------------------------
    @staticmethod
    def current() -> Tracer | None:
        return _current_tracer.get()

    def __enter__(self) -> Tracer:
        self.trace.start_time = time.time()
        self._token = _current_tracer.set(self)
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        self.trace.end_time = time.time()
        if exc is not None and self.trace.error is None:
            self.trace.error = f"{type(exc).__name__}: {exc}"
        if self._token is not None:
            _current_tracer.reset(self._token)
            self._token = None

    async def __aenter__(self) -> Tracer:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        self.__exit__(exc_type, exc, tb)

    # ---- recording API --------------------------------------------------------------
    @property
    def current_agent(self) -> str | None:
        span = _current_span.get()
        return span.agent if span else None

    @contextmanager
    def span(self, kind: SpanKind | str, name: str, agent: str | None = None, input: Any = None,
             **fields: Any) -> Iterator[Span]:
        parent = _current_span.get()
        span = Span(kind=SpanKind(kind), name=name, agent=agent or (parent.agent if parent else None),
                    input=_jsonable(input), parent_id=parent.span_id if parent else None, **fields)
        self.trace.spans.append(span)
        token = _current_span.set(span)
        try:
            yield span
        except Exception as exc:
            span.error = f"{type(exc).__name__}: {exc}"
            if span.tool_call is not None:
                span.tool_call.error = span.error
            raise
        finally:
            span.end_time = time.time()
            _current_span.reset(token)

    def add_span(self, span: Span) -> Span:
        """Append a pre-built span (used by framework adapters)."""
        self.trace.spans.append(span)
        return span

    def record_tool_call(self, name: str, arguments: dict[str, Any] | None = None, output: Any = None,
                         error: str | None = None, agent: str | None = None, duration_ms: float = 0.0) -> Span:
        now = time.time()
        parent = _current_span.get()
        return self.add_span(Span(
            kind=SpanKind.TOOL, name=name, agent=agent or self.current_agent,
            parent_id=parent.span_id if parent else None,
            tool_call=ToolCall(name=name, arguments=_jsonable(arguments or {}), output=_jsonable(output), error=error),
            input=_jsonable(arguments), output=_jsonable(output), error=error,
            start_time=now - duration_ms / 1000, end_time=now))

    def record_handoff(self, from_agent: str, to_agent: str, payload: Any = None) -> Span:
        now = time.time()
        return self.add_span(Span(kind=SpanKind.HANDOFF, name=f"{from_agent}->{to_agent}", agent=from_agent,
                                  handoff_from=from_agent, handoff_to=to_agent, input=_jsonable(payload),
                                  start_time=now, end_time=now))

    def record_llm(self, prompt: Any, output: Any, model: str | None = None, agent: str | None = None,
                   input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0,
                   duration_ms: float = 0.0) -> Span:
        now = time.time()
        parent = _current_span.get()
        return self.add_span(Span(kind=SpanKind.LLM, name=model or "llm", model=model,
                                  agent=agent or self.current_agent, parent_id=parent.span_id if parent else None,
                                  input=_jsonable(prompt), output=_jsonable(output), input_tokens=input_tokens,
                                  output_tokens=output_tokens, cost_usd=cost_usd,
                                  start_time=now - duration_ms / 1000, end_time=now))

    def record_retrieval(self, query: str, documents: list[Any], agent: str | None = None) -> Span:
        now = time.time()
        return self.add_span(Span(kind=SpanKind.RETRIEVAL, name="retrieval", agent=agent or self.current_agent,
                                  input=query, output=_jsonable(documents), start_time=now, end_time=now))

    def record_guardrail(self, name: str, triggered: bool, details: Any = None, agent: str | None = None) -> Span:
        now = time.time()
        return self.add_span(Span(kind=SpanKind.GUARDRAIL, name=name, agent=agent or self.current_agent,
                                  output={"triggered": triggered, "details": _jsonable(details)},
                                  start_time=now, end_time=now))

    def set_output(self, output: Any) -> None:
        self.trace.final_output = _jsonable(output, limit=20_000)
