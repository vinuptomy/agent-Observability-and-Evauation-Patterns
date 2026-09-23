"""Input / output guardrails: prompt-injection screening, PII, canary-token leak detection."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field

from langfuse_agents.observability.tracing import GUARDRAIL, traced
from langfuse_agents.security.pii import redact_text

INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
        r"disregard\s+(all\s+|the\s+|your\s+)?(previous|prior|system|above)",
        r"(reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+(system\s+prompt|instructions|hidden\s+prompt)",
        r"you\s+are\s+now\s+(in\s+)?(developer|dan|jailbreak|unrestricted)",
        r"\bdo\s+anything\s+now\b",
        r"act\s+as\s+(an?\s+)?(unrestricted|unfiltered|jailbroken)",
        r"</?\s*(system|tool_output|assistant)\s*>",
    )
]

REFUSAL_MESSAGE = (
    "I can't help with that request. It appears to conflict with our acceptable-use policy. "
    "If you believe this is a mistake, please contact the Service Desk."
)


@dataclass
class GuardrailResult:
    allowed: bool
    sanitized_text: str
    reasons: list[str] = field(default_factory=list)
    pii_findings: dict[str, int] = field(default_factory=dict)


def make_canary() -> str:
    """A secret marker embedded in the system prompt; seeing it in output = prompt leak."""
    return f"CANARY-{secrets.token_hex(8)}"


def wrap_untrusted(source: str, content: str) -> str:
    """Delimit tool output so the model treats it as data, never as instructions."""
    safe = content.replace("</tool_output>", "&lt;/tool_output&gt;")
    return f'<tool_output source="{source}">\n{safe}\n</tool_output>'


class InputGuardrail:
    def __init__(self, max_chars: int = 4000, redact_pii: bool = True) -> None:
        self.max_chars = max_chars
        self.redact_pii = redact_pii

    @traced(name="guardrail.input", as_type=GUARDRAIL)
    def check(self, text: str) -> GuardrailResult:
        reasons: list[str] = []
        if not text or not text.strip():
            reasons.append("empty_input")
        if text and len(text) > self.max_chars:
            reasons.append(f"input_too_long(>{self.max_chars})")
        for pattern in INJECTION_PATTERNS:
            if text and pattern.search(text):
                reasons.append("prompt_injection_suspected")
                break
        sanitized, findings = text or "", {}
        if self.redact_pii:
            red = redact_text(sanitized)
            sanitized, findings = red.text, red.findings
        return GuardrailResult(not reasons, sanitized, reasons, findings)


class OutputGuardrail:
    def __init__(self, canary_token: str, max_chars: int = 8000, redact_pii: bool = True) -> None:
        self.canary_token = canary_token
        self.max_chars = max_chars
        self.redact_pii = redact_pii

    @traced(name="guardrail.output", as_type=GUARDRAIL)
    def check(self, text: str) -> GuardrailResult:
        reasons: list[str] = []
        text = text or ""
        if self.canary_token and self.canary_token in text:
            return GuardrailResult(False, REFUSAL_MESSAGE, ["system_prompt_leak"])
        if len(text) > self.max_chars:
            text = text[: self.max_chars] + " …[truncated]"
            reasons.append("output_truncated")
        findings: dict[str, int] = {}
        if self.redact_pii:
            red = redact_text(text)
            text, findings = red.text, red.findings
            if findings:
                reasons.append("pii_redacted")
        return GuardrailResult(True, text, reasons, findings)
