"""REST service exposing agents (FastAPI). Run: uvicorn phoenix_agents.api.app:app"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from phoenix_agents.agents.factory import AGENT_SPECS, build_agent
from phoenix_agents.config import get_settings
from phoenix_agents.core.agent import ToolCallingAgent
from phoenix_agents.logging_config import configure_logging
from phoenix_agents.observability import tracing
from phoenix_agents.security.approval import deny_all

_agents: dict[str, ToolCallingAgent] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    tracing.init_observability(settings)
    for name in AGENT_SPECS:
        # High-risk tools are denied over the API; route approvals through your ITSM workflow.
        _agents[name] = build_agent(name, settings, approval_handler=deny_all)
    yield
    tracing.flush()
    tracing.shutdown()


app = FastAPI(title="Enterprise Agents API", version="0.1.0", lifespan=lifespan)


class InvokeRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = Field(None, max_length=128)
    user_id: str | None = Field(None, max_length=128)


class InvokeResponse(BaseModel):
    run_id: str
    answer: str
    status: str
    steps: int
    tools: list[str]
    usage: dict[str, Any]
    latency_ms: float
    trace_id: str | None
    span_id: str | None = None


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if expected is None:
        return  # auth disabled (dev only) — put the service behind an API gateway / Entra ID
    if not x_api_key or not secrets.compare_digest(x_api_key, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "agents": sorted(AGENT_SPECS), "tracing": tracing.STATE.enabled}


class FeedbackRequest(BaseModel):
    """End-user feedback, written back onto the span as a Phoenix annotation."""

    span_id: str = Field(..., min_length=8, max_length=128)
    name: str = Field("user_feedback", max_length=64)
    value: float = Field(..., ge=0.0, le=1.0)
    comment: str | None = Field(None, max_length=1000)


@app.post("/v1/feedback", status_code=202, dependencies=[Depends(require_api_key)])
def feedback(body: FeedbackRequest) -> dict[str, Any]:
    if tracing.get_client() is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tracing is disabled")
    tracing.annotate_span(body.span_id, body.name, score=body.value, explanation=body.comment,
                          annotator_kind="HUMAN")
    return {"accepted": True, "span_id": body.span_id}


@app.post("/v1/agents/{agent_name}/invoke", response_model=InvokeResponse,
          dependencies=[Depends(require_api_key)])
def invoke(agent_name: str, body: InvokeRequest) -> InvokeResponse:
    agent = _agents.get(agent_name)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown agent '{agent_name}'")
    r = agent.run(body.input, session_id=body.session_id, user_id=body.user_id)
    return InvokeResponse(run_id=r.run_id, answer=r.answer, status=r.status, steps=r.steps,
                          tools=r.tool_names, usage=r.usage, latency_ms=r.latency_ms,
                          trace_id=r.trace_id, span_id=r.span_id)
