"""Framework-agnostic data model.

Every adapter (LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, OpenTelemetry, ...) converts framework
events into a single :class:`Trace` made of :class:`Span` objects. Metrics only ever see ``Trace`` +
``EvalCase`` — that is what makes the evaluation module pluggable into any agentic framework.
"""
from __future__ import annotations

import json
import statistics
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def new_id(length: int = 16) -> str:
    return uuid.uuid4().hex[:length]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SpanKind(str, Enum):
    AGENT = "agent"          # an agent turn / node execution
    LLM = "llm"              # a model call
    TOOL = "tool"            # a tool / function call
    HANDOFF = "handoff"      # control transfer between agents
    RETRIEVAL = "retrieval"  # RAG retrieval step
    GUARDRAIL = "guardrail"  # input/output guardrail check
    CHAIN = "chain"          # any other orchestration step


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None


class Span(BaseModel):
    model_config = ConfigDict(extra="allow")

    span_id: str = Field(default_factory=new_id)
    parent_id: str | None = None
    kind: SpanKind
    name: str
    agent: str | None = None
    input: Any = None
    output: Any = None
    tool_call: ToolCall | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    model: str | None = None
    start_time: float = Field(default_factory=time.time)
    end_time: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return max(0.0, (self.end_time - self.start_time) * 1000.0)


class Trace(BaseModel):
    """A complete record of one agent-system run."""

    model_config = ConfigDict(extra="allow")

    trace_id: str = Field(default_factory=lambda: new_id(32))
    name: str = "agent-run"
    input: Any = None
    final_output: Any = None
    spans: list[Span] = Field(default_factory=list)
    start_time: float = Field(default_factory=time.time)
    end_time: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ---- query helpers used by metrics -------------------------------------------------
    def spans_of(self, *kinds: SpanKind) -> list[Span]:
        return [s for s in self.spans if s.kind in kinds]

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [s.tool_call for s in self.spans_of(SpanKind.TOOL) if s.tool_call is not None]

    @property
    def tool_names(self) -> list[str]:
        return [tc.name for tc in self.tool_calls]

    @property
    def agent_sequence(self) -> list[str]:
        """Agents in activation order, consecutive duplicates collapsed."""
        seq: list[str] = []
        for s in sorted(self.spans_of(SpanKind.AGENT), key=lambda x: x.start_time):
            if s.agent and (not seq or seq[-1] != s.agent):
                seq.append(s.agent)
        return seq

    @property
    def agents(self) -> list[str]:
        seen: list[str] = []
        for s in self.spans:
            if s.agent and s.agent not in seen:
                seen.append(s.agent)
        return seen

    @property
    def handoffs(self) -> list[tuple[str, str]]:
        return [
            (s.handoff_from or s.agent or "unknown", s.handoff_to)
            for s in self.spans_of(SpanKind.HANDOFF)
            if s.handoff_to
        ]

    @property
    def retrieved_contexts(self) -> list[str]:
        out: list[str] = []
        for s in self.spans_of(SpanKind.RETRIEVAL):
            docs = s.output
            if isinstance(docs, str):
                out.append(docs)
            elif isinstance(docs, (list, tuple)):
                for d in docs:
                    out.append(str(d.get("content", d)) if isinstance(d, dict) else str(d))
        return out

    @property
    def step_count(self) -> int:
        return len(self.spans_of(SpanKind.TOOL, SpanKind.LLM))

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.spans)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        return round(sum(s.cost_usd for s in self.spans), 8)

    @property
    def duration_ms(self) -> float:
        end = self.end_time
        if end is None:
            ends = [s.end_time or s.start_time for s in self.spans]
            end = max(ends) if ends else self.start_time
        return max(0.0, (end - self.start_time) * 1000.0)

    @property
    def errors(self) -> list[Span]:
        return [s for s in self.spans if s.error]

    @property
    def output_text(self) -> str:
        if self.final_output is None:
            return ""
        if isinstance(self.final_output, str):
            return self.final_output
        return json.dumps(self.final_output, default=str, ensure_ascii=False)

    def summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "agents": self.agent_sequence,
            "tools": self.tool_names,
            "handoffs": [list(h) for h in self.handoffs],
            "steps": self.step_count,
            "tokens": self.total_tokens,
            "cost_usd": self.total_cost_usd,
            "latency_ms": round(self.duration_ms, 2),
            "errors": len(self.errors),
        }


