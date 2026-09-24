"""OpenInference/Phoenix instrumentation, including behaviour when Phoenix is unavailable."""

from phoenix_agents.agents.factory import build_agent
from phoenix_agents.observability import tracing
from phoenix_agents.observability.usage import UsageTracker


def test_safe_payload_is_redacted_and_bounded():
    payload = tracing.to_safe_payload({"email": "a.b@contoso.com", "text": "x" * 9000})
    assert "a.b@contoso.com" not in payload
    assert len(payload) <= 4100


def test_span_kinds_cover_the_openinference_set():
    assert {tracing.AGENT, tracing.CHAIN, tracing.LLM, tracing.TOOL, tracing.RETRIEVER,
            tracing.GUARDRAIL} == {"agent", "chain", "llm", "tool", "retriever", "guardrail"}


def test_tracing_disabled_is_a_noop(settings):
    assert tracing.init_observability(settings) is False
    tracing.set_metadata({"x": 1})
    tracing.set_llm_attributes("m", "mock", 1, 2, 3)
    tracing.set_retrieved_documents([{"id": "KB-1", "content": "c", "score": 1.0}])
    tracing.annotate_span("abc", "score", 1.0)
    tracing.flush()
    assert tracing.current_ids() == (None, None)


def test_traced_decorator_passes_through_when_disabled():
    @tracing.traced(name="unit.test", kind=tracing.CHAIN)
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


def test_agent_runs_and_records_retrieved_ids(settings):
    result = build_agent("policy_qa", settings).run("What is the AI usage policy?")
    assert result.status == "completed"
    assert "KB-202" in result.retrieved_ids     # retriever span data feeds the RAG metrics
    assert result.trace_id is None              # tracing disabled in tests


def test_usage_tracker_costs():
    tracker = UsageTracker()
    tracker.add({"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracker.estimated_cost_usd("gpt-4o-mini") == 0.15
