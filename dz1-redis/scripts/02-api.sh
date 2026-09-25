#!/usr/bin/env bash
# Сценарий 2: профили, уровень, счётчик входов, лидерборд, достижения.

source "$(dirname "$0")/common.sh"

step "Создаём два профиля (HSET)"
api POST /api/players/1001 '{"name":"Alice","level":5,"region":"EU"}'
api POST /api/players/1002 '{"name":"Bob","level":3,"region":"NA"}'

step "Повышаем уровень Alice на 2 (HINCRBY + DEL кеша + XADD)"
api PATCH /api/players/1001/level '{"delta":2}'

step "Три входа Alice за день (Lua: INCR + EXPIRE 86400)"
api POST /api/players/1001/login
api POST /api/players/1001/login
api POST /api/players/1001/login
redis_cli "$(current_master_container)" GET logins:1001
redis_cli "$(current_master_container)" TTL logins:1001

step "Очки в лидерборд (ZINCRBY)"
api POST /api/leaderboard/score '{"playerId":"1001","score":150}'
api POST /api/leaderboard/score '{"playerId":"1002","score":90}'
api POST /api/leaderboard/score '{"playerId":"1003","score":210}'
api POST /api/leaderboard/score '{"playerId":"1002","score":40}'

step "Топ-10 (ZREVRANGE 0 9 WITHSCORES)"
api GET "/api/leaderboard/top?limit=10"

step "Место Alice (ZRANK / ZREVRANK)"
api GET /api/leaderboard/rank/1001

step "Достижения (SADD)"
api POST /api/players/1001/achievements '{"name":"first_blood"}'
api POST /api/players/1001/achievements '{"name":"sniper"}'
api POST /api/players/1001/achievements '{"name":"marathon"}'
api POST /api/players/1002/achievements '{"name":"sniper"}'
api POST /api/players/1002/achievements '{"name":"marathon"}'
api POST /api/players/1002/achievements '{"name":"collector"}'

step "Повторное добавление того же достижения ничего не меняет (added: false)"
api POST /api/players/1001/achievements '{"name":"sniper"}'

step "Есть ли у Alice достижение sniper? (SISMEMBER)"
api GET /api/players/1001/achievements/sniper
api GET /api/players/1001/achievements/collector

step "Общие достижения Alice и Bob (SINTER)"
api GET /api/players/1001/achievements/common/1002
