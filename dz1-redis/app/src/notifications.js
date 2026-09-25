// Очередь уведомлений на Redis Streams.

const { keys, NOTIFICATIONS_RETENTION_MS, NOTIFICATIONS_GROUP } = require("./keys");

// XGROUP CREATE notifications notifications-group $ MKSTREAM
// MKSTREAM создаёт поток, если его ещё нет. Повторный вызов даёт BUSYGROUP:
// это значит, что группа уже есть, и это нормально.
// Сразу после старта кластера реплики могут ещё не догнать мастер, и он
// отвечает NOREPLICAS (min-replicas-to-write 1). Тогда ждём и пробуем снова.
const GROUP_CREATE_ATTEMPTS = 30;
const GROUP_CREATE_RETRY_MS = 1000;

async function ensureConsumerGroup(client) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      await client.xgroup("CREATE", keys.notifications, NOTIFICATIONS_GROUP, "$", "MKSTREAM");
      console.log(`[stream] создана группа ${NOTIFICATIONS_GROUP}`);
      return;
    } catch (error) {
      if (error.message.includes("BUSYGROUP")) {
        return;
      }
      if (!error.message.includes("NOREPLICAS") || attempt >= GROUP_CREATE_ATTEMPTS) {
        throw error;
      }
      console.log(`[stream] реплики ещё не готовы, повтор ${attempt}/${GROUP_CREATE_ATTEMPTS}`);
      await new Promise((resolve) => setTimeout(resolve, GROUP_CREATE_RETRY_MS));
    }
  }
}

// XADD notifications MINID ~ <сейчас минус 7 дней> * player_id ... type ... message ... timestamp ...
// MINID удаляет из потока сообщения старше 7 дней при каждой новой записи.
// ID сообщения в Redis начинается с времени в миллисекундах, поэтому
// «ID меньше чем сейчас минус 7 дней» и означает «старше 7 дней».
async function publishNotification(client, { playerId, type, message }) {
  const now = Date.now();
  const oldestAllowedId = String(now - NOTIFICATIONS_RETENTION_MS);

  return client.xadd(
    keys.notifications,
    "MINID",
    "~",
    oldestAllowedId,
    "*",
    "player_id",
    playerId,
    "type",
    type,
    "message",
    message,
    "timestamp",
    String(now),
  );
}

module.exports = { ensureConsumerGroup, publishNotification };
