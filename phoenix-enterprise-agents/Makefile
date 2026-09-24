.PHONY: install test lint eval eval-phoenix push-dataset ask chat api docker phoenix

install:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[api,dev]"

test:
	pytest -q

lint:
	ruff check src tests

eval:
	agentctl-px eval --mode local

eval-phoenix:
	agentctl-px eval --mode phoenix

ask:
	agentctl-px ask "My VPN keeps disconnecting when I work from home. How do I fix it?"

chat:
	agentctl-px chat --agent it_helpdesk

api:
	uvicorn phoenix_agents.api.app:app --reload --port 8000

docker:
	docker compose up --build

phoenix:
	bash scripts/start_phoenix_local.sh

push-dataset:
	agentctl-px push-dataset
