-- Задание 4. Почасовой отчёт и материализованное представление

DROP VIEW IF EXISTS takt.hw_country_hourly_mv;
DROP TABLE IF EXISTS takt.hw_country_hourly;
DROP TABLE IF EXISTS takt.hw_mv_events;

CREATE TABLE takt.hw_mv_events
(
    ended_at       DateTime('UTC'),
    country        String,
    played_seconds UInt32
)
ENGINE = MergeTree
ORDER BY ended_at;

INSERT INTO takt.hw_mv_events
SELECT ended_at, country, played_seconds
FROM takt.listening_events
WHERE ended_at >= toDateTime('2026-10-13 00:00:00', 'UTC')
  AND ended_at <  toDateTime('2026-10-27 00:00:00', 'UTC');

CREATE TABLE takt.hw_country_hourly
(
    hour            DateTime('UTC'),
    country         String,
    events          UInt64,
    events_under_20 UInt64,
    total_seconds   UInt64
)
ENGINE = SummingMergeTree((events, events_under_20, total_seconds))
ORDER BY (hour, country);

SELECT count() AS source_events FROM takt.hw_mv_events;

-- 4.1 MV (инкрементальное, без POPULATE и без фильтра по периоду)
CREATE MATERIALIZED VIEW takt.hw_country_hourly_mv
TO takt.hw_country_hourly AS
SELECT
    toStartOfHour(ended_at) AS hour,
    country,
    count() AS events,
    countIf(played_seconds < 20) AS events_under_20,
    sum(played_seconds) AS total_seconds
FROM takt.hw_mv_events
GROUP BY hour, country;

SELECT count() AS stored_rows FROM takt.hw_country_hourly;

-- 4.2 Однократное заполнение истории (до первых контрольных INSERT)
INSERT INTO takt.hw_country_hourly
SELECT
    toStartOfHour(ended_at) AS hour,
    country,
    count() AS events,
    countIf(played_seconds < 20) AS events_under_20,
    sum(played_seconds) AS total_seconds
FROM takt.hw_mv_events
GROUP BY hour, country;

-- Общий контроль (ожидается 0 строк)
SELECT
    hour,
    country,
    sum(events_delta) AS events_diff,
    sum(short_delta) AS short_diff,
    sum(seconds_delta) AS seconds_diff
FROM
(
    SELECT
        toStartOfHour(ended_at) AS hour,
        country,
        toInt64(count()) AS events_delta,
        toInt64(countIf(played_seconds < 20)) AS short_delta,
        toInt64(sum(played_seconds)) AS seconds_delta
    FROM takt.hw_mv_events
    GROUP BY hour, country
    UNION ALL
    SELECT
        hour,
        country,
        -toInt64(events),
        -toInt64(events_under_20),
        -toInt64(total_seconds)
    FROM takt.hw_country_hourly
)
GROUP BY hour, country
HAVING events_diff != 0 OR short_diff != 0 OR seconds_diff != 0
ORDER BY hour, country;

-- 4.3 Отчёт по итогам (пример: 27 окт, 19:00–21:00)
SELECT
    hour,
    country,
    sum(events) AS events_total,
    sum(events_under_20) AS short_count,
    sum(total_seconds) AS seconds_sum,
    round(100 * sum(events_under_20) / sum(events), 2) AS under_20_percent,
    round(sum(total_seconds) / sum(events), 2) AS avg_seconds
FROM takt.hw_country_hourly
WHERE hour >= toDateTime('2026-10-27 19:00:00', 'UTC')
  AND hour <  toDateTime('2026-10-27 21:00:00', 'UTC')
GROUP BY hour, country
ORDER BY hour, country;

-- 4.5 Порция А (один раз)
INSERT INTO takt.hw_mv_events (ended_at, country, played_seconds)
VALUES
    ('2026-10-27 19:01:00', 'RU', 5),
    ('2026-10-27 19:02:00', 'RU', 19),
    ('2026-10-27 19:03:00', 'RU', 20),
    ('2026-10-27 19:04:00', 'RU', 40),
    ('2026-10-27 19:05:00', 'KZ', 25);

-- После А: снова отчёт 19–21 и общий контроль

-- 4.5 Порция Б (один раз)
INSERT INTO takt.hw_mv_events (ended_at, country, played_seconds)
VALUES
    ('2026-10-27 19:00:00', 'RU', 1),
    ('2026-10-27 20:00:00', 'RU', 10),
    ('2026-10-24 12:34:00', 'RU', 7);

-- После Б: отчёт, контроль, SELECT count() FROM takt.hw_mv_events; (ожидается 10_000_008)