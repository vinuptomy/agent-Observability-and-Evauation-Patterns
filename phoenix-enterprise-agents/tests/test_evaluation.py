"""Agent and RAG metrics, plus the offline quality gate."""

from phoenix_agents.evaluation.dataset import load_cases, to_phoenix_examples
from phoenix_agents.evaluation.metrics import (
    citation_presence,
    keyword_coverage,
    no_pii_leakage,
    phoenix_evaluators,
    retrieval_hit_rate,
    retrieval_precision,
    safety_refusal,
    step_efficiency,
    tool_selection_accuracy,
)
from phoenix_agents.evaluation.runner import run_local


def _out(**kwargs):
    base = {"answer": "", "tool_calls": [], "status": "completed", "steps": 1, "retrieved_ids": []}
    return {**base, **kwargs}


def test_trajectory_metrics():
    assert tool_selection_accuracy(_out(tool_calls=["search_knowledge_base"]),
                                   {"expected_tools": ["search_knowledge_base"]}).score == 1.0
    assert tool_selection_accuracy(_out(tool_calls=["create_ticket"]),
                                   {"expected_tools": [], "forbidden_tools": ["create_ticket"]}).score == 0.0
    assert step_efficiency(_out(steps=6), {"max_steps": 3}).score == 0.5


def test_content_and_safety_metrics():
    assert keyword_coverage(_out(answer="Reset via MFA"), {"expected_keywords": ["reset", "mfa"]}).score == 1.0
    assert citation_presence(_out(answer="See [KB-102]"), {"requires_citation": True}).score == 1.0
    assert safety_refusal(_out(status="completed"), {"must_refuse": True}).score == 0.0
    assert no_pii_leakage(_out(answer="mail me at a.b@c.com")).score == 0.0


def test_rag_retrieval_metrics():
    meta = {"expected_kb_ids": ["KB-101"]}
    assert retrieval_hit_rate(_out(retrieved_ids=["KB-101", "KB-203"]), meta).score == 1.0
    assert retrieval_hit_rate(_out(retrieved_ids=["KB-203"]), meta).score == 0.0
    assert retrieval_precision(_out(retrieved_ids=["KB-101", "KB-203"]), meta).score == 0.5


def test_phoenix_evaluator_adapters_return_score_tuples():
    evaluators = phoenix_evaluators()
    assert "retrieval_hit_rate" in evaluators
    score, label, explanation = evaluators["task_completion"](
        output=_out(status="completed"), metadata={"must_refuse": False})
    assert score == 1.0 and label == "pass" and explanation


def test_dataset_is_valid_and_converts_to_phoenix_examples():
    cases = load_cases()
    assert len(cases) >= 2
    inputs, outputs, metadata = to_phoenix_examples(cases)
    assert len(inputs) == len(outputs) == len(metadata) == len(cases)
    assert metadata[0]["case_id"] and "input" in inputs[0]


def test_local_evaluation_passes_quality_gate(settings, tmp_path):
    report, passed = run_local(settings, report_dir=str(tmp_path))
    assert passed, report["quality_gate"]
    assert report["num_cases"] == 6
    assert report["run_metrics"]["escalation_rate"] == 0.0
