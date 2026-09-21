# Minimal, non-root image for running evaluations in CI runners, Azure Container Apps Jobs or Kubernetes CronJobs.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

ARG EXTRAS="azure,otel"
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[${EXTRAS}]"

COPY config ./config
COPY examples ./examples
RUN useradd --create-home --uid 10001 evaluator && mkdir -p /app/reports && chown -R evaluator /app/reports
USER evaluator

ENV PYTHONPATH=/app AGENTIC_EVAL_JUDGE=mock
ENTRYPOINT ["agentic-eval"]
CMD ["run", "--config", "config/eval_config.yaml", \
     "--dataset", "examples/enterprise_it_service_desk/dataset.jsonl", \
     "--target", "examples.enterprise_it_service_desk.agents:run_service_desk", \
     "--output-dir", "reports"]
