"""Provider-agnostic LLM client abstraction (OpenAI, Azure OpenAI, Ollama, offline Mock)."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from langfuse_agents.config import Settings
from langfuse_agents.observability.tracing import GENERATION, traced, update_generation

logger = logging.getLogger(__name__)

Message = dict[str, Any]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid4().hex[:12]}")

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: dict[str, int]
    model: str
    finish_reason: str | None = None


class LLMClient(Protocol):
    model: str
    provider: str

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse: ...


class OpenAICompatibleClient:
    """Works for OpenAI, Azure OpenAI and any OpenAI-compatible endpoint (Ollama, vLLM)."""

    def __init__(self, client: Any, model: str, provider: str, temperature: float = 0.0,
                 max_retries: int = 3) -> None:
        self._client = client
        self.model = model
        self.provider = provider
        self.temperature = temperature
        self.max_retries = max_retries

    @traced(name="llm.chat", as_type=GENERATION)
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        import openai

        retriable = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)
        kwargs: dict[str, Any] = {
            "model": self.model, "messages": messages, "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except retriable as exc:
                if attempt == self.max_retries:
                    raise
                backoff = min(2 ** attempt, 20)
                logger.warning("LLM call failed (attempt %s), retrying in %ss: %s",
                               attempt, backoff, type(exc).__name__)
                time.sleep(backoff)

        choice = resp.choices[0]
        tool_calls: list[ToolCall] = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": tc.function.arguments}
            tool_calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))

        usage = {
            "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(resp.usage, "total_tokens", 0) or 0,
        }
        update_generation(
            model=self.model,
            model_parameters={"temperature": self.temperature, "provider": self.provider},
            usage_details={"input": usage["prompt_tokens"], "output": usage["completion_tokens"],
                           "total": usage["total_tokens"]},
        )
        return LLMResponse(choice.message.content, tool_calls, usage, self.model,
                           choice.finish_reason)


class MockLLMClient:
    """Deterministic, offline LLM that emulates native function calling.

    Lets you run the whole solution — tracing, guardrails, evaluation, CI — with no API key.
    """

    provider = "mock"

    def __init__(self, model: str = "mock-llm") -> None:
        self.model = model

    @traced(name="llm.chat", as_type=GENERATION)
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        tool_names = {t["function"]["name"] for t in tools or []}
        last = messages[-1]
        if last["role"] == "tool":
            content, calls = self._final_from_tools(messages), []
        else:
            call = self._route(str(last.get("content", "")), tool_names)
            content, calls = (None, [call]) if call else (
                "Hello! I'm your enterprise assistant. How can I help you today?", [])
        prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        usage = {
            "prompt_tokens": prompt_chars // 4,
            "completion_tokens": len(content or "") // 4 + 10 * len(calls),
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        update_generation(
            model=self.model, model_parameters={"provider": self.provider},
            usage_details={"input": usage["prompt_tokens"], "output": usage["completion_tokens"],
                           "total": usage["total_tokens"]},
        )
        return LLMResponse(content, calls, usage, self.model,
                           "tool_calls" if calls else "stop")

    @staticmethod
    def _route(text: str, tool_names: set[str]) -> ToolCall | None:
        lowered = text.lower()
        ticket = re.search(r"\binc-\d{4,6}\b", lowered)
        if ticket and "get_ticket_status" in tool_names:
            return ToolCall("get_ticket_status", {"ticket_id": ticket.group(0).upper()})
        if "create_ticket" in tool_names and re.search(
            r"\b(open|create|raise|log)\s+(a\s+)?ticket\b", lowered
        ):
            category = "hardware" if re.search(r"laptop|screen|keyboard|monitor", lowered) else "other"
            return ToolCall("create_ticket", {"summary": text[:180], "priority": "medium",
                                              "category": category})
        if lowered.strip() in {"hi", "hello", "hey", "good morning"}:
            return None
        if "search_knowledge_base" in tool_names:
            return ToolCall("search_knowledge_base", {"query": text[:400], "top_k": 2})
        return None

    @staticmethod
    def _final_from_tools(messages: list[Message]) -> str:
        payloads: list[dict] = []
        for msg in reversed(messages):
            if msg["role"] != "tool":
                break
            match = re.search(r"<tool_output[^>]*>\n(.*)\n</tool_output>", msg["content"], re.S)
            try:
                payloads.insert(0, json.loads(match.group(1) if match else msg["content"]))
            except (json.JSONDecodeError, AttributeError):
                continue

        parts: list[str] = []
        for data in payloads:
            if "error" in data:
                parts.append(f"I wasn't able to complete that action: {data['error']}")
            elif "results" in data:
                if not data["results"]:
                    parts.append("I couldn't find a documented answer. "
                                 "Please open a ticket with the Service Desk.")
                else:
                    lines = [f"- **{r['title']}**: {r['content']} [{r['id']}]"
                             for r in data["results"]]
                    parts.append("Here is what I found in the knowledge base:\n" + "\n".join(lines))
            elif data.get("created"):
                parts.append(f"I've created ticket {data['ticket_id']} (priority: "
                             f"{data['priority']}). The Service Desk will contact you shortly.")
            elif "ticket_id" in data:
                parts.append(f"Ticket {data['ticket_id']} is currently {data['status']}. "
                             f"Summary: {data['summary']}. Assigned to: {data['assignee_group']}.")
        return "\n\n".join(parts) or "I couldn't process the tool results."


def build_llm_client(settings: Settings) -> LLMClient:
    """Factory — the only place that knows about concrete providers."""
    if settings.llm_provider == "mock":
        return MockLLMClient()

    import openai

    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for LLM_PROVIDER=openai")
        client = openai.OpenAI(api_key=settings.openai_api_key.get_secret_value(),
                               timeout=settings.llm_timeout_s, max_retries=0)
    elif settings.llm_provider == "azure":
        if not (settings.azure_openai_endpoint and settings.azure_openai_api_key):
            raise ValueError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required")
        client = openai.AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key.get_secret_value(),
            api_version=settings.azure_openai_api_version,
            timeout=settings.llm_timeout_s, max_retries=0,
        )
    elif settings.llm_provider == "ollama":
        client = openai.OpenAI(base_url=settings.ollama_base_url, api_key="ollama",
                               timeout=settings.llm_timeout_s, max_retries=0)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported provider {settings.llm_provider}")

    return OpenAICompatibleClient(client, settings.llm_model, settings.llm_provider,
                                  settings.llm_temperature, settings.llm_max_retries)
