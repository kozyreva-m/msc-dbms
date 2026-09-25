// Потребитель уведомлений: читает поток notifications через группу,
// «обрабатывает» сообщение (печатает в консоль) и подтверждает его через XACK.

const { createClient, waitForRedis } = require("./redis");
const { ensureConsumerGroup } = require("./notifications");
const { keys, NOTIFICATIONS_GROUP } = require("./keys");

const CONSUMER_NAME = process.env.CONSUMER_NAME || "consumer-1";
const BLOCK_MS = 5000;
const BATCH_SIZE = 10;

// Отдельное соединение без таймаута на команду: XREADGROUP BLOCK ждёт сообщения до 5 секунд.
const client = createClient({ role: "master", blocking: true });

// Redis отдаёт поля сообщения плоским списком [ключ, значение, ключ, значение, ...].
function toObject(flatFields) {
  const result = {};
  for (let index = 0; index < flatFields.length; index += 2) {
    result[flatFields[index]] = flatFields[index + 1];
  }
  return result;
}

async function handleMessage(id, fields) {
  const notification = toObject(fields);
  const time = new Date(Number(notification.timestamp)).toISOString();
  console.log(`[notification ${id}] ${time} player=${notification.player_id} type=${notification.type}: ${notification.message}`);

  // XACK: сообщение обработано, из списка ожидающих (PEL) его можно убрать.
  await client.xack(keys.notifications, NOTIFICATIONS_GROUP, id);
}

// startId "0": сообщения, которые этот потребитель получил раньше, но не подтвердил (например, упал).
// startId ">": только новые сообщения, которые ещё никому в группе не выдавались.
async function readBatch(startId) {
  const response = await client.xreadgroup(
    "GROUP",
    NOTIFICATIONS_GROUP,
    CONSUMER_NAME,
    "COUNT",
    BATCH_SIZE,
    "BLOCK",
    BLOCK_MS,
    "STREAMS",
    keys.notifications,
    startId,
  );

  if (!response) {
    return 0;
  }

  const [[, messages]] = response;
  for (const [id, fields] of messages) {
    await handleMessage(id, fields);
  }
  return messages.length;
}

async function run() {
  await waitForRedis(client, "consumer");
  await ensureConsumerGroup(client);
  console.log(`[consumer] ${CONSUMER_NAME} ждёт уведомления в группе ${NOTIFICATIONS_GROUP}`);

  // Сначала дочитываем неподтверждённые хвосты, потом переходим к новым сообщениям.
  let pendingCount;
  do {
    pendingCount = await readBatch("0");
  } while (pendingCount > 0);

  for (;;) {
    try {
      await readBatch(">");
    } catch (error) {
      // Во время failover соединение рвётся, поэтому ждём секунду и пробуем снова.
      console.error(`[consumer] ошибка чтения: ${error.message}`);
      if (error.message.includes("NOGROUP")) {
        await ensureConsumerGroup(client).catch(() => {});
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
