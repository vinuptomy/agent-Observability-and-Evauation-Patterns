"""Evaluation dataset loading and publishing to Langfuse Datasets."""

from __future__ import annotations

import json
import logging
from importlib import resources
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"case_id", "agent", "input", "expected_tools", "must_refuse"}


def load_cases(path: str | Path | None = None) -> list[dict]:
    """Load the regression suite from JSONL (repo-versioned source of truth)."""
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (resources.files("langfuse_agents.evaluation.datasets")
                .joinpath("agent_eval.jsonl").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in text.splitlines() if line.strip()]
    for case in cases:
        missing = REQUIRED_FIELDS - case.keys()
        if missing:
            raise ValueError(f"Case {case.get('case_id')} missing fields: {sorted(missing)}")
    return cases


def to_local_items(cases: list[dict]) -> list[dict]:
    """Convert cases to Langfuse ``LocalExperimentItem`` shape (input / expected_output / metadata)."""
    return [{"input": c["input"],
             "expected_output": c.get("expected_output"),
             "metadata": {k: v for k, v in c.items() if k != "input"}}
            for c in cases]


def push_to_langfuse(client: Any, dataset_name: str, cases: list[dict]) -> None:
    """Create (or update) a Langfuse dataset; item ids are the case ids, so re-runs are idempotent."""
    client.create_dataset(
        name=dataset_name,
        description="Enterprise agent regression suite (tool trajectory, grounding, safety, privacy)",
        metadata={"source": "repo:evaluation/datasets/agent_eval.jsonl"},
    )
    for case in cases:
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=case["case_id"],
            input=case["input"],
            expected_output=case.get("expected_output"),
            metadata={k: v for k, v in case.items() if k != "input"},
        )
    logger.info("Pushed %s cases to Langfuse dataset '%s'", len(cases), dataset_name)
