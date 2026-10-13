#!/usr/bin/env bash
# Sends every sample payload to the demo webhooks and prints what came back, then what the mock services recorded.
# Needs the demo stack running (docker compose up -d) and the workflows imported (scripts/import_workflows.sh).
set -uo pipefail
cd "$(dirname "$0")"
N8N="http://127.0.0.1:${N8N_HOST_PORT:-5679}/webhook/demo"
MOCK="http://127.0.0.1:${MOCK_HOST_PORT:-8795}"
RUN="$(date +%s)" # makes lead emails unique, because the lead workflow ignores repeat emails for DEDUPE_WINDOW_MIN minutes

post() { # post <path> <file> [unique-email]
  local body
  body="$(cat "$2")"
  [ "${3:-}" = unique ] && body="$(echo "$body" | sed "s/\"email\": \"\([^@\"]*\)@/\"email\": \"\1+$RUN@/")"
  printf '\n### POST %s  (%s)\n' "$1" "$2"
  curl -s -w '\n[HTTP %{http_code}]\n' -X POST "$N8N/$1" -H 'Content-Type: application/json' -d "$body"
}

curl -s -X POST "$MOCK/admin/reset" >/dev/null

echo "===== 1. Gmail triage (fake classifier) ====="
for f in email-urgent email-billing email-newsletter email-bad-model-output; do post email-triage $f.json; done
printf '\n### GET triage-summary\n'; curl -s -w '\n[HTTP %{http_code}]\n' "$N8N/triage-summary"

echo; echo "===== 2. Support chatbot (mock knowledge base) ====="
for f in chat-refund chat-unknown chat-invalid; do post support-chat $f.json; done

echo; echo "===== 3. Lead intake (mock CRM) ====="
post lead-intake lead-hot.json unique
post lead-intake lead-hot.json unique   # same email again: answered with {"status":"duplicate"}, no second contact
for f in lead-spam lead-invalid lead-scoring-fails; do post lead-intake $f.json unique; done

echo; echo "===== What the mock services recorded ====="
curl -s "$MOCK/state"; echo
echo "--- Slack messages"; curl -s "$MOCK/slack/messages" | python3 -c 'import sys,json; [print("-", m["channel"], "|", m["text"].replace(chr(10), " / ")[:160]) for m in json.load(sys.stdin)]' 2>/dev/null || curl -s "$MOCK/slack/messages"
echo "--- Gmail drafts (never sent)"; curl -s "$MOCK/gmail/drafts"; echo
echo "--- CRM contacts"; curl -s "$MOCK/crm/v3/objects/contacts"; echo
