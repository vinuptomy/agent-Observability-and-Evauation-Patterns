"""Evaluation dataset loading and publishing to Phoenix Datasets."""

from __future__ import annotations

import json
import logging
from importlib import resources
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"case_id", "agent", "input", "expected_tools", "must_refuse"}


def load_cases(path: str | Path | None = None) -> list[dict]:
    """Load the regression suite from JSONL (the repo-versioned source of truth)."""
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (resources.files("phoenix_agents.evaluation.datasets")
                .joinpath("agent_eval.jsonl").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in text.splitlines() if line.strip()]
    for case in cases:
        missing = REQUIRED_FIELDS - case.keys()
        if missing:
            raise ValueError(f"Case {case.get('case_id')} missing fields: {sorted(missing)}")
    return cases


def to_phoenix_examples(cases: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split cases into Phoenix (inputs, outputs, metadata) example columns."""
    inputs = [{"input": c["input"]} for c in cases]
    outputs = [{"expected_answer": c.get("expected_output")} for c in cases]
    metadata = [{k: v for k, v in c.items() if k != "input"} for c in cases]
    return inputs, outputs, metadata


def push_to_phoenix(client: Any, dataset_name: str, cases: list[dict]) -> Any:
    """Create a dataset version in Phoenix. Re-running adds a new version, keeping history."""
    inputs, outputs, metadata = to_phoenix_examples(cases)
    dataset = client.datasets.create_dataset(
        name=dataset_name,
        dataset_description="Enterprise agent regression suite: trajectory, grounding, retrieval, "
                            "safety and privacy",
        inputs=inputs, outputs=outputs, metadata=metadata,
    )
    logger.info("Pushed %s cases to Phoenix dataset '%s'", len(cases), dataset_name)
    return dataset
