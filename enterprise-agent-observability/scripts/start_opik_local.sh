#!/usr/bin/env bash
# Starts a self-hosted Opik stack locally (requires Docker + git).
# Official docs: https://www.comet.com/docs/opik/self-host/local_deployment
set -euo pipefail
OPIK_DIR="${OPIK_DIR:-$HOME/opik}"
if [ ! -d "$OPIK_DIR" ]; then
  git clone --depth 1 https://github.com/comet-ml/opik.git "$OPIK_DIR"
fi
cd "$OPIK_DIR"
./opik.sh
echo "Opik UI: http://localhost:5173  (set OPIK_USE_LOCAL=true in .env)"
