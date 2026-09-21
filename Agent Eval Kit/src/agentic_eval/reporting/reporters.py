from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from xml.sax.saxutils import escape

from agentic_eval.core.models import EvalReport
from agentic_eval.runners.gate import GateResult


def write_json(report: EvalReport, path: str | Path, include_traces: bool = False) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = report.model_dump()
    data["summary"] = report.summary()
    for c_data, c in zip(data["cases"], report.cases, strict=True):
        c_data["passed"], c_data["score"] = c.passed, round(c.score, 4)
        if include_traces and c.trace is not None:
            c_data["trace"] = c.trace.model_dump()
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return p


def write_markdown(report: EvalReport, path: str | Path, gate: GateResult | None = None) -> Path:
    s = report.summary()
    lines = [f"# Evaluation report — {report.name}", "",
             f"Run `{report.run_id}` · started {report.started_at} · finished {report.finished_at}", "",
             f"**Cases:** {s['passed_cases']}/{s['total_cases']} passed ({s['pass_rate']:.0%}) · "
             f"**Mean score:** {s['mean_score']:.3f}", ""]
    if gate is not None:
        lines += [f"**Quality gate:** {'✅ PASSED' if gate.passed else '❌ FAILED'}", ""]
        lines += [f"- {v}" for v in gate.violations] + ([""] if gate.violations else [])
    lines += ["## Scores by category", "", "| Category | Mean |", "|---|---|"]
    lines += [f"| {k} | {v:.3f} |" for k, v in s["categories"].items()]
    lines += ["", "## Metrics", "", "| Metric | Category | Mean | Min | Pass rate | N | Errors |",
              "|---|---|---|---|---|---|---|"]
    for name, m in s["metrics"].items():
        lines.append(f"| {name} | {m['category']} | {m['mean']:.3f} | {m['min'] if m['min'] is not None else '-'} "
                     f"| {m['pass_rate']:.0%} | {m['n']} | {m['errors']} |")
    lines += ["", "## Cases", "", "| Case | Passed | Score | Agents | Tools | Latency ms | Tokens |",
              "|---|---|---|---|---|---|---|"]
    for c in report.cases:
        t = c.trace_summary
        lines.append(f"| {c.case_id} | {'✅' if c.passed else '❌'} | {c.score:.3f} | {' → '.join(t.get('agents', []))} "
                     f"| {', '.join(t.get('tools', []))} | {t.get('latency_ms', 0)} | {t.get('tokens', 0)} |")
    failed = [c for c in report.cases if not c.passed]
    if failed:
        lines += ["", "## Failures", ""]
        for c in failed:
            lines.append(f"### {c.case_id}")
            for r in c.failed_metrics():
                lines.append(f"- **{r.metric}** ({r.category}) score={r.score} < {r.threshold}: "
                             f"{r.error or r.reason}")
            lines.append("")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def write_junit(report: EvalReport, path: str | Path) -> Path:
    """One <testsuite> per run, one <testcase> per (case, metric) — renders in GitHub/Azure DevOps/Jenkins."""
    cases_xml, failures, total = [], 0, 0
    for c in report.cases:
        for r in c.results:
            total += 1
            name = escape(f"{c.case_id}.{r.metric}", {'"': "&quot;"})
            body = ""
            if r.skipped:
                body = f'<skipped message="{escape(r.reason, {chr(34): "&quot;"})}"/>'
            elif not r.passed or r.error:
                failures += 1
                msg = escape(f"score={r.score} threshold={r.threshold} {r.error or r.reason}", {'"': "&quot;"})
                body = f'<failure message="{msg}"/>'
            cases_xml.append(f'  <testcase classname="{escape(r.category)}" name="{name}" '
                             f'time="{r.duration_ms / 1000:.4f}">{body}</testcase>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="{escape(report.name)}" tests="{total}" '
           f'failures="{failures}">\n' + "\n".join(cases_xml) + "\n</testsuite>\n")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(xml, encoding="utf-8")
    return p


def write_reports(report: EvalReport, output_dir: str | Path, formats: Iterable[str] = ("json", "markdown"),
                  gate: GateResult | None = None, include_traces: bool = False) -> list[Path]:
    out = Path(output_dir)
    stem = f"{report.name}-{report.run_id}"
    written = []
    for fmt in formats:
        if fmt == "json":
            written.append(write_json(report, out / f"{stem}.json", include_traces))
        elif fmt == "markdown":
            written.append(write_markdown(report, out / f"{stem}.md", gate))
        elif fmt == "junit":
            written.append(write_junit(report, out / f"{stem}.junit.xml"))
        else:
            raise ValueError(f"unknown report format {fmt}")
    return written
