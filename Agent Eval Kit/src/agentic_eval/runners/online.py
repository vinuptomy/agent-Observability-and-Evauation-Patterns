"""Online (production) evaluation: sample live traces and score them asynchronously off the hot path.

    online = OnlineEvaluator(metrics=[create_metric("pii_leakage"), create_metric("loop_detection")],
                             sample_rate=0.1, on_result=alert_if_failed)
    await online.start()
    ...  # in request handler, after the agent finished:
    online.submit(tracer.trace)
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Sequence
from typing import Any

from agentic_eval.core.metric import BaseMetric
from agentic_eval.core.models import CaseResult, EvalCase, Trace
from agentic_eval.judges.base import BaseJudge
from agentic_eval.runners.evaluator import Evaluator

logger = logging.getLogger(__name__)


class OnlineEvaluator:
    def __init__(self, metrics: Sequence[BaseMetric], judge: BaseJudge | None = None, sample_rate: float = 0.1,
                 max_queue: int = 1000, workers: int = 2,
                 on_result: Callable[[CaseResult], Any] | None = None) -> None:
        self._evaluator = Evaluator(metrics, judge=judge, keep_traces=False, name="online")
        self.sample_rate = sample_rate
        self._queue: asyncio.Queue[tuple[Trace, EvalCase]] = asyncio.Queue(maxsize=max_queue)
        self._workers_n = workers
        self._workers: list[asyncio.Task[None]] = []
        self.on_result = on_result
        self.dropped = 0

    async def start(self) -> None:
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self._workers_n)]

    async def stop(self) -> None:
        await self._queue.join()
        for w in self._workers:
            w.cancel()

    def submit(self, trace: Trace, case: EvalCase | None = None) -> bool:
        """Non-blocking; returns False if not sampled or back-pressure dropped it."""
        if random.random() > self.sample_rate:
            return False
        case = case or EvalCase(case_id=f"online-{trace.trace_id[:8]}", input=str(trace.input or ""))
        try:
            self._queue.put_nowait((trace, case))
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False

    async def _worker(self) -> None:
        while True:
            trace, case = await self._queue.get()
            try:
                result = await self._evaluator.aevaluate_trace(trace, case, run_id="online")
                if self.on_result:
                    out = self.on_result(result)
                    if asyncio.iscoroutine(out):
                        await out
            except Exception:  # never let monitoring break production
                logger.exception("online_eval_failed")
            finally:
                self._queue.task_done()
