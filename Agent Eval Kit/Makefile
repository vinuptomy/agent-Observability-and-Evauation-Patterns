.PHONY: install test lint eval eval-naive demo docker clean
PY ?= python3

install:     ; $(PY) -m pip install -e ".[dev]"
test:        ; $(PY) -m pytest -q
lint:        ; ruff check src tests examples
demo:        ; $(PY) -m examples.enterprise_it_service_desk.run_eval
eval:        ; agentic-eval run --config config/eval_config.yaml --dataset examples/enterprise_it_service_desk/dataset.jsonl --target examples.enterprise_it_service_desk.agents:run_service_desk
eval-naive:  ; agentic-eval run --config config/eval_config.yaml --dataset examples/enterprise_it_service_desk/dataset.jsonl --target examples.enterprise_it_service_desk.agents:run_service_desk_naive
docker:      ; docker build -t agentic-eval-kit . && docker run --rm -v $$PWD/reports:/app/reports agentic-eval-kit
clean:       ; rm -rf reports .pytest_cache .ruff_cache **/__pycache__ *.egg-info src/*.egg-info
