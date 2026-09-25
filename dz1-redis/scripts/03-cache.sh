#!/usr/bin/env bash
# Сценарий 3: Cache-Aside. Первый запрос даёт промах, второй попадание, у кеша есть TTL.

source "$(dirname "$0")/common.sh"

MASTER="$(current_master_container)"

step "Сбрасываем кеш, чтобы начать с промаха"
redis_cli "$MASTER" DEL cache:player:1001

step "Первый запрос: source = redis-hash (cache miss)"
api GET /api/players/1001

step "TTL кеша: около 60 секунд"
redis_cli "$MASTER" TTL cache:player:1001

step "Второй запрос: source = cache (cache hit)"
api GET /api/players/1001

step "Обновление уровня инвалидирует кеш"
api PATCH /api/players/1001/level '{"delta":1}'
redis_cli "$MASTER" EXISTS cache:player:1001

step "После обновления снова промах"
api GET /api/players/1001
