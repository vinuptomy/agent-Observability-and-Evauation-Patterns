import os

import pytest

os.environ.setdefault("OPIK_TRACK_DISABLE", "true")

from enterprise_agents.config import Settings  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, app_env="test", llm_provider="mock", opik_enabled=False,
                    agent_max_steps=4)
