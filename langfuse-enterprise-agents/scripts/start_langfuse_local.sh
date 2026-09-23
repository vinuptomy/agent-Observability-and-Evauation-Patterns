#!/usr/bin/env bash
# Starts a self-hosted Langfuse stack locally (requires Docker + git).
# Official docs: https://langfuse.com/self-hosting/local
set -euo pipefail
LANGFUSE_DIR="${LANGFUSE_DIR:-$HOME/langfuse}"
if [ ! -d "$LANGFUSE_DIR" ]; then
  git clone --depth 1 https://github.com/langfuse/langfuse.git "$LANGFUSE_DIR"
fi
cd "$LANGFUSE_DIR"
docker compose up -d
cat <<'MSG'

Langfuse UI: http://localhost:3000
Next steps:
  1. Create an account and an organisation/project in the UI.
  2. Project settings -> API keys -> create a new key pair.
  3. Put them in .env:
       LANGFUSE_HOST=http://localhost:3000
       LANGFUSE_PUBLIC_KEY=pk-lf-...
       LANGFUSE_SECRET_KEY=sk-lf-...
MSG
