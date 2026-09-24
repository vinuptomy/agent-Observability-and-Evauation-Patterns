import pytest

from phoenix_agents.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Offline settings: deterministic mock LLM, tracing off, small step budget."""
    return Settings(_env_file=None, app_env="test", llm_provider="mock", phoenix_enabled=False,
                    agent_max_steps=4)
