from agentic_eval import EvalCase, create_metric
from tests.conftest import make_trace, run


def evaluate(metric, trace, case):
    return run(metric.evaluate(trace, case))


def test_tool_call_accuracy_f1():
    case = EvalCase(input="x", expected_tools=["a", "b"])
    r = evaluate(create_metric("tool_call_accuracy"), make_trace(tools=["a", "c"]), case)
    assert r.score == 0.5 and not r.passed
    assert r.details["missing"] == ["b"] and r.details["unexpected"] == ["c"]


def test_tool_argument_accuracy_soft_match():
    case = EvalCase(input="x", expected_tool_args={"reset_password": {"user_id": "J.Doe"}})
    trace = make_trace(tools=[("reset_password", {"user_id": "j.doe "})])
    assert evaluate(create_metric("tool_argument_accuracy"), trace, case).score == 1.0


def test_trajectory_modes():
    trace = make_trace(tools=["search", "extra", "reset", "ticket"])
    base = {"input": "x", "expected_trajectory": ["search", "reset", "ticket"]}
    assert evaluate(create_metric("trajectory_match", mode="in_order"), trace, EvalCase(**base)).score == 1.0
    assert evaluate(create_metric("trajectory_match", mode="strict"), trace, EvalCase(**base)).score == 0.75
    assert evaluate(create_metric("trajectory_match", mode="superset"), trace, EvalCase(**base)).score == 1.0
    assert evaluate(create_metric("trajectory_match", mode="subset"), trace, EvalCase(**base)).score == 0.75
    # per-case override of the mode
    strict_case = EvalCase(**base, trajectory_mode="strict")
    assert evaluate(create_metric("trajectory_match", mode="in_order"), trace, strict_case).score == 0.75


def test_loop_detection_and_step_efficiency():
    trace = make_trace(tools=[("search", {"q": "vpn"})] * 3 + [("ticket", {})])
    case = EvalCase(input="x", expected_trajectory=["search", "ticket"])
    loop = evaluate(create_metric("loop_detection"), trace, case)
    assert loop.score == 0.5 and loop.details["repeated"] == {"search": 3}
    assert evaluate(create_metric("step_efficiency"), trace, case).score == 0.5


def test_metric_skipped_when_expectation_missing(case):
    r = evaluate(create_metric("tool_call_accuracy"), make_trace(tools=["a"]), case)
    assert r.skipped and r.passed


def test_budget_metrics():
    trace = make_trace(tools=["a", "b", "c", "d"])
    case = EvalCase(input="x", constraints={"max_steps": 2, "max_latency_ms": 10_000})
    assert evaluate(create_metric("step_budget"), trace, case).score == 0.5
    assert evaluate(create_metric("latency_budget"), trace, case).passed
