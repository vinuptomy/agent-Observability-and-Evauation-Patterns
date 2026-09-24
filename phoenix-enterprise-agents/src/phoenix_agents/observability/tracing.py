"""Arize Phoenix observability built on OpenTelemetry + OpenInference semantic conventions.

Why this matters
----------------
Instrumentation here is **vendor-neutral**: spans follow the OpenInference conventions and are
exported over OTLP. Phoenix is the default backend, but the same spans can be sent to Arize AX,
a Grafana/Tempo stack, Datadog or any OTLP collector by changing one endpoint — no code changes.

Phoenix / OpenInference patterns demonstrated
--------------------------------------------
* **Semantic span kinds** — ``agent``, ``chain``, ``llm``, ``tool``, ``retriever``, ``guardrail``.
  Phoenix uses these to render agent trajectories and to enable its RAG views and evaluators.
* **Retriever spans with documents** — retrieved chunks (id, content, score) are recorded as
  document attributes, which is what makes retrieval evaluation and RAG debugging possible.
* **LLM spans with token counts** — prompt/completion/total tokens plus model and provider, so
  Phoenix can compute cost and latency breakdowns.
* **Context propagation** — ``using_attributes`` attaches session id, user id, tags and metadata
  to every span produced inside the block.
* **Span annotations** — guardrail outcomes and end-user feedback are written back onto spans via
  the Phoenix client (``annotator_kind`` CODE / HUMAN / LLM).

Design principles (shared by every pattern folder in this repository)
---------------------------------------------------------------------
* **Fail-open**: tracing problems never break the business flow.
* **Privacy by default**: payloads are serialised and PII-redacted before they reach an exporter.
* **Vendor isolation**: the rest of the code only uses the helpers below.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar

from phoenix_agents.security.pii import redact_text

logger = logging.getLogger(__name__)

try:
    from openinference.instrumentation import (
        Document,
        TokenCount,
        get_llm_attributes,
        get_retriever_attributes,
        using_attributes,
    )
    from openinference.semconv.trace import SpanAttributes
    from opentelemetry import trace as otel_trace
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover
    OTEL_AVAILABLE = False

try:
    from phoenix.otel import register

    PHOENIX_OTEL_AVAILABLE = True
except Exception:  # pragma: no cover
    PHOENIX_OTEL_AVAILABLE = False

F = TypeVar("F", bound=Callable[..., Any])

# OpenInference span kinds used across the solution.
AGENT = "agent"
CHAIN = "chain"
LLM = "llm"
TOOL = "tool"
RETRIEVER = "retriever"
GUARDRAIL = "guardrail"


class _State:
    enabled: bool = False
    redact: bool = True
    tracer: Any = None
    provider: Any = None
    client: Any = None          # phoenix.client.Client, for annotations/datasets/experiments
    annotations_enabled: bool = True


STATE = _State()


def init_observability(settings: Any) -> bool:
    """Register the OTLP tracer provider and the Phoenix client. Returns True if active."""
    STATE.redact = settings.redact_pii_in_traces
    if not settings.phoenix_enabled:
        STATE.enabled = False
        logger.info("Phoenix tracing disabled by configuration")
        return False
    if not (OTEL_AVAILABLE and PHOENIX_OTEL_AVAILABLE):
        logger.warning("arize-phoenix-otel / openinference packages missing; tracing disabled")
        return False

    headers = {}
    if settings.phoenix_api_key:
        headers["api_key"] = settings.phoenix_api_key.get_secret_value()
    try:
        STATE.provider = register(
            project_name=settings.phoenix_project_name,
            endpoint=settings.phoenix_collector_endpoint,
            headers=headers or None,
            protocol=settings.phoenix_protocol,
            batch=True,                       # batching exporter: production default
            auto_instrument=settings.phoenix_auto_instrument,
            set_global_tracer_provider=True,
            verbose=False,
        )
        STATE.tracer = STATE.provider.get_tracer("phoenix_agents")
        STATE.enabled = True
        logger.info("Phoenix tracing enabled",
                    extra={"endpoint": settings.phoenix_collector_endpoint,
                           "project": settings.phoenix_project_name})
    except Exception as exc:
        logger.warning("Phoenix/OTel initialisation failed, continuing without tracing: %s", exc)
        STATE.enabled, STATE.tracer, STATE.provider = False, None, None
        return False

    STATE.client = _build_client(settings)
    STATE.annotations_enabled = settings.phoenix_annotate_guardrails
    return STATE.enabled


def _build_client(settings: Any) -> Any:
    """Phoenix REST client, used for annotations, datasets and experiments (optional)."""
    try:
        from phoenix.client import Client

        return Client(
            base_url=settings.phoenix_base_url,
            api_key=settings.phoenix_api_key.get_secret_value() if settings.phoenix_api_key else None,
        )
    except Exception as exc:
        logger.info("Phoenix REST client unavailable (annotations/experiments disabled): %s", exc)
        return None


def get_client() -> Any:
    return STATE.client


# --------------------------------------------------------------------------------------------
# Payload handling
# --------------------------------------------------------------------------------------------
def to_safe_payload(obj: Any, max_chars: int = 4000) -> str:
    """Serialise any object to a redacted, size-bounded string before it reaches an exporter."""
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


# --------------------------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------------------------
def traced(name: str | None = None, kind: str = CHAIN, capture_io: bool = True
           ) -> Callable[[F], F]:
    """Decorator creating an OpenInference span of the given kind."""

    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__
        params = list(inspect.signature(fn).parameters)
        skip_first = bool(params) and params[0] in ("self", "cls")

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not STATE.enabled or STATE.tracer is None:
                return fn(*args, **kwargs)
            with STATE.tracer.start_as_current_span(span_name, openinference_span_kind=kind) as span:
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                if capture_io:
                    call_args = args[1:] if skip_first else args
                    payload = {"args": list(call_args), "kwargs": kwargs} if kwargs else list(call_args)
                    _safe_set(span, SpanAttributes.INPUT_VALUE, to_safe_payload(payload))
                    _safe_set(span, SpanAttributes.INPUT_MIME_TYPE, "application/json")
                    _safe_set(span, SpanAttributes.OUTPUT_VALUE, to_safe_payload(result))
                    _safe_set(span, SpanAttributes.OUTPUT_MIME_TYPE, "application/json")
                span.set_status(Status(StatusCode.OK))
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _safe_set(span: Any, key: str, value: Any) -> None:
    try:
        span.set_attribute(key, value)
    except Exception as exc:  # pragma: no cover
        logger.debug("set_attribute failed for %s: %s", key, exc)


def _current_span() -> Any:
    if not STATE.enabled or not OTEL_AVAILABLE:
        return None
    span = otel_trace.get_current_span()
    return span if span and span.get_span_context().is_valid else None


def set_span_attributes(attributes: dict[str, Any]) -> None:
    span = _current_span()
    if span is None:
        return
    for key, value in attributes.items():
        _safe_set(span, key, value)


def set_metadata(metadata: dict[str, Any]) -> None:
    """Free-form metadata shown in the Phoenix span detail and usable as a filter."""
    span = _current_span()
    if span is not None:
        _safe_set(span, SpanAttributes.METADATA, to_safe_payload(metadata))


def set_llm_attributes(model: str, provider: str, prompt_tokens: int = 0,
                       completion_tokens: int = 0, total_tokens: int = 0,
                       invocation_parameters: dict[str, Any] | None = None) -> None:
    """Record model, provider and token counts on the current LLM span."""
    span = _current_span()
    if span is None:
        return
    try:
        attributes = get_llm_attributes(
            provider=provider, model_name=model,
            invocation_parameters=invocation_parameters or {},
            token_count=TokenCount(prompt=prompt_tokens, completion=completion_tokens,
                                   total=total_tokens or prompt_tokens + completion_tokens),
        )
        for key, value in attributes.items():
            _safe_set(span, key, value)
    except Exception as exc:  # pragma: no cover
        logger.debug("set_llm_attributes failed: %s", exc)


def set_retrieved_documents(documents: Sequence[dict[str, Any]]) -> None:
    """Record retrieved chunks on the current retriever span (enables Phoenix RAG analysis)."""
    span = _current_span()
    if span is None:
        return
    try:
        docs = [Document(id=str(d.get("id", i)),
                         content=redact_text(str(d.get("content", ""))).text if STATE.redact
                         else str(d.get("content", "")),
                         score=float(d.get("score", 0.0)),
                         metadata={k: v for k, v in d.items() if k not in {"id", "content", "score"}})
                for i, d in enumerate(documents)]
        for key, value in get_retriever_attributes(documents=docs).items():
            _safe_set(span, key, value)
    except Exception as exc:  # pragma: no cover
        logger.debug("set_retrieved_documents failed: %s", exc)


def set_tool_attributes(name: str, description: str = "", parameters: Any = None) -> None:
    span = _current_span()
    if span is None:
        return
    _safe_set(span, SpanAttributes.TOOL_NAME, name)
    if description:
        _safe_set(span, SpanAttributes.TOOL_DESCRIPTION, description)
    if parameters is not None:
        _safe_set(span, SpanAttributes.TOOL_PARAMETERS, to_safe_payload(parameters))


@contextmanager
def trace_attributes(session_id: str | None = None, user_id: str | None = None,
                     tags: list[str] | None = None, metadata: dict[str, Any] | None = None
                     ) -> Iterator[None]:
    """Attach session, user, tags and metadata to every span created inside the block."""
    if not STATE.enabled or not OTEL_AVAILABLE:
        yield
        return
    try:
        ctx = using_attributes(session_id=session_id or "", user_id=user_id or "",
                               tags=tags or [], metadata=metadata or {})
    except Exception as exc:  # pragma: no cover
        logger.debug("using_attributes failed: %s", exc)
        ctx = nullcontext()
    with ctx:
        yield


def current_ids() -> tuple[str | None, str | None]:
    """(trace_id, span_id) as hex strings — store them to correlate logs, tickets and feedback."""
    span = _current_span()
    if span is None:
        return None, None
    ctx = span.get_span_context()
    return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"


# --------------------------------------------------------------------------------------------
# Annotations (online evaluation signal)
# --------------------------------------------------------------------------------------------
def annotate_span(span_id: str | None, name: str, score: float | None = None,
                  label: str | None = None, explanation: str | None = None,
                  annotator_kind: str = "CODE") -> None:
    """Write a score onto a span: guardrail outcomes (CODE), user feedback (HUMAN), judges (LLM)."""
    if not span_id or STATE.client is None:
        return
    if annotator_kind == "CODE" and not STATE.annotations_enabled:
        return          # keep the hot path free of REST calls in high-volume deployments
    try:
        STATE.client.spans.add_span_annotation(
            span_id=span_id, annotation_name=name, annotator_kind=annotator_kind,
            score=score, label=label, explanation=explanation)
    except Exception as exc:
        logger.debug("add_span_annotation failed: %s", exc)


def flush() -> None:
    if STATE.enabled and STATE.provider is not None:
        try:
            STATE.provider.force_flush()
        except Exception as exc:  # pragma: no cover
            logger.debug("force_flush failed: %s", exc)


def shutdown() -> None:
    if STATE.provider is not None:
        try:
            STATE.provider.shutdown()
        except Exception as exc:  # pragma: no cover
            logger.debug("shutdown failed: %s", exc)
