#!/usr/bin/env bash
# Push env vars from railway/<service>.env to the matching Railway service.
#
# Usage:
#   ./railway/push.sh api
#   ./railway/push.sh ingest-worker
#   ./railway/push.sh frontend
#   ./railway/push.sh all                    # push all three sequentially
#
#   ENV=production ./railway/push.sh api     # default; pass staging etc. if you have one
#
# Prereqs:
#   - railway CLI installed and `railway link` already run against this project.
#   - railway/<service>.env exists (copy from <service>.env.example and fill).
set -euo pipefail

cd "$(dirname "$0")"

ENVIRONMENT="${ENV:-production}"

push_one() {
  local service="$1"
  local file="${service}.env"

  if [[ ! -f "$file" ]]; then
    echo "✗ $service: railway/$file not found (copy from ${service}.env.example and fill)" >&2
    return 1
  fi

  local args=()
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    args+=(--set "$line")
  done < "$file"

  if [[ ${#args[@]} -eq 0 ]]; then
    echo "✗ $service: $file has no KEY=VALUE lines" >&2
    return 1
  fi

  echo "→ pushing ${#args[@]} vars to service=$service environment=$ENVIRONMENT"
  railway variables --service "$service" --environment "$ENVIRONMENT" "${args[@]}"
  echo "✓ $service done"
}

case "${1:-}" in
  api|ingest-worker|frontend)
    push_one "$1"
    ;;
  all)
    push_one api
    push_one ingest-worker
    push_one frontend
    ;;
  *)
    echo "usage: $0 {api|ingest-worker|frontend|all}" >&2
    exit 2
    ;;
esac
