"""Token usage, latency and cost accounting (FinOps for LLM workloads)."""

from __future__ import annotations

from dataclasses import dataclass

# USD per 1M tokens (input, output). Illustrative — maintain from your contract/price sheet.
PRICES_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "mock-llm": (0.0, 0.0),
}


@dataclass
class UsageTracker:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0

    def add(self, usage: dict | None) -> None:
        usage = usage or {}
        self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self.llm_calls += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def estimated_cost_usd(self, model: str) -> float:
        price_in, price_out = PRICES_PER_1M_TOKENS.get(model, (0.0, 0.0))
        return round(
            (self.prompt_tokens * price_in + self.completion_tokens * price_out) / 1_000_000, 6
        )

    def as_dict(self, model: str) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
            "estimated_cost_usd": self.estimated_cost_usd(model),
        }
