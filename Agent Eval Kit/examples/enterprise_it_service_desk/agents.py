"""Enterprise IT Service Desk — a supervisor-pattern multi-agent system (deterministic simulation).

    supervisor ──► triage_agent ──► knowledge_agent ──► resolution_agent ──► supervisor (final answer)
                        │
                        └── blocked (prompt injection) ──► supervisor

The agent "LLM calls" are simulated so the example runs offline and reproducibly, but the system is
instrumented exactly as a real one would be: ``@trace_agent``, ``@trace_tool``, ``handoff`` and
``Tracer.record_llm``. Replace the rule-based bodies with LangGraph / CrewAI / AutoGen / SDK agents and
the evaluation keeps working unchanged.

``run_service_desk_naive`` is a deliberately vulnerable/inefficient variant used to demonstrate that the
evaluation suite catches regressions (prompt leakage, privileged actions, redundant tool loops).
"""
from __future__ import annotations

import json
import re

from agentic_eval import Tracer, handoff, trace_agent
from agentic_eval.security.injection import detect_injection
from examples.enterprise_it_service_desk import tools
from examples.enterprise_it_service_desk.prompts import SYSTEM_PROMPTS

MODEL = "sim-gpt-4o-mini"
PRICE_PER_1K_IN, PRICE_PER_1K_OUT = 0.00015, 0.0006


def _llm(agent: str, prompt: str, output: object) -> None:
    """Record a simulated model call with token + cost accounting."""
    tracer = Tracer.current()
    if tracer is None:
        return
    text_out = json.dumps(output) if not isinstance(output, str) else output
    tin = (len(SYSTEM_PROMPTS[agent]) + len(prompt)) // 4
    tout = len(text_out) // 4
    tracer.record_llm(prompt=prompt, output=text_out, model=MODEL, agent=agent, input_tokens=tin, output_tokens=tout,
                      cost_usd=tin / 1000 * PRICE_PER_1K_IN + tout / 1000 * PRICE_PER_1K_OUT)


def _extract_user(text: str) -> str:
    m = re.search(r"\bfor user\s+([\w.]+)", text, re.I) or re.search(r"\b([a-z]+\.[a-z]+)\b", text)
    return m.group(1) if m else "unknown"


def _extract_product(text: str) -> str:
    for product in ("Adobe Acrobat Pro", "Microsoft Visio"):
        if product.lower() in text.lower():
            return product
    return "unknown"


# ---------------------------------------------------------------------------------------- agents
@trace_agent("triage_agent")
def triage_agent(request: str, guardrails: bool = True) -> dict:
    tracer = Tracer.current()
    if guardrails:
        findings = detect_injection(request)
        if tracer:
            tracer.record_guardrail("prompt_injection_shield", bool(findings), [f.rule for f in findings])
        if findings:
            result = {"intent": "blocked", "priority": "high", "reason": [f.rule for f in findings]}
            _llm("triage_agent", request, result)
            return result
    text = request.lower()
    if "password" in text or "locked out" in text:
        result = {"intent": "password_reset", "priority": "medium"}
    elif "license" in text or "install" in text:
        result = {"intent": "software_license", "priority": "low"}
    elif any(w in text for w in ("vpn", "outage", "down", "cannot connect")):
        severe = any(w in text for w in ("team", "everyone", "nobody", "multiple", "all users"))
        result = {"intent": "incident", "priority": "high" if severe else "medium"}
    else:
        result = {"intent": "general", "priority": "low"}
    _llm("triage_agent", request, result)
    return result


@trace_agent("knowledge_agent")
def knowledge_agent(request: str, triage: dict, redundant_searches: int = 0) -> list[dict]:
    docs = tools.search_kb(query=request)
    for _ in range(redundant_searches):  # naive variant: repeats identical calls (loop anti-pattern)
        docs = tools.search_kb(query=request)
    _llm("knowledge_agent", request, [d["id"] for d in docs])
    return docs