TrajectoryMode = Literal["strict", "in_order", "unordered", "superset", "subset"]


class EvalCase(BaseModel):
    """A single evaluation scenario (golden test case). Every expectation field is optional —
    metrics whose required fields are missing are *skipped*, not failed."""

    model_config = ConfigDict(extra="allow")

    case_id: str = Field(default_factory=new_id)
    input: str
    expected_output: str | None = None
    expected_keywords: list[str] = Field(default_factory=list)
    # tools
    expected_tools: list[str] = Field(default_factory=list)
    expected_tool_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    forbidden_tools: list[str] = Field(default_factory=list)
    # trajectory
    expected_trajectory: list[str] = Field(default_factory=list)
    trajectory_mode: TrajectoryMode | None = None
    # multi-agent
    expected_agents: list[str] = Field(default_factory=list)
    expected_handoffs: list[list[str]] = Field(default_factory=list)
    agent_roles: dict[str, str] = Field(default_factory=dict)
    # RAG
    reference_contexts: list[str] = Field(default_factory=list)
    # quality / rubric
    rubric: str | None = None
    # budgets: max_latency_ms, max_cost_usd, max_tokens, max_steps, max_handoffs, optimal_steps
    constraints: dict[str, float] = Field(default_factory=dict)
    # security
    canary: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricResult(BaseModel):
    metric: str
    category: str
    score: float | None = None
    threshold: float = 0.0
    passed: bool = True
    weight: float = 1.0
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False
    error: str | None = None
    duration_ms: float = 0.0


class CaseResult(BaseModel):
    case_id: str
    trace_id: str
    tags: list[str] = Field(default_factory=list)
    results: list[MetricResult] = Field(default_factory=list)
    trace_summary: dict[str, Any] = Field(default_factory=dict)
    trace: Trace | None = Field(default=None, exclude=True)

    @property
    def evaluated(self) -> list[MetricResult]:
        return [r for r in self.results if not r.skipped]

    @property
    def passed(self) -> bool:
        return all(r.passed and r.error is None for r in self.evaluated)

    @property
    def score(self) -> float:
        rs = [r for r in self.evaluated if r.score is not None]
        total_w = sum(r.weight for r in rs)
        if not rs or total_w == 0:
            return 0.0
        return sum((r.score or 0.0) * r.weight for r in rs) / total_w

    def failed_metrics(self) -> list[MetricResult]:
        return [r for r in self.evaluated if not r.passed or r.error]


class EvalReport(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id(12))
    name: str = "eval-run"
    started_at: str = Field(default_factory=utcnow_iso)
    finished_at: str | None = None
    cases: list[CaseResult] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        total = len(self.cases)
        passed = sum(1 for c in self.cases if c.passed)
        metrics: dict[str, dict[str, Any]] = {}
        for case in self.cases:
            for r in case.evaluated:
                m = metrics.setdefault(
                    r.metric, {"category": r.category, "scores": [], "passed": 0, "n": 0, "errors": 0}
                )
                m["n"] += 1
                m["passed"] += int(r.passed and r.error is None)
                m["errors"] += int(r.error is not None)
                if r.score is not None:
                    m["scores"].append(r.score)
        metric_summary: dict[str, dict[str, Any]] = {}
        categories: dict[str, list[float]] = {}
        for name, m in sorted(metrics.items()):
            scores = m.pop("scores")
            mean = statistics.fmean(scores) if scores else 0.0
            metric_summary[name] = {
                **m,
                "mean": round(mean, 4),
                "min": round(min(scores), 4) if scores else None,
                "pass_rate": round(m["passed"] / m["n"], 4) if m["n"] else 0.0,
            }
            categories.setdefault(m["category"], []).append(mean)
        return {
            "run_id": self.run_id,
            "name": self.name,
            "total_cases": total,
            "passed_cases": passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "mean_score": round(statistics.fmean([c.score for c in self.cases]), 4) if total else 0.0,
            "metrics": metric_summary,
            "categories": {k: round(statistics.fmean(v), 4) for k, v in sorted(categories.items())},
        }
