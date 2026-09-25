# ДЗ 1. GameHub на Redis

Бэкенд для игровой платформы: профили игроков, счётчик входов, лидерборд, достижения и уведомления.
Все данные хранятся в Redis.

## Из чего состоит

Redis запущен в Docker Compose так же, как на семинаре.

`redis-master` это мастер, он принимает все записи. Его настройки лежат в `redis.conf`: включены RDB и AOF,
лимит памяти 256 МБ с политикой `volatile-lru`, защита от split-brain (`min-replicas-to-write 1`,
`min-replicas-max-lag 10`).

`redis-replica-1` и `redis-replica-2` это реплики мастера, они только читают. Настроены флагами в
`docker-compose.yml`: `--replicaof redis-master 6379 --replica-read-only yes`. Лимиты и защита от split-brain
у них такие же, как у мастера, потому что после failover реплика сама становится мастером.

`sentinel-1`, `sentinel-2` и `sentinel-3` следят за мастером, кворум 2. Если мастер не отвечает 5 секунд,
Sentinel переключают его роль на одну из реплик. У каждого Sentinel свой файл конфига: `sentinel1.conf`,
`sentinel2.conf`, `sentinel3.conf`. Это копии `sentinel.conf`, как на семинаре.

`redis-insight` показывает данные в браузере, порт 5540.

Приложение написано на Node.js (Express и ioredis) и лежит в папке `app`. Контейнер `gamehub-app` отвечает
на запросы к API. Адрес мастера приложение не знает и спрашивает его у Sentinel, поэтому после failover
само переподключается к новому мастеру. Контейнер `gamehub-consumer` читает уведомления из потока
`notifications`, печатает их и подтверждает.

## Как запустить

Команды выполняются из папки `dz1-redis`:

```bash
docker compose up -d --build
docker compose ps
```

Для Podman всё то же самое, только вместо `docker` пишется `podman`. На macOS перед этим нужно запустить
виртуальную машину: `podman machine start`.

Примерно через 20 секунд все контейнеры будут в статусе `Up`.

Остановить и удалить данные:

```bash
docker compose down -v
```

Порты: API 3000, мастер 6379, реплики 6380 и 6381, Sentinel 26379, 26380 и 26381, Redis Insight 5540.

## Где какие данные

- Профиль игрока: Hash `player:{id}` с полями `name`, `level`, `region`, `created_at`.
- Счётчик входов: String `logins:{id}`, живёт 24 часа. Его увеличивает Lua-скрипт, в котором `INCR` и `EXPIRE`
  выполняются вместе, поэтому счётчик не останется без срока жизни.
- Кеш профиля: String `cache:player:{id}` с JSON профиля, живёт 60 секунд.
- Лидерборд: Sorted Set `tournament:main`, в нём игроки и их очки.
- Достижения: Set `achievements:{id}`.
- Уведомления: Stream `notifications` с полями `player_id`, `type`, `message`, `timestamp`. Сообщения старше
  7 дней удаляются при каждой новой записи.

## API

- `POST /api/players/{id}` создаёт или обновляет профиль. Тело: `{"name": "Alice", "level": 5, "region": "EU"}`.
  Делает `HSET`, удаляет кеш и отправляет уведомление.
- `GET /api/players/{id}` возвращает профиль. Сначала смотрит в кеш, а если там пусто, читает Hash и кладёт
  его в кеш на 60 секунд. Поле `source` в ответе показывает, откуда взяты данные: `cache` или `redis-hash`.
- `PATCH /api/players/{id}/level` меняет уровень. Тело: `{"delta": 1}`. Делает `HINCRBY`, удаляет кеш
  и отправляет уведомление.
- `POST /api/players/{id}/login` отмечает вход игрока.
- `POST /api/leaderboard/score` добавляет очки. Тело: `{"playerId": "1001", "score": 150}`.
- `GET /api/leaderboard/top?limit=10` возвращает топ игроков.
- `GET /api/leaderboard/rank/{playerId}` возвращает место игрока. В поле `zrank` лежит результат `ZRANK`
  (считается с нуля от худшего игрока), а в поле `place` привычное место сверху.
- `POST /api/players/{id}/achievements` добавляет достижение. Тело: `{"name": "sniper"}`.
- `GET /api/players/{id}/achievements/{name}` проверяет, есть ли у игрока достижение.
- `GET /api/players/{id1}/achievements/common/{id2}` возвращает общие достижения двух игроков.
- `POST /api/players/batch?compare=true` создаёт сразу 20 профилей через pipeline. В ответе видно, сколько
  времени это заняло с pipeline и без него.

Пример:

```bash
curl -X POST localhost:3000/api/players/1001 -H 'Content-Type: application/json' \
  -d '{"name":"Alice","level":5,"region":"EU"}'
curl localhost:3000/api/players/1001
```

## Демонстрация

Каждый сценарий запускается отдельным скриптом, который печатает команды перед выполнением.

1. `bash scripts/01-status.sh`: контейнеры запущены, у мастера 2 реплики, Sentinel видит мастер.
2. `bash scripts/02-api.sh`: профили, уровень, входы, лидерборд, достижения.
3. `bash scripts/03-cache.sh`: первый запрос идёт мимо кеша, второй берётся из кеша, виден TTL.
4. `bash scripts/04-stream.sh`: уведомление попадает в поток, потребитель его читает и подтверждает.
5. `bash scripts/05-failover.sh`: мастер останавливается, Sentinel назначает новый, приложение продолжает работать.
6. `bash scripts/06-split-brain.sh`: реплики на паузе, мастер отказывается принимать записи.
7. `bash scripts/07-pipeline.sh`: 20 профилей через pipeline.

Перед повторным прогоном стенд лучше перезапустить с нуля: `docker compose down -v && docker compose up -d --build`.

## Самопроверка

Скрипт `dz1_check.py` запускается на чистом стенде, до сценария failover:

```bash
docker compose down -v && docker compose up -d --build
bash scripts/02-api.sh && bash scripts/04-stream.sh && bash scripts/07-pipeline.sh && bash scripts/03-cache.sh
python3 dz1_check.py
```
