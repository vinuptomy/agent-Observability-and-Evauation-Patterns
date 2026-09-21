"""Command line interface.

    agentic-eval list-metrics
    agentic-eval run --config config/eval_config.yaml --dataset data.jsonl --target examples.x.agents:run
    agentic-eval eval-traces --config ... --traces traces.jsonl --dataset data.jsonl
    agentic-eval verify-audit reports/audit.jsonl

Exit codes: 0 = gate passed, 1 = gate failed, 2 = configuration/usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import agentic_eval.metrics  # noqa: F401
from agentic_eval.core.config import load_config
from agentic_eval.core.exceptions import AgenticEvalError
from agentic_eval.core.metric import list_metrics
from agentic_eval.core.models import Trace
from agentic_eval.observability.logging_setup import configure_logging
from agentic_eval.reporting.reporters import write_reports
from agentic_eval.runners.dataset import load_dataset
from agentic_eval.runners.evaluator import Evaluator
from agentic_eval.runners.gate import QualityGate
from agentic_eval.security.audit import AuditLogger
from agentic_eval.security.validation import load_target


def _finish(report, cfg, output_dir: str | None) -> int:  # type: ignore[no-untyped-def]
    gate = QualityGate(**cfg.gate.model_dump()).evaluate(report)
    paths = write_reports(report, output_dir or cfg.reporting.output_dir, cfg.reporting.formats, gate,
                          cfg.reporting.include_traces)
    s = report.summary()
    print(json.dumps({"run_id": s["run_id"], "pass_rate": s["pass_rate"], "mean_score": s["mean_score"],
                      "gate_passed": gate.passed, "violations": gate.violations,
                      "reports": [str(p) for p in paths]}, indent=2))
    return 0 if gate.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-eval", description="Pluggable evaluation for agentic AI systems")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-metrics", help="show all registered metrics")

    run = sub.add_parser("run", help="execute a target agent over a dataset and evaluate it")
    run.add_argument("--config", required=True)
    run.add_argument("--dataset", required=True)
    run.add_argument("--target", required=True, help="module.path:callable (must be allow-listed)")
    run.add_argument("--tags", nargs="*")
    run.add_argument("--output-dir")

    ev = sub.add_parser("eval-traces", help="evaluate pre-recorded traces (JSONL of Trace objects)")
    ev.add_argument("--config", required=True)
    ev.add_argument("--dataset", required=True)
    ev.add_argument("--traces", required=True, help="JSONL; each trace must carry metadata.case_id")
    ev.add_argument("--output-dir")

    va = sub.add_parser("verify-audit", help="verify the hash chain of an audit log")
    va.add_argument("path")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "list-metrics":
            for name, info in list_metrics().items():
                judge = " [LLM judge]" if info["uses_judge"] else ""
                print(f"{name:<30} {info['category']:<12} {info['description']}{judge}")
            return 0
        if args.cmd == "verify-audit":
            ok, line = AuditLogger.verify(args.path)
            print("audit log intact" if ok else f"audit log TAMPERED at line {line}")
            return 0 if ok else 1

        cfg = load_config(args.config)
        configure_logging(cfg.observability.log_level, cfg.observability.json_logs)
        evaluator = Evaluator.from_config(cfg)
        cases = load_dataset(args.dataset, cfg.security.max_cases, cfg.security.max_input_chars,
                             getattr(args, "tags", None))
        if args.cmd == "run":
            sys.path.insert(0, str(Path.cwd()))
            target = load_target(args.target, cfg.security.allowed_target_modules)
            report = evaluator.run(target, cases)
        else:
            by_id = {c.case_id: c for c in cases}
            pairs = []
            for line in Path(args.traces).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    trace = Trace.model_validate_json(line)
                    case = by_id.get(trace.metadata.get("case_id", ""))
                    if case:
                        pairs.append((trace, case))
            report = evaluator.evaluate_traces(pairs)
        return _finish(report, cfg, args.output_dir)
    except AgenticEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
