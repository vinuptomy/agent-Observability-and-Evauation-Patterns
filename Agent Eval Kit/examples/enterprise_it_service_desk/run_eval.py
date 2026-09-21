"""Programmatic usage example: evaluate the production and the naive service desk side by side.

    python -m examples.enterprise_it_service_desk.run_eval
"""
from __future__ import annotations

from pathlib import Path

from agentic_eval import Evaluator, QualityGate, load_dataset
from agentic_eval.core.config import load_config
from agentic_eval.observability import configure_logging
from agentic_eval.reporting import write_reports
from examples.enterprise_it_service_desk.agents import run_service_desk, run_service_desk_naive

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    cfg = load_config(ROOT / "config" / "eval_config.yaml")
    configure_logging("WARNING", json_format=True)
    cases = load_dataset(Path(__file__).with_name("dataset.jsonl"))
    gate = QualityGate(**cfg.gate.model_dump())

    for label, target in (("production", run_service_desk), ("naive", run_service_desk_naive)):
        cfg.name = f"it-service-desk-{label}"
        evaluator = Evaluator.from_config(cfg)
        report = evaluator.run(target, cases)
        result = gate.evaluate(report)
        paths = write_reports(report, ROOT / "reports", ["json", "markdown", "junit"], result)
        s = report.summary()
        print(f"\n=== {label.upper()} === pass_rate={s['pass_rate']:.0%} mean_score={s['mean_score']:.3f} "
              f"gate={'PASS' if result.passed else 'FAIL'}")
        for v in result.violations[:8]:
            print("  -", v)
        print("  report:", paths[1])


if __name__ == "__main__":
    main()
