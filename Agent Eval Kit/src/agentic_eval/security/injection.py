"""Heuristic prompt-injection / jailbreak detection (indirect and direct).

Heuristics are a *first line* of defence and a useful evaluation signal; combine them with a model-based
classifier (e.g. Azure AI Content Safety Prompt Shields, Llama Guard) in production.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|all|earlier|system)\b.{0,20}"
        r"\b(instructions?|rules|prompts?|guidelines)\b", re.I | re.S)),
    ("role_hijack", re.compile(r"\byou are now\b.{0,40}\b(mode|dan|unrestricted|jailbroken|developer)\b", re.I)),
    ("prompt_exfiltration", re.compile(
        r"\b(reveal|print|show|repeat|output|leak|dump)\b.{0,30}\b(system prompt|hidden instructions|"
        r"initial instructions|your instructions|confidential)\b", re.I)),
    ("no_restrictions", re.compile(r"\b(without|no)\s+(any\s+)?(restrictions|filters|limitations|guardrails)\b", re.I)),
    ("chat_template_tokens", re.compile(r"(<\|im_start\|>|<\|system\|>|\[INST\]|###\s*system\s*:)", re.I)),
    ("tool_coercion", re.compile(r"\b(call|execute|run|invoke)\b.{0,20}\b(tool|function)\b.{0,40}\b(immediately|now|without)\b", re.I)),
    ("secret_request", re.compile(r"\b(api[_ -]?key|password|credentials?|secret)\b.{0,20}\b(of|for)\b.{0,15}\b(admin|root|system)\b", re.I)),  # noqa: E501
]


@dataclass(frozen=True)
class InjectionFinding:
    rule: str
    excerpt: str


def detect_injection(text: str | None) -> list[InjectionFinding]:
    if not text:
        return []
    findings = []
    for name, pattern in _RULES:
        m = pattern.search(text)
        if m:
            findings.append(InjectionFinding(name, m.group(0)[:80]))
    return findings
