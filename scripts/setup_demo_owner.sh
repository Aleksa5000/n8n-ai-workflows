#!/usr/bin/env bash
# Optional: create the owner account of the LOCAL demo n8n so you can open the editor straight away.
# Reads DEMO_OWNER_EMAIL / DEMO_OWNER_PASSWORD from .env (or .env.example). For a real deployment create your own owner in the browser instead.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
. "$([ -f .env ] && echo .env || echo .env.example)"
set +a
curl -fsS -X POST "http://127.0.0.1:${N8N_HOST_PORT:-5679}/rest/owner/setup" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$DEMO_OWNER_EMAIL\",\"firstName\":\"Demo\",\"lastName\":\"Owner\",\"password\":\"$DEMO_OWNER_PASSWORD\"}" >/dev/null
echo "Owner created. Log in at http://127.0.0.1:${N8N_HOST_PORT:-5679} with $DEMO_OWNER_EMAIL"
