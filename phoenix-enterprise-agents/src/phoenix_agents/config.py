"""Centralised, typed configuration (12-factor: everything comes from env / .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Runtime
    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # LLM
    llm_provider: Literal["mock", "openai", "azure", "ollama"] = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = Field(0.0, ge=0.0, le=2.0)
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3
    openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "2024-10-21"
    ollama_base_url: str = "http://localhost:11434/v1"

    # Agent limits
    agent_max_steps: int = Field(6, ge=1, le=20)
    agent_max_input_chars: int = Field(4000, ge=100)

    # Observability (Arize Phoenix / OpenTelemetry)
    phoenix_enabled: bool = True
    phoenix_collector_endpoint: str = "http://localhost:6006/v1/traces"
    phoenix_base_url: str = "http://localhost:6006"
    phoenix_api_key: SecretStr | None = None
    phoenix_project_name: str = "enterprise-agents"
    phoenix_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    phoenix_auto_instrument: bool = False
    phoenix_annotate_guardrails: bool = True   # one REST call per run; disable at high volume
    release: str = "0.1.0"

    # Security
    redact_pii_in_traces: bool = True
    redact_pii_in_prompts: bool = True
    api_key: SecretStr | None = None

    # Evaluation
    eval_use_llm_judge: bool = False
    eval_judge_model: str = "gpt-4o-mini"
    eval_dataset_name: str = "enterprise-agent-regression"
    eval_max_concurrency: int = Field(4, ge=1, le=50)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
