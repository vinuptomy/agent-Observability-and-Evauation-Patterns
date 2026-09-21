from agentic_eval import EvalCase, create_metric
from tests.conftest import make_trace, run

EXPECTED = [["supervisor", "triage"], ["triage", "resolver"], ["resolver", "supervisor"]]


def test_handoff_accuracy_perfect_and_order():
    trace = make_trace(handoffs=[tuple(h) for h in EXPECTED])
    r = run(create_metric("handoff_accuracy", check_order=True).evaluate(trace, EvalCase(input="x", expected_handoffs=EXPECTED)))
    assert r.score == 1.0


def test_handoff_accuracy_wrong_route():
    trace = make_trace(handoffs=[("supervisor", "triage"), ("triage", "billing"), ("billing", "supervisor")])
    r = run(create_metric("handoff_accuracy").evaluate(trace, EvalCase(input="x", expected_handoffs=EXPECTED)))
    assert r.score < 0.5 and ["triage", "resolver"] in r.details["missing"]


def test_coordination_detects_ping_pong():
    pingpong = [("a", "b"), ("b", "a")] * 3
    r = run(create_metric("coordination_efficiency").evaluate(make_trace(handoffs=pingpong), EvalCase(input="x")))
    assert r.details["ping_pong_excess"] == 4 and not r.passed


def test_agent_participation_penalises_unexpected():
    trace = make_trace(agents=["supervisor", "triage", "rogue"])
    r = run(create_metric("agent_participation").evaluate(trace, EvalCase(input="x", expected_agents=["supervisor", "triage"])))
    assert r.details["unexpected"] == ["rogue"] and r.score == 0.8


def test_error_recovery():
    recovered = make_trace(agents=["a"], tools=["t"], errors=("t",), output="fallback answer")
    assert run(create_metric("error_recovery").evaluate(recovered, EvalCase(input="x"))).score == 1.0
    failed = make_trace(agents=["a"], tools=["t"], errors=("t",), output="")
    assert run(create_metric("error_recovery").evaluate(failed, EvalCase(input="x"))).score == 0.0
