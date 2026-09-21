"""Push evaluation scores to LLM-observability platforms so quality sits next to the traces.

* Langfuse  — ``LangfuseScoreExporter``  (pip install langfuse)
* LangSmith — ``LangSmithFeedbackExporter`` (pip install langsmith)
Both expect the platform's own trace/run id in ``trace.metadata`` (``langfuse_trace_id`` / ``langsmith_run_id``).
"""
from __future__ import annotations

import logging
from typing import Any

from agentic_eval.core.models import EvalReport

logger = logging.getLogger(__name__)


class LangfuseScoreExporter:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            from langfuse import Langfuse  # type: ignore[import-not-found]
            client = Langfuse()  # reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST
        self.client = client

    def export(self, report: EvalReport) -> int:
        n = 0
        for case in report.cases:
            trace_id = case.trace.metadata.get("langfuse_trace_id") if case.trace else None
            if not trace_id:
                continue
            for r in case.evaluated:
                if r.score is None:
                    continue
                creator = getattr(self.client, "create_score", None) or self.client.score
                creator(trace_id=trace_id, name=r.metric, value=r.score, comment=r.reason[:500])
                n += 1
        logger.info("langfuse_scores_exported", extra={"count": n})
        return n


class LangSmithFeedbackExporter:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            from langsmith import Client  # type: ignore[import-not-found]
            client = Client()
        self.client = client

    def export(self, report: EvalReport) -> int:
        n = 0
        for case in report.cases:
            run_id = case.trace.metadata.get("langsmith_run_id") if case.trace else None
            if not run_id:
                continue
            for r in case.evaluated:
                if r.score is not None:
                    self.client.create_feedback(run_id, key=r.metric, score=r.score, comment=r.reason[:500])
                    n += 1
        return n
