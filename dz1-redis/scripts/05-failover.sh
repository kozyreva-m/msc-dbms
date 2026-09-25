#!/usr/bin/env bash
# Сценарий 5: мастер падает, Sentinel переключает роль на реплику, приложение работает дальше.

source "$(dirname "$0")/common.sh"

MASTER="$(current_master_container)"

step "Текущий мастер по мнению Sentinel"
sentinel_master

step "Останавливаем мастер ($MASTER)"
run "$CLI" stop "$MASTER"

step "Ждём, пока Sentinel выберет нового мастера"
BEFORE="$(sentinel_master)"
for second in $(seq 1 60); do
  sleep 1
  NOW="$("$CLI" exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster | paste -sd ':' -)"
  echo "  ${second} c: мастер = $NOW"
  if [ "$NOW" != "$BEFORE" ]; then
    echo "  Sentinel переключил мастера за ${second} c"
    break
  fi
done

NEW_MASTER="$(current_master_container)"
step "Новый мастер: $NEW_MASTER, у него роль master"
redis_cli "$NEW_MASTER" INFO replication

step "Приложение продолжает работать: запись и чтение"
api POST /api/leaderboard/score '{"playerId":"1001","score":10}'
api GET "/api/leaderboard/top?limit=3"

step "Возвращаем старый мастер, Sentinel сделает его репликой"
run "$CLI" start "$MASTER"
for second in $(seq 1 30); do
  sleep 1
  ROLE="$("$CLI" exec "$MASTER" redis-cli INFO replication 2>/dev/null | tr -d '\r' | grep '^role:' || true)"
  echo "  ${second} c: $MASTER $ROLE"
  [ "$ROLE" = "role:slave" ] && break
done
redis_cli "$MASTER" INFO replication | head -5 || true
