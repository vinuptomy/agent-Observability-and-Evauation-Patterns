"""CrewAI adapter using the stable ``step_callback`` / ``task_callback`` hooks.

    adapter = CrewAIAdapter()          # uses the active Tracer if present
    crew = adapter.instrument(crew)
    result = crew.kickoff(inputs={...})
    trace = adapter.finish(result)

Each task becomes an AGENT span for the agent that executed it; moving from one agent's task to the
next agent's task is recorded as a HANDOFF (sequential and hierarchical processes).
"""
from __future__ import annotations

import json
import time
from typing import Any

from agentic_eval.collectors.tracer import Tracer, _jsonable
from agentic_eval.core.models import Span, SpanKind, Trace


def _role(agent: Any) -> str | None:
    return None if agent is None else (getattr(agent, "role", None) or str(agent))


class CrewAIAdapter:
    def __init__(self, tracer: Tracer | None = None) -> None:
        self.tracer = tracer or Tracer.current() or Tracer(name="crewai")
        self._task_agents: list[str | None] = []
        self._task_idx = 0
        self._task_started = time.time()
        self._last_agent: str | None = None

    @property
    def current_agent(self) -> str | None:
        return self._task_agents[self._task_idx] if self._task_idx < len(self._task_agents) else self._last_agent

    def instrument(self, crew: Any) -> Any:
        self._task_agents = [_role(getattr(t, "agent", None)) for t in getattr(crew, "tasks", [])]
        crew.step_callback = self.step_callback
        crew.task_callback = self.task_callback
        return crew

    def step_callback(self, step: Any) -> None:
        agent = self.current_agent
        if agent and agent != self._last_agent:
            if self._last_agent:
                self.tracer.record_handoff(self._last_agent, agent)
            self._last_agent = agent
        steps = step if isinstance(step, list) else [step]
        for s in steps:
            s = s[0] if isinstance(s, tuple) else s
            tool = getattr(s, "tool", None)
            if tool:
                raw = getattr(s, "tool_input", {})
                try:
                    args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                except (ValueError, TypeError):
                    args = {"input": raw}
                self.tracer.record_tool_call(tool, args, output=getattr(s, "result", None), agent=agent)
            thought = getattr(s, "thought", None) or getattr(s, "text", None)
            if thought:
                self.tracer.record_llm(prompt=None, output=thought, agent=agent, model="crewai-llm")

    def task_callback(self, task_output: Any) -> None:
        agent = _role(getattr(task_output, "agent", None)) or self.current_agent
        if agent and self._last_agent and agent != self._last_agent:
            self.tracer.record_handoff(self._last_agent, agent)
        self._last_agent = agent
        self.tracer.add_span(Span(kind=SpanKind.AGENT, name=getattr(task_output, "description", "task")[:80],
                                  agent=agent, output=_jsonable(getattr(task_output, "raw", str(task_output))),
                                  start_time=self._task_started, end_time=time.time()))
        self._task_idx += 1
        self._task_started = time.time()

    def finish(self, crew_output: Any) -> Trace:
        self.tracer.set_output(getattr(crew_output, "raw", str(crew_output)))
        usage = getattr(crew_output, "token_usage", None)
        if usage is not None:
            self.tracer.trace.metadata["token_usage"] = _jsonable(usage)
            self.tracer.add_span(Span(kind=SpanKind.LLM, name="crew_total_usage",
                                      input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                                      output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                                      end_time=time.time()))
        self.tracer.trace.end_time = time.time()
        return self.tracer.trace
