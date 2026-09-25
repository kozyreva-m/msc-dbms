// REST API GameHub.

const express = require("express");
const { createClient, waitForRedis, defineScripts } = require("./redis");
const { ensureConsumerGroup, publishNotification } = require("./notifications");
const { keys, CACHE_TTL_SECONDS, LOGINS_TTL_SECONDS } = require("./keys");

const PORT = Number(process.env.PORT || 3000);
const REGIONS = ["EU", "NA", "ASIA", "RU"];

// Два клиента: запись идёт на мастер, чтение лидерборда и достижений идёт с реплик.
const writer = createClient({ role: "master" });
const reader = createClient({ role: "slave" });
defineScripts(writer);

const app = express();
app.use(express.json());

// Express 4 не ловит ошибки из async-функций сам, эта обёртка передаёт их в обработчик ошибок.
const route = (handler) => (req, res, next) => handler(req, res).catch(next);

function badRequest(res, message) {
  return res.status(400).json({ error: message });
}

// Сразу после failover Sentinel несколько секунд числит упавший мастер среди реплик,
// и клиент чтения может подключиться к нему. Тогда читаем с мастера, чтобы API не падал.
async function readFromReplica(read) {
  try {
    return await read(reader);
  } catch (error) {
    console.error(`[redis:slave] чтение с реплики не удалось (${error.message}), читаем с мастера`);
    return read(writer);
  }
}

// Поля хеша player:{id}: name, level, region, created_at.
function playerFields({ name, level, region }, createdAt) {
  return { name, level: Number(level), region, created_at: createdAt };
}

// HGETALL возвращает все значения строками, уровень превращаем обратно в число.
function toProfile(id, hash) {
  return {
    id,
    name: hash.name,
    level: Number(hash.level),
    region: hash.region,
    created_at: Number(hash.created_at),
  };
}

// --- 7. Конвейеризация: массовое создание профилей ---
// Маршрут объявлен раньше /api/players/:id, иначе Express примет "batch" за id игрока.

app.post(
  "/api/players/batch",
  route(async (req, res) => {
    const players = Array.isArray(req.body.players)
      ? req.body.players
      : Array.from({ length: Number(req.body.count || 20) }, (_, index) => ({
          id: `batch-${index + 1}`,
          name: `Player ${index + 1}`,
          level: 1 + Math.floor(Math.random() * 50),
          region: REGIONS[index % REGIONS.length],
        }));

    if (players.length === 0) {
      return badRequest(res, "нужен непустой список players или count > 0");
    }

    const now = Date.now();

    // Pipeline: все команды уходят в Redis одной пачкой, ответы приходят тоже пачкой.
    // Без pipeline на каждую команду был бы отдельный сетевой запрос-ответ.
    const pipelineStart = process.hrtime.bigint();
    const pipeline = writer.pipeline();
    for (const player of players) {
      pipeline.hset(keys.player(player.id), playerFields(player, now));
    }
    // Ошибка отдельной команды не бросается сама, а лежит в результате: [[error, value], ...].
    const results = await pipeline.exec();
    const failed = results.find(([error]) => error);
    if (failed) {
      throw failed[0];
    }
    const pipelineMs = Number(process.hrtime.bigint() - pipelineStart) / 1e6;

    // Для сравнения по запросу ?compare=true записываем те же данные без pipeline,
    // каждой командой отдельно.
    let sequentialMs;
    if (req.query.compare === "true") {
      const sequentialStart = process.hrtime.bigint();
      for (const player of players) {
        await writer.hset(keys.player(player.id), playerFields(player, now));
      }
      sequentialMs = Number(process.hrtime.bigint() - sequentialStart) / 1e6;
    }

    res.status(201).json({
      created: players.length,
      commands: results.length,
      pipelineMs: Number(pipelineMs.toFixed(2)),
      sequentialMs: sequentialMs === undefined ? undefined : Number(sequentialMs.toFixed(2)),
    });
  }),
);

// --- 1. Профили игроков (Hash) ---

app.post(
  "/api/players/:id",
  route(async (req, res) => {
    const { id } = req.params;
    const { name, level, region } = req.body;

    if (!name || !region || !Number.isInteger(Number(level))) {
      return badRequest(res, "нужны поля name, region и целое level");
    }

    // HSET player:{id} name {name} level {level} region {region} created_at {timestamp}
    await writer.hset(keys.player(id), playerFields({ name, level, region }, Date.now()));
    // DEL cache:player:{id}: инвалидация кеша при обновлении профиля.
    await writer.del(keys.playerCache(id));

    await publishNotification(writer, {
      playerId: id,
      type: "profile_updated",
      message: `Профиль ${name} сохранён`,
    });

    const profile = toProfile(id, await writer.hgetall(keys.player(id)));
    res.status(201).json(profile);
  }),
);

// --- 5. Кеширование профилей (Cache-Aside + TTL) ---

app.get(
  "/api/players/:id",
  route(async (req, res) => {
    const { id } = req.params;

    // 1. Сначала смотрим в кеш.
    const cached = await writer.get(keys.playerCache(id));
    if (cached) {
      const ttl = await writer.ttl(keys.playerCache(id));
      res.set("X-Cache", "HIT");
      return res.json({ source: "cache", cacheTtl: ttl, profile: JSON.parse(cached) });
    }

    // 2. Кеш пуст, поэтому читаем хеш и кладём JSON в кеш на 60 секунд.
    const hash = await writer.hgetall(keys.player(id));
    if (Object.keys(hash).length === 0) {
      return res.status(404).json({ error: `игрок ${id} не найден` });
    }

    const profile = toProfile(id, hash);
    await writer.set(keys.playerCache(id), JSON.stringify(profile), "EX", CACHE_TTL_SECONDS);

    res.set("X-Cache", "MISS");
    res.json({ source: "redis-hash", cacheTtl: CACHE_TTL_SECONDS, profile });
  }),
);

