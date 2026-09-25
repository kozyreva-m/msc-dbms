#!/usr/bin/env bash
# Сценарий 4: уведомление попадает в поток, потребитель читает и подтверждает.

source "$(dirname "$0")/common.sh"

MASTER="$(current_master_container)"

step "Длина потока до обновления"
redis_cli "$MASTER" XLEN notifications

step "Повышаем уровень Bob, в поток уходит уведомление (XADD)"
api PATCH /api/players/1002/level '{"delta":1}'

step "Длина потока выросла"
redis_cli "$MASTER" XLEN notifications

step "Последнее сообщение в потоке"
redis_cli "$MASTER" XREVRANGE notifications + - COUNT 1

sleep 1

step "Потребитель прочитал и подтвердил (XREADGROUP + XACK)"
run "$CLI" logs --tail 5 gamehub-consumer

step "Неподтверждённых сообщений в группе: 0"
redis_cli "$MASTER" XPENDING notifications notifications-group
