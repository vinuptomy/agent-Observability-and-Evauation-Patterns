"""Shared base for LLM-as-a-judge metrics (G-Eval style rubric scoring on a 1–5 scale)."""
from __future__ import annotations

import json
from typing import Any, ClassVar

from agentic_eval.core.exceptions import ConfigurationError
from agentic_eval.core.metric import BaseMetric, ComputeOutput
from agentic_eval.core.models import EvalCase, Trace
from agentic_eval.judges.prompts import JUDGE_SYSTEM_PROMPT, render


def actions_summary(trace: Trace, limit: int = 20) -> str:
    rows = []
    for tc in trace.tool_calls[:limit]:
        rows.append(f"{tc.name}({json.dumps(tc.arguments, default=str)[:200]}) -> "
                    f"{'ERROR ' + tc.error if tc.error else json.dumps(tc.output, default=str)[:200]}")
    return "\n".join(rows)


class LLMJudgeMetric(BaseMetric):
    uses_judge: ClassVar[bool] = True
    template: ClassVar[str] = ""
    system_prompt: ClassVar[str] = JUDGE_SYSTEM_PROMPT

    def build_inputs(self, trace: Trace, case: EvalCase) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    async def ask_judge(self, **inputs: Any) -> tuple[float, str, dict[str, Any]]:
        if self.judge is None:
            raise ConfigurationError(f"metric '{self.name}' requires a judge")
        data = await self.judge.judge(self.system_prompt, render(self.template, metric_id=self.name, **inputs))
        raw = float(data.get("score", 1))
        raw = max(1.0, min(5.0, raw))
        return (raw - 1) / 4, str(data.get("reason", ""))[:500], {"raw_score": raw, "judge": self.judge.provider,
                                                                   "judge_model": self.judge.model}

    async def compute(self, trace: Trace, case: EvalCase) -> ComputeOutput:
        return await self.ask_judge(**self.build_inputs(trace, case))
