"""REST service exposing agents (FastAPI). Run: uvicorn enterprise_agents.api.app:app"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from enterprise_agents.agents.factory import AGENT_SPECS, build_agent
from enterprise_agents.config import get_settings
from enterprise_agents.core.agent import ToolCallingAgent
from enterprise_agents.logging_config import configure_logging
from enterprise_agents.observability import tracing
from enterprise_agents.security.approval import deny_all

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


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if expected is None:
        return  # auth disabled (dev only) — put the service behind an API gateway / Entra ID
    if not x_api_key or not secrets.compare_digest(x_api_key, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "agents": sorted(AGENT_SPECS), "tracing": tracing.STATE.enabled}


@app.post("/v1/agents/{agent_name}/invoke", response_model=InvokeResponse,
          dependencies=[Depends(require_api_key)])
def invoke(agent_name: str, body: InvokeRequest) -> InvokeResponse:
    agent = _agents.get(agent_name)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown agent '{agent_name}'")
    r = agent.run(body.input, session_id=body.session_id, user_id=body.user_id)
    return InvokeResponse(run_id=r.run_id, answer=r.answer, status=r.status, steps=r.steps,
                          tools=r.tool_names, usage=r.usage, latency_ms=r.latency_ms,
                          trace_id=r.trace_id)
