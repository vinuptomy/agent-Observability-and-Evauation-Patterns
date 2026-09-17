"""Evaluation dataset loading and publishing to Opik."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

REQUIRED_FIELDS = {"case_id", "agent", "input", "expected_tools", "must_refuse"}


def load_cases(path: str | Path | None = None) -> list[dict]:
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (resources.files("enterprise_agents.evaluation.datasets")
                .joinpath("agent_eval.jsonl").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in text.splitlines() if line.strip()]
    for case in cases:
        missing = REQUIRED_FIELDS - case.keys()
        if missing:
            raise ValueError(f"Case {case.get('case_id')} missing fields: {sorted(missing)}")
    return cases


def push_to_opik(dataset_name: str, cases: list[dict]):
    """Create/refresh an Opik dataset (Opik de-duplicates identical items)."""
    import opik

    client = opik.Opik()
    dataset = client.get_or_create_dataset(
        name=dataset_name, description="Enterprise agent regression suite")
    dataset.insert(cases)
    return dataset
