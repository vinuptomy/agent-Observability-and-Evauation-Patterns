"""Typed configuration (YAML) with ``${ENV_VAR}`` / ``${ENV_VAR:-default}`` expansion.
Secrets are never stored in YAML — reference environment variables instead."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from agentic_eval.core.exceptions import ConfigurationError

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.getenv(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class JudgeConfig(BaseModel):
    provider: str = "mock"
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class MetricConfig(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class RunnerConfig(BaseModel):
    concurrency: int = Field(default=4, ge=1, le=256)
    case_timeout_s: float = Field(default=120.0, gt=0)


class SecurityConfig(BaseModel):
    redact_pii_for_judge: bool = True
    audit_log: str | None = "reports/audit.jsonl"
    max_input_chars: int = 20_000
    max_cases: int = 10_000
    allowed_target_modules: list[str] = Field(default_factory=lambda: ["examples."])


class ObservabilityConfig(BaseModel):
    log_level: str = "INFO"
    json_logs: bool = True
    otel_enabled: bool = False
    service_name: str = "agentic-eval"


class ReportingConfig(BaseModel):
    output_dir: str = "reports"
    formats: list[str] = Field(default_factory=lambda: ["json", "markdown"])
    include_traces: bool = False


class GateConfig(BaseModel):
    min_pass_rate: float = 1.0
    min_mean_score: float = 0.0
    blocking_categories: list[str] = Field(default_factory=lambda: ["safety"])
    metric_min_means: dict[str, float] = Field(default_factory=dict)


class EvalConfig(BaseModel):
    name: str = "eval-run"
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    metrics: list[MetricConfig] = Field(default_factory=list)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    gate: GateConfig = Field(default_factory=GateConfig)

    def redacted_dict(self) -> dict[str, Any]:
        """Config snapshot safe to embed into reports (no secrets)."""
        data = self.model_dump()
        for k in list(data["judge"]["params"]):
            if any(s in k.lower() for s in ("key", "secret", "token", "password")):
                data["judge"]["params"][k] = "***"
        return data


def load_config(path: str | Path) -> EvalConfig:
    p = Path(path)
    if not p.is_file():
        raise ConfigurationError(f"Config file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}  # safe_load: no arbitrary objects
    try:
        return EvalConfig.model_validate(_expand(raw))
    except Exception as exc:
        raise ConfigurationError(f"Invalid config {p}: {exc}") from exc
