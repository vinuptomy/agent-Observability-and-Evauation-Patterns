"""System-instruction loading with optional Langfuse Prompt Management.

Two sources, one interface:

* **Repository files** (default) — prompts are versioned with the code in ``prompts/*.md``.
  Simple, reviewable, GitOps-friendly.
* **Langfuse Prompt Management** (``LANGFUSE_PROMPT_MANAGEMENT=true``) — prompts are fetched by
  name and label (e.g. ``production``), so non-developers can iterate and roll back in the UI
  without a deployment. The returned object is linked to generations for per-version analytics.

The file version is always the fallback, so a Langfuse outage cannot take the agents down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources
from typing import Any

from langfuse_agents.observability import tracing

logger = logging.getLogger(__name__)


@dataclass
class LoadedPrompt:
    text: str
    source: str           # "file" | "langfuse"
    version: str | None = None
    client_object: Any = None   # Langfuse prompt client, for linking to generations


def load_from_file(filename: str) -> str:
    return resources.files("langfuse_agents.prompts").joinpath(filename).read_text(encoding="utf-8")


def load_prompt(name: str, filename: str, settings: Any) -> LoadedPrompt:
    file_text = load_from_file(filename)
    if not getattr(settings, "langfuse_prompt_management", False):
        return LoadedPrompt(file_text, "file")

    client = tracing.get_client()
    if client is None:
        logger.info("Prompt management requested but Langfuse is not active; using file prompt")
        return LoadedPrompt(file_text, "file")
    try:
        prompt = client.get_prompt(name, label=settings.langfuse_prompt_label)
        return LoadedPrompt(prompt.prompt, "langfuse", str(getattr(prompt, "version", "")), prompt)
    except Exception as exc:
        logger.warning("Falling back to file prompt for '%s': %s", name, exc)
        return LoadedPrompt(file_text, "file")
