#!/usr/bin/env bash
# Общие настройки для демо-скриптов. Работает и с Docker, и с Podman.

set -euo pipefail

if command -v docker >/dev/null 2>&1; then
  CLI="docker"
  COMPOSE="docker compose"
else
  CLI="podman"
  COMPOSE="podman compose"
fi

API="${API:-http://localhost:3000}"
REDIS_NODES=(redis-master redis-replica-1 redis-replica-2)

step() {
  echo
  echo "=== $* ==="
}

run() {
  echo "\$ $*"
  "$@"
}

pretty() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    python3 -m json.tool
  fi
}

# curl с выводом метода и пути, тело ответа печатается красиво.
api() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  echo "\$ curl -X $method $API$path ${body:+-d '$body'}"
  if [ -n "$body" ]; then
    curl -s -X "$method" "$API$path" -H "Content-Type: application/json" -d "$body" | pretty
  else
    curl -s -X "$method" "$API$path" | pretty
  fi
}

redis_cli() {
  local container="$1"
  shift
  echo "\$ $CLI exec $container redis-cli $*"
  "$CLI" exec "$container" redis-cli "$@"
}

sentinel_master() {
  "$CLI" exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster | paste -sd ':' -
}

# Какой из трёх Redis сейчас мастер: у него в INFO replication стоит role:master.
current_master_container() {
  for node in "${REDIS_NODES[@]}"; do
    if "$CLI" exec "$node" redis-cli INFO replication 2>/dev/null | grep -q "role:master"; then
      echo "$node"
      return
    fi
  done
}
