"""Trace capture primitives (framework-independent)."""
from agentic_eval.collectors.decorators import handoff, trace_agent, trace_tool
from agentic_eval.collectors.tracer import Tracer

__all__ = ["Tracer", "handoff", "trace_agent", "trace_tool"]