@trace_agent("resolution_agent")
def resolution_agent(request: str, triage: dict, docs: list[dict]) -> dict:
    intent, priority = triage["intent"], triage["priority"]
    actions: dict = {"intent": intent, "kb": [d["id"] for d in docs]}
    if intent == "password_reset":
        user = _extract_user(request)
        actions["reset"] = tools.reset_password(user_id=user)
        actions["ticket"] = tools.create_ticket(summary=f"Password reset for {user}", category="access",
                                                priority=priority)
        actions["user"] = user
    elif intent == "software_license":
        product = _extract_product(request)
        actions["license"] = tools.check_license(product=product)
        actions["ticket"] = tools.create_ticket(summary=f"License request: {product}", category="procurement",
                                                priority=priority)
    elif intent == "incident":
        ticket = tools.create_ticket(summary="VPN outage affecting multiple users", category="network",
                                     priority=priority)
        actions["ticket"] = ticket
        actions["escalation"] = tools.escalate(ticket_id=ticket["ticket_id"], team="network-operations")
    else:
        actions["ticket"] = tools.create_ticket(summary=request[:60], category="general", priority=priority)
    _llm("resolution_agent", request, actions)
    return actions


@trace_agent("supervisor")
def compose_answer(request: str, triage: dict, actions: dict, leak_prompt: bool = False) -> str:
    intent = triage["intent"]
    ticket = actions.get("ticket", {}).get("ticket_id", "n/a")
    kb = ", ".join(actions.get("kb", [])) or "n/a"
    if intent == "blocked":
        answer = ("Your request could not be processed because it contains instructions that violate our security "
                  f"policy. It has been logged as security ticket {ticket} for review.")
    elif intent == "password_reset":
        answer = (f"A password reset link has been sent to your registered corporate email after MFA verification. "
                  f"Ticket {ticket} was created for tracking. (Source: {kb})")
    elif intent == "software_license":
        lic = actions["license"]
        answer = (f"Your {lic['product']} license request is logged as procurement ticket {ticket}. "
                  f"{lic['available_seats']} seats are available; manager approval is required before assignment. "
                  f"(Source: {kb})")
    elif intent == "incident":
        answer = (f"We opened high priority incident ticket {ticket} for the VPN outage and escalated it to the "
                  f"network operations team. (Source: {kb})")
    else:
        answer = f"Your request is logged as ticket {ticket}; an agent will contact you. (Source: {kb})"
    if leak_prompt and "system prompt" in request.lower():  # naive variant only
        answer += " My instructions are: " + SYSTEM_PROMPTS["supervisor"]
    _llm("supervisor", request, answer)
    return answer


# ---------------------------------------------------------------------------------------- entry points
def _run(request: str, guardrails: bool) -> str:
    handoff("supervisor", "triage_agent", {"request_chars": len(request)})
    triage = triage_agent(request, guardrails=guardrails)
    if triage["intent"] == "blocked":
        handoff("triage_agent", "supervisor", triage)
        actions = {"ticket": tools.create_ticket(summary="Security review: blocked request", category="security",
                                                 priority="high")}
        return compose_answer(request, triage, actions)
    handoff("triage_agent", "knowledge_agent", triage)
    docs = knowledge_agent(request, triage, redundant_searches=0 if guardrails else 2)
    handoff("knowledge_agent", "resolution_agent", {"kb": [d["id"] for d in docs]})
    try:
        actions = resolution_agent(request, triage, docs)
    except PermissionError as exc:  # tool refused -> recover gracefully
        actions = {"ticket": tools.create_ticket(summary=f"Failed action: {exc}", category="security", priority="high"),
                   "kb": [d["id"] for d in docs]}
        triage = {**triage, "intent": "general"}
    handoff("resolution_agent", "supervisor", {"ticket": actions.get("ticket", {}).get("ticket_id")})
    return compose_answer(request, triage, actions, leak_prompt=not guardrails)


def run_service_desk(request: str) -> str:
    """Production-grade version (guardrails on)."""
    return _run(request, guardrails=True)


def run_service_desk_naive(request: str) -> str:
    """Regression demo: no injection shield, leaks prompt, redundant tool loops."""
    return _run(request, guardrails=False)
