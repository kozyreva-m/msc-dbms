-- Задание 3. Кодеки и порядок значений

DROP TABLE IF EXISTS takt.hw_codec_mixed;
DROP TABLE IF EXISTS takt.hw_codec_ordered;

CREATE TABLE takt.hw_codec_ordered
(
    event_no       UInt64,
    t_zstd         DateTime('UTC') CODEC(ZSTD(1)),
    t_delta        DateTime('UTC') CODEC(Delta, ZSTD(1)),
    t_double_delta DateTime('UTC') CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY event_no
SETTINGS
    index_granularity = 8192,
    index_granularity_bytes = 0,
    min_bytes_for_wide_part = 0,
    min_rows_for_wide_part = 0;

CREATE TABLE takt.hw_codec_mixed
AS takt.hw_codec_ordered
ENGINE = MergeTree
ORDER BY (cityHash64(event_no), event_no)
SETTINGS
    index_granularity = 8192,
    index_granularity_bytes = 0,
    min_bytes_for_wide_part = 0,
    min_rows_for_wide_part = 0;

INSERT INTO takt.hw_codec_ordered
SELECT
    number,
    toDateTime('2026-10-20 00:00:00', 'UTC')
        + toIntervalSecond(number) AS event_time,
    event_time,
    event_time
FROM numbers(500000);

INSERT INTO takt.hw_codec_mixed
SELECT * FROM takt.hw_codec_ordered;

OPTIMIZE TABLE takt.hw_codec_ordered FINAL;
OPTIMIZE TABLE takt.hw_codec_mixed FINAL;

-- Контроль данных
WITH toDateTime('2026-10-20 00:00:00', 'UTC') AS base
SELECT
    source,
    count() AS rows_count,
    uniqExact(event_no) AS unique_ids,
    min(event_no) AS first_id,
    max(event_no) AS last_id,
    countIf(
        t_zstd != base + toIntervalSecond(event_no)
        OR t_delta != t_zstd
        OR t_double_delta != t_zstd
    ) AS bad_rows
FROM
(
    SELECT 'ordered' AS source, * FROM takt.hw_codec_ordered
    UNION ALL
    SELECT 'mixed' AS source, * FROM takt.hw_codec_mixed
)
GROUP BY source
ORDER BY source;

-- 3.2 Соседние значения (mixed)
SELECT
    event_no,
    t_zstd,
    toInt64(toUnixTimestamp(t_zstd))
      - toInt64(toUnixTimestamp(toDateTime('2026-10-20 00:00:00', 'UTC'))) AS seconds_from_start
FROM takt.hw_codec_mixed
ORDER BY cityHash64(event_no), event_no
LIMIT 6;

-- 3.2 То же для ordered (ORDER BY event_no)
SELECT
    event_no,
    t_zstd,
    toInt64(toUnixTimestamp(t_zstd))
      - toInt64(toUnixTimestamp(toDateTime('2026-10-20 00:00:00', 'UTC'))) AS seconds_from_start
FROM takt.hw_codec_ordered
ORDER BY event_no
LIMIT 6;

-- 3.3 Размеры колонок
SELECT
    table,
    column,
    sum(column_data_uncompressed_bytes) AS uncompressed_bytes,
    sum(column_data_compressed_bytes) AS compressed_bytes,
    round(
        sum(column_data_uncompressed_bytes)
        / nullIf(sum(column_data_compressed_bytes), 0),
        2
    ) AS compression_ratio
FROM system.parts_columns
WHERE database = 'takt'
  AND active
  AND table IN ('hw_codec_ordered', 'hw_codec_mixed')
  AND column IN ('t_zstd', 't_delta', 't_double_delta')
GROUP BY table, column
ORDER BY table, column;