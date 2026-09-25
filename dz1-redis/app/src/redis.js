// Подключение к Redis через Sentinel.
// Приложение не знает адрес мастера: оно спрашивает его у Sentinel,
// а после failover ioredis сам переподключается к новому мастеру.

const fs = require("fs");
const path = require("path");
const Redis = require("ioredis");

const MASTER_NAME = process.env.MASTER_NAME || "mymaster";

// "sentinel-1:26379,sentinel-2:26379" -> [{ host, port }, ...]
const SENTINELS = (process.env.SENTINELS || "localhost:26379")
  .split(",")
  .map((address) => {
    const [host, port] = address.trim().split(":");
    return { host, port: Number(port) };
  });

// role: "master" для записи, "slave" для чтения с реплики.
// blocking: true для потребителя, который ждёт сообщения через BLOCK,
// ему нельзя ставить таймаут на команду.
function createClient({ role = "master", blocking = false } = {}) {
  const client = new Redis({
    sentinels: SENTINELS,
    name: MASTER_NAME,
    role,
    connectTimeout: 5000,
    commandTimeout: blocking ? undefined : 5000,
    maxRetriesPerRequest: blocking ? null : 5,
    // Сразу узнаём о смене мастера по событию +switch-master от Sentinel.
    failoverDetector: true,
    // Пауза между попытками переподключения растёт до 5 секунд.
    sentinelRetryStrategy: (attempt) => Math.min(attempt * 500, 5000),
    retryStrategy: (attempt) => Math.min(attempt * 500, 5000),
    // Бывший мастер после failover отвечает READONLY, поэтому переподключаемся
    // и снова спрашиваем у Sentinel, кто теперь мастер.
    reconnectOnError: (error) => (error.message.startsWith("READONLY") ? 2 : false),
  });

  client.on("error", (error) => {
    console.error(`[redis:${role}] ${error.message}`);
  });
  client.on("ready", () => {
    const address = client.stream ? `${client.stream.remoteAddress}:${client.stream.remotePort}` : "?";
    console.log(`[redis:${role}] подключились к ${address}`);
  });

  return client;
}

// Проверка соединения при старте: ждём, пока Redis ответит на PING.
async function waitForRedis(client, label, attempts = 30) {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      await client.ping();
      console.log(`[${label}] Redis отвечает на PING`);
      return;
    } catch (error) {
      console.log(`[${label}] Redis пока недоступен (${attempt}/${attempts}): ${error.message}`);
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  throw new Error(`[${label}] не удалось подключиться к Redis`);
}

// Регистрирует Lua-скрипт как команду client.recordLogin(key, ttl).
function defineScripts(client) {
  client.defineCommand("recordLogin", {
    numberOfKeys: 1,
    lua: fs.readFileSync(path.join(__dirname, "lua", "record-login.lua"), "utf8"),
  });
}

module.exports = { createClient, waitForRedis, defineScripts };
