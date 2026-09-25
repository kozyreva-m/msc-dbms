#!/usr/bin/env bash
# Сценарий 7: массовая загрузка 20 профилей через pipeline и сравнение с обычной записью.

source "$(dirname "$0")/common.sh"

step "20 профилей одной пачкой через pipeline, плюс те же команды по одной для сравнения"
api POST "/api/players/batch?compare=true" '{"count":20}'

step "Профили на месте"
redis_cli "$(current_master_container)" HGETALL player:batch-1
redis_cli "$(current_master_container)" HGETALL player:batch-20
