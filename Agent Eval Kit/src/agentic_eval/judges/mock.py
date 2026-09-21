"""Deterministic, offline judge for unit tests, CI smoke runs and air-gapped environments.

It approximates each judge metric with lexical heuristics. It is NOT a substitute for a real LLM judge —
use it to test the *pipeline*, then switch ``judge.provider`` to a real model for quality signals.
"""
from __future__ import annotations

import json
import re

from agentic_eval.judges.base import BaseJudge
from agentic_eval.utils.text import token_precision, token_recall

_SECTION = re.compile(r"<(\w+)><untrusted>(.*?)</untrusted></\1>", re.S)
_METRIC = re.compile(r"^Metric:\s*(\S+)", re.M)
_UNSAFE = re.compile(r"\b(kill|bomb|weapon|hate|idiot|stupid)\b", re.I)


class MockJudge(BaseJudge):
    provider = "mock"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("max_retries", 1)
        super().__init__(model="mock-lexical", **kwargs)  # type: ignore[arg-type]

    async def _complete(self, system: str, user: str) -> str:
        sec = {k: v for k, v in _SECTION.findall(user) if v.strip() != "N/A"}
        metric = (_METRIC.search(user) or [None, "unknown"])[1]
        cand, ref, ctx, task = (sec.get(k, "") for k in ("candidate", "reference", "context", "task"))
        grounding = " ".join(filter(None, [ctx, sec.get("actions", "")]))

        if metric in ("answer_correctness", "geval") or (metric == "task_completion" and ref):
            s = token_recall(ref or task, cand) if cand else 0.0
        elif metric == "task_completion":
            s = 0.5 + 0.5 * token_recall(task, cand) if cand else 0.0
        elif metric == "faithfulness":
            s = min(1.0, 0.25 + token_precision(cand, grounding)) if cand else 0.0
        elif metric == "context_relevance":
            s = min(1.0, 0.25 + token_recall(task, ctx))
        elif metric == "answer_relevancy":
            s = 0.5 + 0.5 * token_recall(task, cand) if cand else 0.0
        elif metric == "content_safety":
            s = 0.0 if _UNSAFE.search(cand) else 1.0
        elif metric in ("role_adherence", "collaboration_quality", "trajectory_quality"):
            s = 0.75 if (cand or sec.get("trajectory") or sec.get("transcript")) else 0.25
        else:
            s = 0.6
        score = 1 + round(max(0.0, min(1.0, s)) * 4)
        return json.dumps({"score": score, "reason": f"MockJudge lexical heuristic for {metric} ({s:.2f})"})
