-- Скопировано из стенда LMS. Выполняйте по одной команде в http://localhost:8123/play
-- Пользователь student, пароль takt. Gzip: data/listening_events.csv.gz (10 000 000 строк)

CREATE DATABASE IF NOT EXISTS takt;

DROP TABLE IF EXISTS takt.listening_events;

CREATE TABLE takt.listening_events
(
    ended_at       DateTime('UTC') CODEC(Delta, ZSTD),
    user_id        UInt64,
    track_id       UInt64,
    country        String,
    platform       String,
    app_version    String,
    played_seconds UInt32,
    track_seconds  UInt32
)
ENGINE = MergeTree
ORDER BY ended_at;

INSERT INTO takt.listening_events
SELECT *
FROM file(
    'data/listening_events.csv.gz',
    'CSVWithNames',
    'ended_at DateTime(\'UTC\'), user_id UInt64, track_id UInt64, country String, platform String, app_version String, played_seconds UInt32, track_seconds UInt32'
);

SELECT version();
SELECT count() AS events, min(ended_at) AS first_event, max(ended_at) AS last_event
FROM takt.listening_events;