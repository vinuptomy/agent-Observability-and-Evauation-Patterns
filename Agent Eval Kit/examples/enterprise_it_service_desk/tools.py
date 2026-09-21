"""Simulated enterprise tools (ITSM / IAM / licensing). Deterministic for reproducible evaluation."""
from __future__ import annotations

import zlib

from agentic_eval import Tracer, trace_tool
from agentic_eval.utils.text import tokenize

KNOWLEDGE_BASE = [
    {"id": "KB-101", "title": "Password reset procedure",
     "content": "Password reset: the service desk triggers a password reset link sent to the registered corporate "
                "email after MFA verification. A ticket must be created for tracking."},
    {"id": "KB-205", "title": "Software license requests",
     "content": "Software license requests such as Adobe Acrobat Pro or Microsoft Visio require manager approval. "
                "The service desk checks license availability and creates a procurement ticket."},
    {"id": "KB-310", "title": "VPN outage procedure",
     "content": "VPN outage affecting multiple users: open a high priority incident ticket and escalate to the "
                "network operations team."},
]

LICENSE_POOL = {"adobe acrobat pro": 12, "microsoft visio": 3}


def _ticket_id(summary: str) -> str:
    return f"INC-{zlib.crc32(summary.encode()) % 1_000_000:06d}"


@trace_tool("search_kb")
def search_kb(query: str, top_k: int = 1) -> list[dict]:
    q = set(tokenize(query))
    ranked = sorted(KNOWLEDGE_BASE, key=lambda d: -len(q & set(tokenize(d["title"] + " " + d["content"]))))
    docs = ranked[:top_k]
    tracer = Tracer.current()
    if tracer:
        tracer.record_retrieval(query, [d["content"] for d in docs])
    return docs


@trace_tool("reset_password")
def reset_password(user_id: str) -> dict:
    if user_id.lower() in {"admin", "root", "administrator"}:
        raise PermissionError("privileged accounts cannot be reset by the service desk")
    return {"status": "reset_link_sent", "user_id": user_id}


@trace_tool("check_license")
def check_license(product: str) -> dict:
    return {"product": product, "available_seats": LICENSE_POOL.get(product.lower(), 0)}


@trace_tool("create_ticket")
def create_ticket(summary: str, category: str, priority: str) -> dict:
    return {"ticket_id": _ticket_id(summary), "category": category, "priority": priority, "status": "open"}


@trace_tool("escalate")
def escalate(ticket_id: str, team: str) -> dict:
    return {"ticket_id": ticket_id, "assigned_team": team, "status": "escalated"}
