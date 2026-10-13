#!/usr/bin/env bash
# Import the workflows into the n8n container started by `docker compose up -d`.
#   bash scripts/import_workflows.sh        demo mode: shared error handler + the 3 demo workflows, activated (needs no accounts)
#   bash scripts/import_workflows.sh prod   shared error handler + the 3 production workflows, left inactive until you add credentials
#   bash scripts/import_workflows.sh all    both sets
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows would otherwise rewrite the /workflows paths
cd "$(dirname "$0")/.."
MODE="${1:-demo}"
PORT="${N8N_HOST_PORT:-5679}"
n8n() { docker compose exec -T n8n n8n "$@"; }

echo "Waiting for n8n..."
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null && break || sleep 2; done

# /workflows/*.json = 00-error-handler + the three production workflows, /workflows/demo/*.json = the demo variants
case "$MODE" in
  demo) n8n import:workflow --input=/workflows/00-error-handler.json ;;
  prod | all) n8n import:workflow --separate --input=/workflows/ ;;
  *) echo "usage: $0 [demo|prod|all]" >&2; exit 1 ;;
esac
if [ "$MODE" != prod ]; then
  n8n import:workflow --separate --input=/workflows/demo/
  # Webhooks only answer for active workflows. The CLI change is picked up on restart.
  for id in n8nAiDemoTriage0 n8nAiDemoSupport n8nAiDemoLeads00; do
    n8n update:workflow --id="$id" --active=true
  done
  since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  docker compose restart n8n
  # /healthz answers before the active workflows are registered, so wait for the activation lines in the log
  for _ in $(seq 1 60); do
    [ "$(docker compose logs --since "$since" n8n 2>&1 | grep -c 'Activated workflow')" -ge 3 ] && break || sleep 2
  done
fi
echo "Done. Editor: http://127.0.0.1:$PORT  | demo webhooks: http://127.0.0.1:$PORT/webhook/demo/..."
