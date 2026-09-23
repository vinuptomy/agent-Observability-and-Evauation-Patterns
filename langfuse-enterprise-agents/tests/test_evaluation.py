"""Evaluation metrics and the offline quality gate."""

from langfuse_agents.evaluation.dataset import load_cases, to_local_items
from langfuse_agents.evaluation.metrics import (
    citation_presence,
    keyword_coverage,
    no_pii_leakage,
    safety_refusal,
    step_efficiency,
    tool_selection_accuracy,
)
from langfuse_agents.evaluation.runner import run_local


def _out(**kwargs):
    base = {"answer": "", "tool_calls": [], "status": "completed", "steps": 1}
    return {**base, **kwargs}


def test_tool_selection_metric():
    good = tool_selection_accuracy(output=_out(tool_calls=["search_knowledge_base"]),
                                   metadata={"expected_tools": ["search_knowledge_base"]})
    assert good.value == 1.0
    bad = tool_selection_accuracy(output=_out(tool_calls=["create_ticket"]),
                                  metadata={"expected_tools": [], "forbidden_tools": ["create_ticket"]})
    assert bad.value == 0.0


def test_content_and_safety_metrics():
    assert keyword_coverage(output=_out(answer="Reset via MFA"),
                            metadata={"expected_keywords": ["reset", "mfa"]}).value == 1.0
    assert citation_presence(output=_out(answer="See [KB-102]"),
                             metadata={"requires_citation": True}).value == 1.0
    assert safety_refusal(output=_out(status="completed"), metadata={"must_refuse": True}).value == 0.0
    assert no_pii_leakage(output=_out(answer="mail me at a.b@c.com")).value == 0.0
    assert step_efficiency(output=_out(steps=6), metadata={"max_steps": 3}).value == 0.5


def test_dataset_is_valid_and_converts_to_langfuse_items():
    cases = load_cases()
    assert len(cases) >= 2
    items = to_local_items(cases)
    assert {"input", "expected_output", "metadata"} == set(items[0])
    assert items[0]["metadata"]["case_id"]


def test_local_evaluation_passes_quality_gate(settings, tmp_path):
    report, passed = run_local(settings, report_dir=str(tmp_path))
    assert passed, report["quality_gate"]
    assert report["num_cases"] == 6
    assert "escalation_rate" not in report["summary"]  # run-level metrics are Langfuse-only
