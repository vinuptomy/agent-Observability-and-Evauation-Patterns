"""Structured JSON logging so logs can be shipped to ELK / Azure Monitor / Datadog."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from langfuse_agents.security.pii import redact_text

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()).text,
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "urllib3", "langfuse", "opentelemetry"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
