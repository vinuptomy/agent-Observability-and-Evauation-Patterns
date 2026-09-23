"""Langfuse observability layer (Langfuse Python SDK v3/v4, OpenTelemetry-based).

Langfuse-specific patterns demonstrated here
--------------------------------------------
* **Semantic observation types** — ``@observe(as_type=...)`` marks spans as ``agent``,
  ``tool``, ``guardrail``, ``retriever`` or ``generation``, so the Langfuse UI renders an
  agent-graph view instead of a flat span list.
* **SDK-level masking** — a ``mask`` callback runs on every payload before export, so PII
  never leaves the process even if an instrumented library captures raw data.
* **Trace-level attribute propagation** — ``propagate_attributes`` attaches session, user,
  tags, release and metadata to the whole trace.
* **Environment & release tagging** — first-class ``environment``/``release`` on the client
  keeps dev, staging and prod traces separate in one project.
* **Head sampling** — ``sample_rate`` keeps high-volume production cost predictable.
* **Deep links** — ``get_trace_url()`` is returned by the API so support staff can jump
  straight from a ticket to the trace.

Design principles (same as the other patterns in this repository)
----------------------------------------------------------------
* **Fail-open**: observability problems never break the business flow.
* **Privacy by default**: payloads are serialised and redacted before export.
* **Vendor isolation**: the rest of the code only uses the helpers below, so swapping
  Langfuse for another backend touches this single module.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar

from langfuse_agents.security.pii import redact_text

logger = logging.getLogger(__name__)

try:  # Langfuse is optional at runtime (minimal containers, offline unit tests).
    from langfuse import Langfuse, observe, propagate_attributes

    LANGFUSE_AVAILABLE = True
except Exception:  # pragma: no cover
    Langfuse = None  # type: ignore[assignment]
    observe = None  # type: ignore[assignment]
    propagate_attributes = None  # type: ignore[assignment]
    LANGFUSE_AVAILABLE = False

F = TypeVar("F", bound=Callable[..., Any])

# Langfuse observation types -> how they render in the UI.
AGENT = "agent"
TOOL = "tool"
GUARDRAIL = "guardrail"
GENERATION = "generation"
SPAN = "span"


class _State:
    enabled: bool = False
    redact: bool = True
    client: Any = None


STATE = _State()


def mask_payload(*, data: Any, **_: Any) -> Any:
    """Langfuse ``mask`` callback: last line of defence before anything leaves the process."""
    try:
        if isinstance(data, str):
            return redact_text(data).text
        if isinstance(data, dict):
            return {k: mask_payload(data=v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [mask_payload(data=v) for v in data]
        return data
    except Exception:  # pragma: no cover - masking must never raise
        return "[MASKING_ERROR]"


def init_observability(settings: Any) -> bool:
    """Configure the Langfuse client from settings. Returns True if tracing is active."""
    STATE.redact = settings.redact_pii_in_traces
    if not settings.langfuse_enabled:
        STATE.enabled = False
        logger.info("Langfuse tracing disabled by configuration")
        return False
    if not LANGFUSE_AVAILABLE:
        logger.warning("langfuse package not installed; tracing disabled")
        return False
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY missing; tracing disabled")
        return False

    try:
        STATE.client = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
            environment=settings.app_env,          # dev / staging / prod separation
            release=settings.release,              # attribute regressions to a deployment
            sample_rate=settings.langfuse_sample_rate,
            mask=mask_payload if settings.redact_pii_in_traces else None,
            flush_at=settings.langfuse_flush_at,
            tracing_enabled=True,
        )
        if settings.langfuse_auth_check and not STATE.client.auth_check():
            logger.warning("Langfuse credentials rejected; continuing without tracing")
            STATE.client, STATE.enabled = None, False
            return False
        STATE.enabled = True
        logger.info("Langfuse tracing enabled", extra={"host": settings.langfuse_host,
                                                       "environment": settings.app_env})
    except Exception as exc:
        logger.warning("Langfuse initialisation failed, continuing without tracing: %s", exc)
        STATE.client, STATE.enabled = None, False
    return STATE.enabled


def to_safe_payload(obj: Any, max_chars: int = 4000) -> str:
    """Serialise any object to a redacted, size-bounded string for export."""
    try:
        if is_dataclass(obj) and not isinstance(obj, type):
            obj = asdict(obj)
        elif hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        text = json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        text = repr(obj)
    if STATE.redact:
        text = redact_text(text).text
    if len(text) > max_chars:
        text = text[:max_chars] + "…[truncated]"
    return text


def traced(name: str | None = None, as_type: str = SPAN, capture_io: bool = True
           ) -> Callable[[F], F]:
    """Decorator creating a Langfuse observation of the given semantic type.

    I/O is captured manually (``capture_input/output=False``) so payloads are serialised and
    redacted by us; the SDK ``mask`` callback then applies as a second layer.
    """

    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__
        params = list(inspect.signature(fn).parameters)
        skip_first = bool(params) and params[0] in ("self", "cls")

        @functools.wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            result = fn(*args, **kwargs)
            if capture_io:
                call_args = args[1:] if skip_first else args
                update_span(input={"args": to_safe_payload(list(call_args)),
                                   "kwargs": to_safe_payload(kwargs)},
                            output={"output": to_safe_payload(result)})
            return result

        observed = (observe(name=span_name, as_type=as_type, capture_input=False,
                            capture_output=False)(inner) if LANGFUSE_AVAILABLE else inner)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if STATE.enabled:
                return observed(*args, **kwargs)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


@contextmanager
def trace_attributes(session_id: str | None = None, user_id: str | None = None,
                     tags: list[str] | None = None, metadata: dict[str, Any] | None = None,
                     trace_name: str | None = None, version: str | None = None) -> Iterator[None]:
    """Attach trace-level attributes to everything executed inside the block."""
    if not STATE.enabled:
        yield
        return
    try:
        with propagate_attributes(session_id=session_id, user_id=user_id, tags=tags,
                                  metadata=metadata, trace_name=trace_name, version=version):
            yield
    except Exception as exc:  # pragma: no cover
        logger.debug("propagate_attributes failed: %s", exc)
        yield


def update_span(**kwargs: Any) -> None:
    if not STATE.enabled or STATE.client is None:
        return
    try:
        STATE.client.update_current_span(**kwargs)
    except Exception as exc:  # pragma: no cover
        logger.debug("update_current_span failed: %s", exc)


def update_generation(**kwargs: Any) -> None:
    """Record model, token usage and cost on the current ``generation`` observation."""
    if not STATE.enabled or STATE.client is None:
        return
    try:
        STATE.client.update_current_generation(**kwargs)
    except Exception as exc:  # pragma: no cover
        logger.debug("update_current_generation failed: %s", exc)


def score_trace(name: str, value: float | str, comment: str | None = None,
                data_type: str | None = None) -> None:
    """Online feedback score on the current trace (guardrails, user thumbs, judges)."""
    if not STATE.enabled or STATE.client is None:
        return
    try:
        kwargs: dict[str, Any] = {"name": name, "value": value, "comment": comment}
        if data_type:
            kwargs["data_type"] = data_type
        STATE.client.score_current_trace(**kwargs)
    except Exception as exc:  # pragma: no cover
        logger.debug("score_current_trace failed: %s", exc)


def current_trace_id() -> str | None:
    if not STATE.enabled or STATE.client is None:
        return None
    try:
        return STATE.client.get_current_trace_id()
    except Exception:
        return None


def trace_url(trace_id: str | None = None) -> str | None:
    """Deep link to the trace — return it to support staff, logs or ticket systems."""
    if not STATE.enabled or STATE.client is None:
        return None
    try:
        return STATE.client.get_trace_url(trace_id=trace_id) if trace_id else STATE.client.get_trace_url()
    except Exception:
        return None


def get_client() -> Any:
    return STATE.client


def flush() -> None:
    if STATE.enabled and STATE.client is not None:
        try:
            STATE.client.flush()
        except Exception as exc:  # pragma: no cover
            logger.debug("flush failed: %s", exc)


def shutdown() -> None:
    if STATE.client is not None:
        try:
            STATE.client.shutdown()
        except Exception as exc:  # pragma: no cover
            logger.debug("shutdown failed: %s", exc)
