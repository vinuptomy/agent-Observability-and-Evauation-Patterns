"""Tool-calling agent (ReAct-style loop over native function calling).

Agentic patterns implemented
----------------------------
* Bounded reasoning loop (max steps) with graceful escalation.
* Least-privilege tool allowlist per agent.
* Human-in-the-loop approval for high-risk tools.
* Untrusted-data delimiting of tool outputs (indirect prompt-injection defence).
* Input/output guardrails, canary-token leak detection, PII minimisation.
* Full OpenInference trace: agent -> guardrail -> llm -> tool -> retriever spans, with
  session/user propagation and guardrail outcomes written back as Phoenix span annotations.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from phoenix_agents.core.llm import LLMClient, ToolCall
from phoenix_agents.core.tools import ToolRegistry
from phoenix_agents.observability import tracing
from phoenix_agents.observability.tracing import AGENT
from phoenix_agents.observability.usage import UsageTracker
from phoenix_agents.security.approval import ApprovalHandler, deny_all
from phoenix_agents.security.guardrails import (
    REFUSAL_MESSAGE,
    InputGuardrail,
    OutputGuardrail,
    wrap_untrusted,
)
from phoenix_agents.security.pii import redact_text

logger = logging.getLogger(__name__)


def _document_ids(tool_content: str) -> list[str]:
    """Extract retrieved knowledge-base ids from a tool result (used by retrieval metrics)."""
    try:
        data = json.loads(tool_content)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(r.get("id")) for r in data.get("results", []) if isinstance(r, dict) and r.get("id")]


@dataclass(frozen=True)
class AgentConfig:
    name: str
    version: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    description: str = ""
    max_steps: int = 6


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    status: str  # ok | error | denied | rejected
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class AgentResult:
    run_id: str
    agent: str
    answer: str
    status: str  # completed | blocked | max_steps | error
    steps: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    guardrail_reasons: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    trace_id: str | None = None
    span_id: str | None = None
    retrieved_ids: list[str] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [tc.name for tc in self.tool_calls]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolCallingAgent:
    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        registry: ToolRegistry,
        input_guard: InputGuardrail,
        output_guard: OutputGuardrail,
        approval_handler: ApprovalHandler = deny_all,
        environment: str = "dev",
        release: str = "0.1.0",
    ) -> None:
        self.config = config
        self.llm = llm
        self.registry = registry
        self.input_guard = input_guard
        self.output_guard = output_guard
        self.approval_handler = approval_handler
        self.environment = environment
        self.release = release

    def run(self, user_input: str, session_id: str | None = None,
            user_id: str | None = None) -> AgentResult:
        """Public entry point: opens the trace-attribute scope, then runs the agent."""
        with tracing.trace_attributes(
            session_id=session_id,
            user_id=user_id,
            tags=[self.config.name, self.environment, self.llm.provider],
            metadata={"agent_version": self.config.version, "model": self.llm.model,
                      "environment": self.environment, "release": self.release},
        ):
            return self._run(user_input)

    @tracing.traced(name="agent.run", kind=AGENT)
    def _run(self, user_input: str) -> AgentResult:
        start = time.perf_counter()
        usage = UsageTracker()
        result = AgentResult(run_id=uuid4().hex, agent=self.config.name, answer="", status="error")
        result.trace_id, result.span_id = tracing.current_ids()

        try:
            guard = self.input_guard.check(user_input)
            if not guard.allowed:
                result.answer, result.status = REFUSAL_MESSAGE, "blocked"
                result.guardrail_reasons = guard.reasons
                self._annotate(result, "input_guardrail_pass", 0.0, "blocked", ";".join(guard.reasons))
                logger.warning("Input blocked", extra={"agent": self.config.name,
                                                       "reasons": guard.reasons})
                return self._finish(result, usage, start)
            self._annotate(result, "input_guardrail_pass", 1.0, "passed")

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": guard.sanitized_text},
            ]
            tools = self.registry.schemas(self.config.allowed_tools)

            for step in range(1, self.config.max_steps + 1):
                result.steps = step
                response = self.llm.chat(messages, tools=tools)
                usage.add(response.usage)

                if not response.tool_calls:
                    out = self.output_guard.check(response.content or "")
                    result.answer = out.sanitized_text
                    result.guardrail_reasons.extend(out.reasons)
                    result.status = "completed" if out.allowed else "blocked"
                    self._annotate(result, "output_guardrail_pass", 1.0 if out.allowed else 0.0,
                                   "passed" if out.allowed else "blocked",
                                   ";".join(out.reasons) or None)
                    return self._finish(result, usage, start)

                messages.append({"role": "assistant", "content": response.content,
                                 "tool_calls": [tc.to_openai() for tc in response.tool_calls]})
                for call in response.tool_calls:
                    content = self._execute_tool(call, result)
                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "content": wrap_untrusted(call.name, content)})

            result.status = "max_steps"
            result.answer = ("I couldn't complete this request automatically. "
                             "It has been flagged for review by the Service Desk.")
            self._annotate(result, "completed_within_step_budget", 0.0, "escalated")
            return self._finish(result, usage, start)

        except Exception as exc:
            logger.exception("Agent run failed", extra={"agent": self.config.name})
            result.status = "error"
            result.answer = "Sorry, something went wrong. Please try again later."
            result.guardrail_reasons.append(f"exception:{type(exc).__name__}")
            return self._finish(result, usage, start)

    def _execute_tool(self, call: ToolCall, result: AgentResult) -> str:
        safe_args = {k: redact_text(str(v)).text if isinstance(v, str) else v
                     for k, v in call.arguments.items()}
        if call.name not in self.config.allowed_tools:
            result.tool_calls.append(ToolCallRecord(call.name, safe_args, "rejected",
                                                    error="tool_not_allowed"))
            return '{"error": "tool not permitted for this agent"}'

        tool = self.registry.get(call.name)
        if tool and tool.requires_approval and not self.approval_handler(call.name, call.arguments):
            result.tool_calls.append(ToolCallRecord(call.name, safe_args, "denied",
                                                    error="approval_denied"))
            return '{"error": "this action requires human approval and was not approved"}'

        execution = self.registry.execute(call.name, call.arguments)
        result.tool_calls.append(ToolCallRecord(call.name, safe_args,
                                                "ok" if execution.ok else "error",
                                                execution.latency_ms, execution.error))
        if execution.ok:
            result.context.append(execution.content)
            result.retrieved_ids.extend(_document_ids(execution.content))
        return execution.content

    def _annotate(self, result: AgentResult, name: str, score: float, label: str | None = None,
                  explanation: str | None = None) -> None:
        """Guardrail outcome -> span attribute + Phoenix annotation (annotator_kind=CODE)."""
        tracing.set_metadata({name: score})
        trace_id, span_id = tracing.current_ids()
        result.trace_id = result.trace_id or trace_id
        result.span_id = result.span_id or span_id
        tracing.annotate_span(result.span_id, name, score=score, label=label,
                              explanation=explanation, annotator_kind="CODE")

    def _finish(self, result: AgentResult, usage: UsageTracker, start: float) -> AgentResult:
        result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
        result.usage = usage.as_dict(self.llm.model)
        tracing.set_metadata({
            "status": result.status, "steps": result.steps, "tools": result.tool_names,
            "retrieved_ids": result.retrieved_ids, "latency_ms": result.latency_ms,
            "agent_version": self.config.version, **result.usage,
        })
        logger.info("Agent run finished", extra={
            "agent": result.agent, "run_id": result.run_id, "status": result.status,
            "steps": result.steps, "latency_ms": result.latency_ms,
            "total_tokens": result.usage.get("total_tokens"),
        })
        return result
