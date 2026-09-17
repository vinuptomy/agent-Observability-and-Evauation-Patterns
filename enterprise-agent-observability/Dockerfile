# ---------- build stage ----------
FROM python:3.12-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --prefix=/install ".[api]"

# ---------- runtime stage ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LOG_FORMAT=json
WORKDIR /app
COPY --from=build /install /usr/local
COPY configs ./configs
# Non-root user (container security baseline)
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/reports && chown -R appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "enterprise_agents.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
