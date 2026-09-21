"""LangChain / LangGraph callback handler.

    handler = AgentEvalCallbackHandler()          # uses the active Tracer if one exists
    graph.invoke(inputs, config={"callbacks": [handler]})
    trace = handler.tracer.trace

LangGraph node executions become AGENT spans (via ``metadata['langgraph_node']``); transitions between
nodes are recorded as HANDOFF spans, so supervisor / swarm topologies are evaluated out of the box.
"""
from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from agentic_eval.collectors.tracer import Tracer, _jsonable
from agentic_eval.core.models import Span, SpanKind, ToolCall

try:
    from langchain_core.callbacks import BaseCallbackHandler
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    BaseCallbackHandler = object  # type: ignore[misc,assignment]
    _AVAILABLE = False


class AgentEvalCallbackHandler(BaseCallbackHandler):  # type: ignore[misc]
    raise_error = False

    def __init__(self, tracer: Tracer | None = None, agent_key: str = "langgraph_node",
                 ignore_nodes: tuple[str, ...] = ("__start__", "__end__")) -> None:
        if not _AVAILABLE:
            raise ImportError("pip install 'agentic-eval-kit[langchain]'")
        super().__init__()
        self.tracer = tracer or Tracer.current() or Tracer()
        self.agent_key = agent_key
        self.ignore_nodes = ignore_nodes
        self._spans: dict[UUID, Span] = {}
        self._last_agent: str | None = None

    # -- helpers --
    def _parent(self, parent_run_id: UUID | None) -> Span | None:
        return self._spans.get(parent_run_id) if parent_run_id else None

    def _agent_for(self, metadata: dict[str, Any] | None, parent_run_id: UUID | None) -> str | None:
        node = (metadata or {}).get(self.agent_key)
        if node and node not in self.ignore_nodes:
            return node
        parent = self._parent(parent_run_id)
        return parent.agent if parent else None

    def _open(self, run_id: UUID, parent_run_id: UUID | None, **fields: Any) -> Span:
        parent = self._parent(parent_run_id)
        span = Span(parent_id=parent.span_id if parent else None, **fields)
        self._spans[run_id] = span
        return self.tracer.add_span(span)

    def _close(self, run_id: UUID, output: Any = None, error: BaseException | None = None) -> Span | None:
        span = self._spans.get(run_id)
        if span is None:
            return None
        span.end_time = time.time()
        if output is not None:
            span.output = _jsonable(output)
        if error is not None:
            span.error = f"{type(error).__name__}: {error}"
        return span

    # -- chains / graph nodes --
    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: UUID,
                       parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None, **kw: Any) -> None:
        node = (metadata or {}).get(self.agent_key)
        name = kw.get("name") or (serialized or {}).get("name", "chain")
        is_node = bool(node) and node not in self.ignore_nodes and name == node
        if is_node:
            if self._last_agent and self._last_agent != node:
                self.tracer.record_handoff(self._last_agent, node)
            self._last_agent = node
        self._open(run_id, parent_run_id, kind=SpanKind.AGENT if is_node else SpanKind.CHAIN, name=name,
                   agent=self._agent_for(metadata, parent_run_id), input=_jsonable(inputs))
        if parent_run_id is None and self.tracer.trace.input is None:
            self.tracer.trace.input = _jsonable(inputs)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kw: Any) -> None:
        self._close(run_id, outputs)
        if parent_run_id is None:
            self.tracer.set_output(_final_text(outputs))

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        self._close(run_id, error=error)

    # -- tools --
    def on_tool_start(self, serialized: dict[str, Any] | None, input_str: str, *, run_id: UUID,
                      parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None,
                      inputs: dict[str, Any] | None = None, **kw: Any) -> None:
        name = kw.get("name") or (serialized or {}).get("name", "tool")
        args = _jsonable(inputs) if inputs else {"input": input_str}
        self._open(run_id, parent_run_id, kind=SpanKind.TOOL, name=name, agent=self._agent_for(metadata, parent_run_id),
                   input=args, tool_call=ToolCall(name=name, arguments=args))

    def on_tool_end(self, output: Any, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, getattr(output, "content", output))
        if span and span.tool_call:
            span.tool_call.output = span.output

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, error=error)
        if span and span.tool_call:
            span.tool_call.error = span.error

    # -- LLMs --
    def on_chat_model_start(self, serialized: dict[str, Any] | None, messages: Any, *, run_id: UUID,
                            parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None,
                            **kw: Any) -> None:
        model = (metadata or {}).get("ls_model_name") or (serialized or {}).get("name", "llm")
        self._open(run_id, parent_run_id, kind=SpanKind.LLM, name=model, model=model,
                   agent=self._agent_for(metadata, parent_run_id), input=_jsonable(messages))

    def on_llm_start(self, serialized: dict[str, Any] | None, prompts: list[str], *, run_id: UUID,
                     parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None, **kw: Any) -> None:
        self.on_chat_model_start(serialized, prompts, run_id=run_id, parent_run_id=parent_run_id, metadata=metadata)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id)
        if span is None:
            return
        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        try:
            msg = response.generations[0][0].message
            span.output = _jsonable(getattr(msg, "content", None))
            um = getattr(msg, "usage_metadata", None) or {}
            usage = usage or {"prompt_tokens": um.get("input_tokens", 0), "completion_tokens": um.get("output_tokens", 0)}
        except (AttributeError, IndexError, TypeError):
            pass
        span.input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        span.output_tokens = int(usage.get("completion_tokens", 0) or 0)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        self._close(run_id, error=error)

    # -- retrievers --
    def on_retriever_start(self, serialized: dict[str, Any] | None, query: str, *, run_id: UUID,
                           parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None,
                           **kw: Any) -> None:
        self._open(run_id, parent_run_id, kind=SpanKind.RETRIEVAL, name="retriever",
                   agent=self._agent_for(metadata, parent_run_id), input=query)

    def on_retriever_end(self, documents: Any, *, run_id: UUID, **kw: Any) -> None:
        self._close(run_id, [getattr(d, "page_content", str(d)) for d in documents])


def _final_text(outputs: Any) -> Any:
    """Extract the last message content from LangGraph state (``{'messages': [...]}``)."""
    if isinstance(outputs, dict) and outputs.get("messages"):
        last = outputs["messages"][-1]
        return getattr(last, "content", last)
    return outputs
