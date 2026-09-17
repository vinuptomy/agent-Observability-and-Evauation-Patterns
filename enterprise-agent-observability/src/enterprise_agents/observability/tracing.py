"""Opik observability layer.

Design principles
-----------------
* **Fail-open**: tracing problems never break the business flow.
* **Privacy by default**: span inputs/outputs are serialised and PII-redacted before export.
* **Vendor isolation**: the rest of the code only uses ``traced``/``update_*`` helpers,
  so swapping Opik for OpenTelemetry/Langfuse touches this single module.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar

from enterprise_agents.security.pii import redact_text

logger = logging.getLogger(__name__)

try:  # Opik is optional at runtime (e.g. minimal containers, unit tests).
    import opik
    from opik import opik_context

    OPIK_AVAILABLE = True
except Exception:  # pragma: no cover
    opik = None  # type: ignore[assignment]
    opik_context = None  # type: ignore[assignment]
    OPIK_AVAILABLE = False

F = TypeVar("F", bound=Callable[..., Any])


class _State:
    enabled: bool = False
    redact: bool = True
    project_name: str = "enterprise-agents"


STATE = _State()


def init_observability(settings: Any) -> bool:
    """Configure Opik from settings. Returns True if tracing is active."""
    STATE.redact = settings.redact_pii_in_traces
    STATE.project_name = settings.opik_project_name
    if not settings.opik_enabled:
        os.environ["OPIK_TRACK_DISABLE"] = "true"
        STATE.enabled = False
        logger.info("Opik tracing disabled by configuration")
        return False
    if not OPIK_AVAILABLE:
        logger.warning("opik package not installed; tracing disabled")
        return False

    os.environ.setdefault("OPIK_PROJECT_NAME", settings.opik_project_name)
    kwargs: dict[str, Any] = {"use_local": settings.opik_use_local}
    if settings.opik_url:
        kwargs["url"] = settings.opik_url
    if not settings.opik_use_local:
        if settings.opik_api_key:
            kwargs["api_key"] = settings.opik_api_key.get_secret_value()
        if settings.opik_workspace:
            kwargs["workspace"] = settings.opik_workspace
    try:
        try:
            opik.configure(automatic_approvals=True, **kwargs)
        except TypeError:  # older SDKs
            opik.configure(**kwargs)
        STATE.enabled = True
        logger.info("Opik tracing enabled", extra={"project": settings.opik_project_name})
    except Exception as exc:
        logger.warning("Opik configuration failed, continuing without tracing: %s", exc)
        os.environ["OPIK_TRACK_DISABLE"] = "true"
        STATE.enabled = False
    return STATE.enabled


def to_safe_payload(obj: Any, max_chars: int = 4000) -> str:
    """Serialise any object to a redacted, size-bounded string for trace export."""
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


def _opik_track(name: str, span_type: str, tags: list[str] | None) -> Callable[[F], F]:
    try:
        return opik.track(
            name=name, type=span_type, tags=tags, capture_input=False, capture_output=False
        )
    except TypeError:  # pragma: no cover - older SDK signature
        return opik.track(name=name, type=span_type, tags=tags)


def traced(
    name: str | None = None,
    span_type: str = "general",
    tags: list[str] | None = None,
    capture_io: bool = True,
) -> Callable[[F], F]:
    """Decorator creating an Opik span (type: general | llm | tool) with redacted I/O."""

    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__
        params = list(inspect.signature(fn).parameters)
        skip_first = bool(params) and params[0] in ("self", "cls")

        @functools.wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            result = fn(*args, **kwargs)
            if capture_io:
                call_args = args[1:] if skip_first else args
                update_span(
                    input={"args": to_safe_payload(list(call_args)), "kwargs": to_safe_payload(kwargs)},
                    output={"output": to_safe_payload(result)},
                )
            return result

        tracked = _opik_track(span_name, span_type, tags)(inner) if OPIK_AVAILABLE else inner

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if STATE.enabled:
                return tracked(*args, **kwargs)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def update_span(**kwargs: Any) -> None:
    if not STATE.enabled:
        return
    try:
        opik_context.update_current_span(**kwargs)
    except Exception as exc:  # pragma: no cover
        logger.debug("update_current_span failed: %s", exc)


def update_trace(**kwargs: Any) -> None:
    if not STATE.enabled:
        return
    try:
        opik_context.update_current_trace(**kwargs)
    except TypeError:
        kwargs.pop("thread_id", None)  # older SDKs have no thread support
        try:
            opik_context.update_current_trace(**kwargs)
        except Exception as exc:  # pragma: no cover
            logger.debug("update_current_trace failed: %s", exc)
    except Exception as exc:  # pragma: no cover
        logger.debug("update_current_trace failed: %s", exc)


def log_trace_feedback(name: str, value: float, reason: str | None = None) -> None:
    """Attach an online feedback score (e.g. guardrail pass/fail) to the current trace."""
    update_trace(feedback_scores=[{"name": name, "value": float(value), "reason": reason}])


def current_trace_id() -> str | None:
    if not STATE.enabled:
        return None
    try:
        data = opik_context.get_current_trace_data()
        return getattr(data, "id", None)
    except Exception:
        return None


def flush() -> None:
    if STATE.enabled:
        try:
            opik.flush_tracker()
        except Exception as exc:  # pragma: no cover
            logger.debug("flush failed: %s", exc)
