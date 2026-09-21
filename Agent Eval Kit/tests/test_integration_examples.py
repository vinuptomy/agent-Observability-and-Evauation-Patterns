"""The offline integration examples must keep working (they are part of the documentation)."""
import runpy


def test_otel_example_runs(capsys):
    runpy.run_module("examples.integrations.otel_any_framework", run_name="__main__")
    out = capsys.readouterr().out
    assert "handoff_accuracy" in out and "passed=False" not in out


def test_custom_metrics_example_runs(capsys):
    runpy.run_module("examples.integrations.custom_metrics", run_name="__main__")
    assert "approval_before_action       1.00" in capsys.readouterr().out
