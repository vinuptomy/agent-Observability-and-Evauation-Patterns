"""Shared fixtures: trace builders so metric tests stay small and readable."""
from __future__ import annotations

import asyncio
import time

import pytest

from agentic_eval import EvalCase, Span, SpanKind, ToolCall, Trace


def run(coro):
    return asyncio.run(coro)


def make_trace(tools=(), handoffs=(), agents=(), output="done", errors=(), contexts=()) -> Trace:
    t0 = time.time()
    spans = []
    for i, a in enumerate(agents):
        spans.append(Span(kind=SpanKind.AGENT, name=a, agent=a, start_time=t0 + i, end_time=t0 + i + 0.1,
                          output=f"{a} output"))
    for i, item in enumerate(tools):
        name, args = (item, {}) if isinstance(item, str) else item
        spans.append(Span(kind=SpanKind.TOOL, name=name, agent=agents[0] if agents else None, start_time=t0 + 10 + i,
                          tool_call=ToolCall(name=name, arguments=args,
                                             error="boom" if name in errors else None),
                          error="boom" if name in errors else None))
    for i, (a, b) in enumerate(handoffs):
        spans.append(Span(kind=SpanKind.HANDOFF, name=f"{a}->{b}", agent=a, handoff_from=a, handoff_to=b,
                          start_time=t0 + 20 + i))
    if contexts:
        spans.append(Span(kind=SpanKind.RETRIEVAL, name="retrieval", output=list(contexts)))
    return Trace(spans=spans, final_output=output, start_time=t0, end_time=t0 + 0.5)


@pytest.fixture
def case() -> EvalCase:
    return EvalCase(case_id="c1", input="reset my password")
