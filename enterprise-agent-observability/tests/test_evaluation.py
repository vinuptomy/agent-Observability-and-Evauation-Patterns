from enterprise_agents.evaluation.dataset import load_cases
from enterprise_agents.evaluation.metrics import (
    CitationPresence,
    KeywordCoverage,
    NoPIILeakage,
    SafetyRefusal,
    ToolSelectionAccuracy,
)
from enterprise_agents.evaluation.runner import run_local


def test_tool_selection_metric():
    m = ToolSelectionAccuracy()
    assert m.score(tool_calls=["search_knowledge_base"], expected_tools=["search_knowledge_base"]).value == 1.0
    assert m.score(tool_calls=["create_ticket"], expected_tools=[], forbidden_tools=["create_ticket"]).value == 0.0


def test_content_and_safety_metrics():
    assert KeywordCoverage().score(output="Reset via MFA", expected_keywords=["reset", "mfa"]).value == 1.0
    assert CitationPresence().score(output="See [KB-102]", requires_citation=True).value == 1.0
    assert SafetyRefusal().score(status="completed", must_refuse=True).value == 0.0
    assert NoPIILeakage().score(output="mail me at a.b@c.com").value == 0.0


def test_dataset_is_valid():
    assert len(load_cases()) >= 2


def test_local_evaluation_passes_quality_gate(settings, tmp_path):
    report, passed = run_local(settings, report_dir=str(tmp_path))
    assert passed, report["quality_gate"]
    assert report["num_cases"] == 6
