// Имена ключей и константы собраны в одном месте, чтобы не опечататься в разных файлах.

const keys = {
  player: (id) => `player:${id}`,
  playerCache: (id) => `cache:player:${id}`,
  logins: (id) => `logins:${id}`,
  achievements: (id) => `achievements:${id}`,
  leaderboard: "tournament:main",
  notifications: "notifications",
};

const CACHE_TTL_SECONDS = 60;
const LOGINS_TTL_SECONDS = 24 * 60 * 60;
const NOTIFICATIONS_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const NOTIFICATIONS_GROUP = "notifications-group";

module.exports = {
  keys,
  CACHE_TTL_SECONDS,
  LOGINS_TTL_SECONDS,
  NOTIFICATIONS_RETENTION_MS,
  NOTIFICATIONS_GROUP,
};
