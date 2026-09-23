.PHONY: install test lint eval eval-langfuse push-dataset ask chat api docker langfuse

install:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[api,dev]"

test:
	pytest -q

lint:
	ruff check src tests

eval:
	agentctl-lf eval --mode local

eval-langfuse:
	agentctl-lf eval --mode langfuse

ask:
	agentctl-lf ask "My VPN keeps disconnecting when I work from home. How do I fix it?"

chat:
	agentctl-lf chat --agent it_helpdesk

api:
	uvicorn langfuse_agents.api.app:app --reload --port 8000

docker:
	docker compose up --build

langfuse:
	bash scripts/start_langfuse_local.sh

push-dataset:
	agentctl-lf push-dataset