app.patch(
  "/api/players/:id/level",
  route(async (req, res) => {
    const { id } = req.params;
    const delta = Number(req.body.delta);

    if (!Number.isInteger(delta)) {
      return badRequest(res, "нужно целое поле delta");
    }
    if (!(await writer.exists(keys.player(id)))) {
      return res.status(404).json({ error: `игрок ${id} не найден` });
    }

    // HINCRBY player:{id} level {delta} + DEL cache:player:{id}
    const newLevel = await writer.hincrby(keys.player(id), "level", delta);
    await writer.del(keys.playerCache(id));

    // 6. Уведомление о смене уровня уходит в поток notifications.
    const notificationId = await publishNotification(writer, {
      playerId: id,
      type: delta > 0 ? "level_up" : "level_down",
      message: `Уровень игрока ${id} изменился на ${delta}, теперь ${newLevel}`,
    });

    res.json({ id, level: Number(newLevel), notificationId });
  }),
);

// --- 2. Счётчик входов (String + INCR + Lua) ---

app.post(
  "/api/players/:id/login",
  route(async (req, res) => {
    const { id } = req.params;
    const logins = await writer.recordLogin(keys.logins(id), LOGINS_TTL_SECONDS);
    const ttl = await writer.ttl(keys.logins(id));
    res.json({ id, loginsToday: Number(logins), ttlSeconds: ttl });
  }),
);

// --- 3. Лидерборд турнира (Sorted Set) ---

app.post(
  "/api/leaderboard/score",
  route(async (req, res) => {
    const { playerId } = req.body;
    const score = Number(req.body.score);

    if (!playerId || !Number.isFinite(score)) {
      return badRequest(res, "нужны поля playerId и числовое score");
    }

    // ZINCRBY tournament:main {score} {player_id} прибавляет очки, создаёт игрока в рейтинге при первом вызове.
    const total = await writer.zincrby(keys.leaderboard, score, playerId);
    res.json({ playerId, score: Number(total) });
  }),
);

app.get(
  "/api/leaderboard/top",
  route(async (req, res) => {
    const limit = Math.min(Math.max(Number(req.query.limit || 10), 1), 100);

    // ZREVRANGE tournament:main 0 9 WITHSCORES: от большего числа очков к меньшему.
    const flat = await readFromReplica((client) =>
      client.zrevrange(keys.leaderboard, 0, limit - 1, "WITHSCORES"),
    );

    // Redis отдаёт плоский список [игрок, очки, игрок, очки, ...], собираем из него объекты.
    const top = [];
    for (let index = 0; index < flat.length; index += 2) {
      top.push({ place: index / 2 + 1, playerId: flat[index], score: Number(flat[index + 1]) });
    }
    res.json(top);
  }),
);

app.get(
  "/api/leaderboard/rank/:playerId",
  route(async (req, res) => {
    const { playerId } = req.params;

    // ZRANK считает от меньшего счёта (0 у худшего), ZREVRANK от большего (0 у лидера).
    const [zrank, zrevrank, score] = await readFromReplica((client) =>
      Promise.all([
        client.zrank(keys.leaderboard, playerId),
        client.zrevrank(keys.leaderboard, playerId),
        client.zscore(keys.leaderboard, playerId),
      ]),
    );

    if (zrank === null) {
      return res.status(404).json({ error: `игрока ${playerId} нет в лидерборде` });
    }
    res.json({ playerId, place: zrevrank + 1, zrank, zrevrank, score: Number(score) });
  }),
);

// --- 4. Достижения игроков (Set) ---

app.post(
  "/api/players/:id/achievements",
  route(async (req, res) => {
    const { id } = req.params;
    const { name } = req.body;

    if (!name) {
      return badRequest(res, "нужно поле name");
    }

    // SADD возвращает 1, если достижение новое, и 0, если оно уже было: множество хранит только уникальные.
    const added = await writer.sadd(keys.achievements(id), name);
    res.status(added ? 201 : 200).json({ id, achievement: name, added: added === 1 });
  }),
);

// Объявлен раньше /achievements/:name, чтобы "common" не приняли за название достижения.
app.get(
  "/api/players/:id/achievements/common/:otherId",
  route(async (req, res) => {
    const { id, otherId } = req.params;
    const common = await readFromReplica((client) =>
      client.sinter(keys.achievements(id), keys.achievements(otherId)),
    );
    res.json({ players: [id, otherId], common: common.sort() });
  }),
);

app.get(
  "/api/players/:id/achievements/:name",
  route(async (req, res) => {
    const { id, name } = req.params;
    const has = await readFromReplica((client) => client.sismember(keys.achievements(id), name));
    res.json({ id, achievement: name, has: has === 1 });
  }),
);

// --- Ошибки ---

app.use((error, req, res, next) => {
  // NOREPLICAS: мастер отклонил запись из-за min-replicas-to-write (защита от split-brain).
  if (error.message.includes("NOREPLICAS")) {
    return res.status(503).json({ error: "мастер не принимает записи: нет живых реплик", details: error.message });
  }
  console.error(error);
  res.status(500).json({ error: error.message });
});

async function start() {
  await waitForRedis(writer, "master");
  await waitForRedis(reader, "replica");
  await ensureConsumerGroup(writer);

  app.listen(PORT, () => {
    console.log(`GameHub API слушает порт ${PORT}`);
  });
}

start().catch((error) => {
  console.error(error);
  process.exit(1);
});
