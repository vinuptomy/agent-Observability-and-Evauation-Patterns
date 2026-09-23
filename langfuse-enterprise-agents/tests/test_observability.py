"""Langfuse instrumentation behaves correctly — including when Langfuse is unavailable."""

from langfuse_agents.agents.factory import build_agent
from langfuse_agents.observability import tracing
from langfuse_agents.observability.usage import UsageTracker


def test_mask_redacts_nested_payloads():
    masked = tracing.mask_payload(data={"user": {"mail": "anna.berger@contoso.com"},
                                        "notes": ["call +43 660 1234567"]})
    assert "anna.berger" not in str(masked)
    assert "1234567" not in str(masked)


def test_mask_never_raises_on_unserialisable_input():
    class Boom:
        def __str__(self):
            raise RuntimeError("nope")

    assert tracing.mask_payload(data=Boom()) is not None


def test_safe_payload_is_redacted_and_bounded():
    payload = tracing.to_safe_payload({"email": "a.b@contoso.com", "text": "x" * 9000})
    assert "a.b@contoso.com" not in payload
    assert len(payload) <= 4100


def test_tracing_disabled_is_a_noop(settings):
    assert tracing.init_observability(settings) is False
    tracing.update_span(metadata={"x": 1})
    tracing.score_trace("test", 1.0)
    tracing.update_generation(model="m")
    tracing.flush()
    assert tracing.current_trace_id() is None


def test_agent_runs_without_langfuse(settings):
    result = build_agent("policy_qa", settings).run("What is the AI usage policy?")
    assert result.status == "completed"
    assert result.trace_id is None


def test_usage_tracker_costs():
    tracker = UsageTracker()
    tracker.add({"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracker.estimated_cost_usd("gpt-4o-mini") == 0.15
