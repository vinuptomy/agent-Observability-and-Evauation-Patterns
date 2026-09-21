"""Dataset loading (JSONL / JSON / YAML) with validation and security limits."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import yaml

from agentic_eval.core.exceptions import DatasetError
from agentic_eval.core.models import EvalCase
from agentic_eval.security.validation import sanitize_text


def load_dataset(path: str | Path, max_cases: int = 10_000, max_input_chars: int = 20_000,
                 tags: Iterable[str] | None = None) -> list[EvalCase]:
    p = Path(path)
    if not p.is_file():
        raise DatasetError(f"dataset not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip() and not line.lstrip().startswith("//")]
    elif p.suffix == ".json":
        rows = json.loads(text)
    elif p.suffix in (".yaml", ".yml"):
        rows = yaml.safe_load(text)
    else:
        raise DatasetError(f"unsupported dataset format: {p.suffix}")
    if isinstance(rows, dict):
        rows = rows.get("cases", [])
    if len(rows) > max_cases:
        raise DatasetError(f"dataset has {len(rows)} cases > max_cases={max_cases}")
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        try:
            case = EvalCase.model_validate(row)
            case.input = sanitize_text(case.input, max_input_chars)
        except Exception as exc:
            raise DatasetError(f"{p}: case #{i} invalid: {exc}") from exc
        if case.case_id in seen:
            raise DatasetError(f"duplicate case_id '{case.case_id}'")
        seen.add(case.case_id)
        cases.append(case)
    if tags:
        wanted = set(tags)
        cases = [c for c in cases if wanted & set(c.tags)]
    return cases
