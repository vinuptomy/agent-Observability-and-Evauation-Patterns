"""Zero-boilerplate instrumentation for custom / in-house agent code.

    @trace_agent("resolution_agent")
    def resolve(ticket): ...

    @trace_tool()
    def create_ticket(summary: str, priority: str): ...

Works for sync and async functions and is a no-op when no :class:`Tracer` is active.
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from agentic_eval.collectors.tracer import Tracer, _jsonable
from agentic_eval.core.models import SpanKind, ToolCall

F = TypeVar("F", bound=Callable[..., Any])


def _bound_args(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
    except (TypeError, ValueError):
        return {"args": list(args), **kwargs}


def trace_agent(name: str) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = Tracer.current()
                if tracer is None:
                    return await fn(*args, **kwargs)
                with tracer.span(SpanKind.AGENT, name, agent=name, input=_bound_args(fn, args, kwargs)) as span:
                    result = await fn(*args, **kwargs)
                    span.output = _jsonable(result)
                    return result
            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = Tracer.current()
            if tracer is None:
                return fn(*args, **kwargs)
            with tracer.span(SpanKind.AGENT, name, agent=name, input=_bound_args(fn, args, kwargs)) as span:
                result = fn(*args, **kwargs)
                span.output = _jsonable(result)
                return result
        return wrapper  # type: ignore[return-value]
    return decorator


def trace_tool(name: str | None = None) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        tool_name = name or fn.__name__

        def _open(tracer: Tracer, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            arguments = _jsonable(_bound_args(fn, args, kwargs))
            cm = tracer.span(SpanKind.TOOL, tool_name, input=arguments)
            span = cm.__enter__()
            span.tool_call = ToolCall(name=tool_name, arguments=arguments)
            return cm, span

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = Tracer.current()
                if tracer is None:
                    return await fn(*args, **kwargs)
                cm, span = _open(tracer, args, kwargs)
                try:
                    result = await fn(*args, **kwargs)
                except BaseException as exc:
                    cm.__exit__(type(exc), exc, exc.__traceback__)
                    raise
                span.output = span.tool_call.output = _jsonable(result)
                cm.__exit__(None, None, None)
                return result
            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = Tracer.current()
            if tracer is None:
                return fn(*args, **kwargs)
            cm, span = _open(tracer, args, kwargs)
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                cm.__exit__(type(exc), exc, exc.__traceback__)
                raise
            span.output = span.tool_call.output = _jsonable(result)
            cm.__exit__(None, None, None)
            return result
        return wrapper  # type: ignore[return-value]
    return decorator


def handoff(from_agent: str, to_agent: str, payload: Any = None) -> None:
    """Record a control transfer between agents (no-op without an active tracer)."""
    tracer = Tracer.current()
    if tracer is not None:
        tracer.record_handoff(from_agent, to_agent, payload)
