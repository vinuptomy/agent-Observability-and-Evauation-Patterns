"""Production judge providers. SDKs are optional extras and imported lazily."""
from __future__ import annotations

import os
from typing import Any

from agentic_eval.core.exceptions import ConfigurationError
from agentic_eval.judges.base import BaseJudge
from agentic_eval.judges.mock import MockJudge


def _require(module: str, extra: str) -> Any:
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as exc:
        raise ConfigurationError(f"Install the '{extra}' extra: pip install 'agentic-eval-kit[{extra}]'") from exc


class OpenAIJudge(BaseJudge):
    """OpenAI or any OpenAI-compatible endpoint (vLLM, Ollama, LiteLLM proxy) via ``base_url``."""

    provider = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None, base_url: str | None = None,
                 json_mode: bool = True, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        openai = _require("openai", "openai")
        self.json_mode = json_mode
        self._client = openai.AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"),
                                          base_url=base_url or os.getenv("OPENAI_BASE_URL") or None)

    async def _complete(self, system: str, user: str) -> str:
        extra = {"response_format": {"type": "json_object"}} if self.json_mode else {}
        resp = await self._client.chat.completions.create(
            model=self.model, temperature=self.temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **extra)
        return resp.choices[0].message.content or ""


class AzureOpenAIJudge(OpenAIJudge):
    """Azure OpenAI / Azure AI Foundry. Uses Entra ID (managed identity) when no API key is set —
    the recommended enterprise setup (no long-lived secrets)."""

    provider = "azure_openai"

    def __init__(self, model: str | None = None, endpoint: str | None = None, api_version: str | None = None,
                 api_key: str | None = None, **kwargs: Any) -> None:
        BaseJudge.__init__(self, model=model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"), **kwargs)
        openai = _require("openai", "azure")
        self.json_mode = True
        endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        if not endpoint:
            raise ConfigurationError("AZURE_OPENAI_ENDPOINT is not set")
        api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        if key:
            self._client = openai.AsyncAzureOpenAI(azure_endpoint=endpoint, api_version=api_version, api_key=key)
        else:
            identity = _require("azure.identity", "azure")
            provider = identity.get_bearer_token_provider(
                identity.DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            self._client = openai.AsyncAzureOpenAI(azure_endpoint=endpoint, api_version=api_version,
                                                   azure_ad_token_provider=provider)


class AnthropicJudge(BaseJudge):
    provider = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        anthropic = _require("anthropic", "anthropic")
        self._client = anthropic.AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    async def _complete(self, system: str, user: str) -> str:
        resp = await self._client.messages.create(
            model=self.model, max_tokens=512, temperature=self.temperature, system=system,
            messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in resp.content)


_PROVIDERS: dict[str, type[BaseJudge]] = {
    "mock": MockJudge, "openai": OpenAIJudge, "azure_openai": AzureOpenAIJudge, "anthropic": AnthropicJudge,
}


def register_judge(name: str, cls: type[BaseJudge]) -> None:
    """Register a custom provider (e.g. Bedrock, Vertex AI, an internal gateway)."""
    _PROVIDERS[name] = cls


def create_judge(provider: str = "mock", model: str | None = None, **params: Any) -> BaseJudge:
    if provider not in _PROVIDERS:
        raise ConfigurationError(f"Unknown judge provider '{provider}'. Available: {sorted(_PROVIDERS)}")
    if model is not None and provider != "mock":
        params["model"] = model
    return _PROVIDERS[provider](**params)
