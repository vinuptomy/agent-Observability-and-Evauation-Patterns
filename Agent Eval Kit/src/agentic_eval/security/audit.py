"""Append-only, hash-chained (tamper-evident) JSONL audit log.

Each record stores the SHA-256 of the previous record, so any edit/deletion breaks the chain and is
detected by :meth:`AuditLogger.verify`. Supports governance needs (ISO 42001, EU AI Act record keeping).
Never log raw prompts/outputs here — only identifiers, hashes and outcomes.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from agentic_eval.core.models import utcnow_iso

_GENESIS = "0" * 64


def _hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuditLogger:
    def __init__(self, path: str | Path, actor: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.actor = actor or _safe_user()
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return _GENESIS
        last = _GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line).get("hash", last)
        return last

    def log(self, event: str, **data: Any) -> dict[str, Any]:
        with self._lock:
            record = {"ts": utcnow_iso(), "actor": self.actor, "event": event, "data": data,
                      "prev_hash": self._prev}
            record["hash"] = _hash(record)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
            self._prev = record["hash"]
            return record

    @staticmethod
    def verify(path: str | Path) -> tuple[bool, int | None]:
        """Return ``(True, None)`` if intact, else ``(False, first_bad_line_number)``."""
        prev = _GENESIS
        with Path(path).open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                claimed = rec.pop("hash", None)
                if rec.get("prev_hash") != prev or _hash(rec) != claimed:
                    return False, lineno
                prev = claimed
        return True, None


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - containers without passwd entry
        return "unknown"
