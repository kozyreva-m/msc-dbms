#!/usr/bin/env bash
# Сценарий 1: система запущена, у мастера 2 реплики, Sentinel знает мастера.

source "$(dirname "$0")/common.sh"

step "Все контейнеры запущены"
run $COMPOSE ps

MASTER="$(current_master_container)"

step "INFO replication на мастере ($MASTER): ожидаем connected_slaves:2"
redis_cli "$MASTER" INFO replication

step "Sentinel: адрес текущего мастера"
echo "\$ $CLI exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster"
sentinel_master

step "Приложение подключилось к Redis через Sentinel"
"$CLI" logs gamehub-app 2>&1 | grep -E "подключились|PING|слушает" | tail -5
