"""Judge base class: PII redaction, bounded concurrency, timeouts, retries with exponential backoff and
robust JSON parsing. Providers only implement :meth:`BaseJudge._complete`."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from abc import ABC, abstractmethod
from typing import Any

from agentic_eval.core.exceptions import JudgeError
from agentic_eval.security.pii import PIIRedactor

logger = logging.getLogger(__name__)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json_response(raw: str) -> dict[str, Any]:
    text = _FENCE.sub("", (raw or "").strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise JudgeError(f"judge returned non-JSON output: {text[:120]!r}") from exc
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise JudgeError("judge JSON must be an object")
    return data


class BaseJudge(ABC):
    provider: str = "base"

    def __init__(
        self,
        model: str | None = None,
        redact_pii: bool = True,
        max_retries: int = 3,
        timeout_s: float = 60.0,
        temperature: float = 0.0,
        max_concurrency: int = 8,
    ) -> None:
        self.model = model
        self.redactor = PIIRedactor() if redact_pii else None
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.temperature = temperature
        self._max_concurrency = max_concurrency
        self._sem: asyncio.Semaphore | None = None
        self.calls = 0

    @abstractmethod
    async def _complete(self, system: str, user: str) -> str:
        """Send one chat completion and return the raw text."""

    async def judge(self, system: str, user: str) -> dict[str, Any]:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max_concurrency)
        if self.redactor:
            user = self.redactor.redact(user)  # data minimisation before leaving the trust boundary
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._sem:
                    self.calls += 1
                    raw = await asyncio.wait_for(self._complete(system, user), timeout=self.timeout_s)
                return parse_json_response(raw)
            except Exception as exc:  # network, rate limit, parse errors
                last_exc = exc
                delay = min(8.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.25)
                logger.warning("judge_retry", extra={"provider": self.provider, "attempt": attempt,
                                                     "error": type(exc).__name__})
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
        raise JudgeError(f"{self.provider} judge failed after {self.max_retries} attempts: {last_exc}")
