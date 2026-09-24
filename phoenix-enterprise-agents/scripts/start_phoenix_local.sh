#!/usr/bin/env bash
# Starts a self-hosted Arize Phoenix instance locally.
# Docs: https://arize.com/docs/phoenix/self-hosting
set -euo pipefail

if command -v docker >/dev/null 2>&1; then
  docker run -d --name phoenix -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
else
  echo "Docker not found — falling back to the Python package (pip install arize-phoenix)"
  python -m phoenix.server.main serve &
fi

cat <<'MSG'

Phoenix UI:        http://localhost:6006
OTLP (HTTP):       http://localhost:6006/v1/traces
OTLP (gRPC):       http://localhost:4317

.env settings:
  PHOENIX_ENABLED=true
  PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
  PHOENIX_BASE_URL=http://localhost:6006
MSG
