#!/usr/bin/env bash
# Сценарий 6: защита от split-brain. Все реплики на паузе, и мастер отказывается принимать записи.

source "$(dirname "$0")/common.sh"

MASTER="$(current_master_container)"
REPLICAS=()
for node in "${REDIS_NODES[@]}"; do
  if [ "$node" != "$MASTER" ]; then
    REPLICAS+=("$node")
  fi
done

step "Настройки мастера ($MASTER)"
redis_cli "$MASTER" CONFIG GET min-replicas-to-write
redis_cli "$MASTER" CONFIG GET min-replicas-max-lag

step "Запись работает, пока реплики живы"
redis_cli "$MASTER" SET split-brain-check ok

step "Ставим на паузу все реплики: ${REPLICAS[*]}"
run "$CLI" pause "${REPLICAS[@]}"

step "Ждём, пока мастер перестанет считать реплики живыми (min-replicas-max-lag = 10 секунд)"
for second in $(seq 1 40); do
  sleep 1
  GOOD="$("$CLI" exec "$MASTER" redis-cli INFO replication | tr -d '\r' | grep '^min_slaves_good_slaves:' || true)"
  echo "  ${second} c: $GOOD"
  [ "$GOOD" = "min_slaves_good_slaves:0" ] && break
done

step "Запись напрямую в мастер: ожидаем NOREPLICAS"
redis_cli "$MASTER" SET split-brain-check fail || true

step "Запись через API: ожидаем 503"
api POST /api/leaderboard/score '{"playerId":"1001","score":1}'

step "Снимаем паузу с реплик"
run "$CLI" unpause "${REPLICAS[@]}"
sleep 3

step "Запись снова работает"
redis_cli "$MASTER" SET split-brain-check ok
