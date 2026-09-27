#!/usr/bin/env bash
set -euo pipefail

token="${ASSISTANT_API_TOKEN:-}"
if [ -z "$token" ]; then
  token_file="${ASSISTANT_DATA_DIR:-/app/data}/api_token.txt"
  [ -s "$token_file" ] || exit 1
  token="$(tr -d '[:space:]' < "$token_file")"
fi
curl -fsS --max-time 4 -H "X-Assistant-Token: ${token}" \
  "http://127.0.0.1:${ASSISTANT_PORT:-8756}/api/status" > /dev/null
