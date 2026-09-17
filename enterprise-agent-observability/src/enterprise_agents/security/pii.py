"""PII detection and redaction (data minimisation for prompts, logs and traces).

Regex-based detection is a fast first line of defence. For production, consider
layering Microsoft Presidio or Azure AI Language PII detection on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Order matters: more specific patterns first.
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){12,15}\d\b"),
    "PHONE": re.compile(r"(?<!\w)\+\d{1,3}[\s-]?\(?\d{1,4}\)?(?:[\s-]?\d{2,4}){2,4}(?!\w)"),
}


@dataclass
class RedactionResult:
    text: str
    findings: dict[str, int] = field(default_factory=dict)

    @property
    def has_pii(self) -> bool:
        return bool(self.findings)


def redact_text(text: str) -> RedactionResult:
    """Replace detected PII with typed placeholders such as ``[REDACTED_EMAIL]``."""
    if not text:
        return RedactionResult(text=text or "")
    findings: dict[str, int] = {}
    for label, pattern in PII_PATTERNS.items():
        text, count = pattern.subn(f"[REDACTED_{label}]", text)
        if count:
            findings[label] = count
    return RedactionResult(text=text, findings=findings)


def contains_pii(text: str) -> bool:
    return any(p.search(text or "") for p in PII_PATTERNS.values())
