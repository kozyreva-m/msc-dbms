-- Задание 1. Аналитический отчёт по странам
-- Период: [2026-10-20 00:00:00, 2026-10-27 00:00:00) UTC, порог played_seconds < 20

-- 1.1 Отчёт по основному набору (10 млн событий)
SELECT
    country,
    count() AS events_total,
    countIf(played_seconds < 20) AS events_under_20,
    round(100 * countIf(played_seconds < 20) / count(), 2) AS under_20_percent
FROM takt.listening_events
WHERE ended_at >= toDateTime('2026-10-20 00:00:00', 'UTC')
  AND ended_at <  toDateTime('2026-10-27 00:00:00', 'UTC')
GROUP BY country
ORDER BY country;

-- 1.2 Контроль на VALUES (тот же SELECT, другой источник после FROM)
SELECT
    country,
    count() AS events_total,
    countIf(played_seconds < 20) AS events_under_20,
    round(100 * countIf(played_seconds < 20) / count(), 2) AS under_20_percent
FROM values(
    'ended_at DateTime(\'UTC\'), country String, user_id UInt64, played_seconds UInt32',
    ('2026-10-19 23:59:59', 'RU', 101, 5),
    ('2026-10-20 00:00:00', 'RU', 101, 19),
    ('2026-10-22 12:00:00', 'RU', 101, 20),
    ('2026-10-26 23:59:59', 'RU', 102, 21),
    ('2026-10-27 00:00:00', 'RU', 103, 1),
    ('2026-10-21 10:00:00', 'KZ', 201, 5),
    ('2026-10-21 10:01:00', 'KZ', 201, 20)
)
WHERE ended_at >= toDateTime('2026-10-20 00:00:00', 'UTC')
  AND ended_at <  toDateTime('2026-10-27 00:00:00', 'UTC')
GROUP BY country
ORDER BY country;