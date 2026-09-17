.PHONY: install test lint eval eval-opik ask chat api docker opik

install:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[api,dev]"

test:
	pytest -q

lint:
	ruff check src tests

eval:
	agentctl eval --mode local

eval-opik:
	agentctl eval --mode opik

ask:
	agentctl ask "My VPN keeps disconnecting when I work from home. How do I fix it?"

chat:
	agentctl chat --agent it_helpdesk

api:
	uvicorn enterprise_agents.api.app:app --reload --port 8000

docker:
	docker compose up --build

opik:
	bash scripts/start_opik_local.sh
