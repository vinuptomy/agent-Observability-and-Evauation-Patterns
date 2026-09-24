"""Typed tool registry: schema generation, argument validation, risk metadata, tracing."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from phoenix_agents.observability.tracing import TOOL, set_metadata, set_tool_attributes, traced

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "medium", "high"]


class ToolError(Exception):
    """Expected, user-safe tool failure (message may be shown to the model)."""


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[Any], dict]
    risk: RiskLevel = "low"
    requires_approval: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


@dataclass
class ToolExecution:
    ok: bool
    content: str
    error: str | None = None
    latency_ms: float = 0.0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, args_model: type[BaseModel],
             risk: RiskLevel = "low", requires_approval: bool = False) -> Callable:
        """Decorator form: ``@registry.tool("name", "desc", ArgsModel)``."""
        def decorator(func: Callable[[Any], dict]) -> Callable[[Any], dict]:
            self.register(Tool(name, description, args_model, func, risk, requires_approval))
            return func
        return decorator

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, allowed: Iterable[str]) -> list[dict[str, Any]]:
        return [self._tools[n].schema() for n in allowed if n in self._tools]

    @traced(name="tool.execute", kind=TOOL)
    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecution:
        start = time.perf_counter()
        tool = self._tools.get(name)
        if tool is None:
            return ToolExecution(False, json.dumps({"error": f"unknown tool '{name}'"}), "unknown_tool")
        set_tool_attributes(name=tool.name, description=tool.description, parameters=arguments)
        set_metadata({"risk": tool.risk, "requires_approval": tool.requires_approval})
        try:
            args = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            details = [{"field": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]
            return ToolExecution(False, json.dumps({"error": "invalid arguments", "details": details}),
                                 "validation_error", _ms(start))
        try:
            data = tool.func(args)
            return ToolExecution(True, json.dumps(data, ensure_ascii=False), None, _ms(start))
        except ToolError as exc:
            return ToolExecution(False, json.dumps({"error": str(exc)}), "tool_error", _ms(start))
        except Exception:
            # Never leak stack traces / internals to the model or the user.
            logger.exception("Unhandled tool failure", extra={"tool": name})
            return ToolExecution(False, json.dumps({"error": "internal tool failure"}),
                                 "internal_error", _ms(start))


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
