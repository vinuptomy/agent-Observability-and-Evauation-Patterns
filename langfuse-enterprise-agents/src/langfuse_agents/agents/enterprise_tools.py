"""Enterprise IT tools. In production these adapters call ServiceNow / Jira SM / Azure AI Search."""

from __future__ import annotations

import itertools
import json
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from langfuse_agents.core.retrieval import Document, KeywordRetriever
from langfuse_agents.core.tools import ToolError, ToolRegistry

DATA_PACKAGE = "langfuse_agents.data"


class SearchKnowledgeBaseArgs(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="Natural-language search query")
    top_k: int = Field(3, ge=1, le=5, description="Number of articles to return")


class GetTicketStatusArgs(BaseModel):
    ticket_id: str = Field(..., pattern=r"^INC-\d{4,6}$", description="Ticket id, e.g. INC-1001")


class CreateTicketArgs(BaseModel):
    summary: str = Field(..., min_length=5, max_length=200)
    priority: Literal["low", "medium", "high"] = "medium"
    category: Literal["access", "hardware", "network", "software", "security", "other"] = "other"


def _load_json(filename: str, data_dir: Path | None) -> object:
    if data_dir:
        return json.loads((data_dir / filename).read_text(encoding="utf-8"))
    return json.loads(resources.files(DATA_PACKAGE).joinpath(filename).read_text(encoding="utf-8"))


def build_enterprise_registry(data_dir: Path | None = None) -> ToolRegistry:
    """Build a fresh registry (fresh in-memory ticket store) — safe for tests/evaluation."""
    kb = _load_json("knowledge_base.json", data_dir)
    tickets: dict[str, dict] = dict(_load_json("tickets.json", data_dir))  # type: ignore[arg-type]
    retriever = _retriever_from(kb)
    id_seq = itertools.count(2001)
    registry = ToolRegistry()

    @registry.tool("search_knowledge_base",
                   "Search approved IT, security and HR policy knowledge-base articles.",
                   SearchKnowledgeBaseArgs)
    def search_knowledge_base(args: SearchKnowledgeBaseArgs) -> dict:
        hits = retriever.search(args.query, top_k=args.top_k)
        return {"results": [{"id": d.id, "title": d.title, "content": d.content, "score": s}
                            for d, s in hits]}

    @registry.tool("get_ticket_status", "Get the current status of an existing incident ticket.",
                   GetTicketStatusArgs)
    def get_ticket_status(args: GetTicketStatusArgs) -> dict:
        ticket = tickets.get(args.ticket_id)
        if not ticket:
            raise ToolError(f"ticket {args.ticket_id} not found")
        return ticket

    @registry.tool("create_ticket", "Create a new IT incident ticket. HIGH RISK: requires approval.",
                   CreateTicketArgs, risk="high", requires_approval=True)
    def create_ticket(args: CreateTicketArgs) -> dict:
        ticket_id = f"INC-{next(id_seq)}"
        tickets[ticket_id] = {"ticket_id": ticket_id, "status": "New", "summary": args.summary,
                              "assignee_group": "Service Desk L1", "updated": "now"}
        return {"created": True, "ticket_id": ticket_id, "priority": args.priority,
                "category": args.category, "status": "New"}

    return registry


def _retriever_from(kb: object) -> KeywordRetriever:
    return KeywordRetriever([Document(d["id"], d["title"], d["content"], tuple(d.get("tags", [])))
                             for d in kb])  # type: ignore[union-attr]

