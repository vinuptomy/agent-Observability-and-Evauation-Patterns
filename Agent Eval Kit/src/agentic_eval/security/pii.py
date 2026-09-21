"""Regex + checksum based PII / secret detection (no external calls, GDPR-friendly).

Used for (1) redacting data *before* it is sent to an external LLM judge and (2) the ``pii_leakage``
safety metric. For production-grade NER-based detection plug Microsoft Presidio in via a custom
:class:`PIIDetector` subclass — the interface is intentionally tiny.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


def _luhn_ok(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        checksum += d
    return checksum % 10 == 0


def _iban_ok(iban: str) -> bool:
    s = re.sub(r"\s", "", iban).upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


_PATTERNS: dict[str, tuple[re.Pattern[str], object]] = {
    "EMAIL": (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    "IBAN": (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b"), _iban_ok),
    "CREDIT_CARD": (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), _luhn_ok),
    "PHONE": (re.compile(r"(?<![\w-])(?:\+|00)\d{1,3}[\s/-]?(?:\(?\d{1,5}\)?[\s/-]?){2,5}\d{2,}\b"), None),
    "IPV4": (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), None),
    "SECRET": (re.compile(
        r"\b(?:sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}"
        r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"), None),
}


@dataclass(frozen=True)
class PIIFinding:
    type: str
    start: int
    end: int


class PIIDetector:
    def __init__(self, types: Iterable[str] | None = None) -> None:
        self.types = [t for t in (types or _PATTERNS) if t in _PATTERNS]

    def detect(self, text: str) -> list[PIIFinding]:
        text = text or ""
        findings: list[PIIFinding] = []
        for t in self.types:
            pattern, validator = _PATTERNS[t]
            for m in pattern.finditer(text):
                if validator is None or validator(m.group(0)):  # type: ignore[operator]
                    findings.append(PIIFinding(t, m.start(), m.end()))
        # drop overlaps (keep first / longest)
        findings.sort(key=lambda f: (f.start, -(f.end - f.start)))
        result: list[PIIFinding] = []
        for f in findings:
            if not result or f.start >= result[-1].end:
                result.append(f)
        return result


class PIIRedactor:
    """Replaces detected PII with typed placeholders, e.g. ``[REDACTED_EMAIL]``."""

    def __init__(self, detector: PIIDetector | None = None) -> None:
        self.detector = detector or PIIDetector()

    def redact(self, text: str) -> str:
        if not text:
            return text
        out, last = [], 0
        for f in self.detector.detect(text):
            out.append(text[last:f.start])
            out.append(f"[REDACTED_{f.type}]")
            last = f.end
        out.append(text[last:])
        return "".join(out)
