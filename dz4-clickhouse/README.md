# ДЗ 4. ClickHouse, TAKT

Стенд и ответы по заданиям 1-4. БД `takt`, логин `student`, пароль `takt`, версия 25.8.33.6.

## Запуск

`listening_events.csv.gz` (10 млн строк) в `data/` рядом с `compose.yaml`, не распаковывать. В репо gzip нет. У себя обычная копия из LMS: на Mac с Podman симлинк в эту папку в контейнере не открывается.

```sh
docker compose up -d --wait
# у меня podman-compose up -d
```

Дальше [http://localhost:8123/play](http://localhost:8123/play), встроенный редактор SQL. Скрипты: `00_prepare_source.sql`, потом `sql/01` - `04`. В prepare команды по одной, иначе можно продублировать INSERT.

В конце prepare: 10 000 000 строк, даты 13-26.10.2026 UTC.

## 1. Отчёт по странам

`sql/01_report.sql`: окно `[2026-10-20, 2026-10-27)`, короткое это `played_seconds < 20`.

Итог в `results/01_report_countries.tsv`. RU: 2 771 858 событий, 653 114 короче 20 с, доля 23,56%.

Контроль на `VALUES` (второй запрос в файле):

| country | events_total | events_under_20 | under_20_percent |
|---------|-------------|-----------------|------------------|
| RU | 3 | 1 | 33.33 |
| KZ | 2 | 1 | 50.00 |

Границы периода: с 20.10 00:00, до 27.10 не включая. Ровно 20 секунд в `<20` не попадает, в условии строго меньше.

Ответ: отчёт считает события (строки), не `uniq(user_id)`. В контроле у KZ один `user_id` и два плея, 50% коротких по событиям. Доля слушателей с коротким прослушиванием была бы другой метрикой и другим запросом.

## 2. ORDER BY и чтение

Одни и те же 10 млн строк, две таблицы с разным ключом сортировки (порядок на диске, от него зависит объём чтения):

- `hw_events_time`, `ORDER BY (ended_at)`
- `hw_events_country`, `ORDER BY (country, ended_at)`

В `sql/02_order_by.sql`. Read rows / Read bytes из `/play`, копия в `results/02_read_stats.tsv`. Granules: сколько кусков из 1221 задели (EXPLAIN indexes = 1).

| Запрос | Таблица | Granules | Read rows | Read bytes |
|--------|---------|----------|-----------|------------|
| DE | hw_events_time | 102/1221 | 835584 | 15040512 |
| DE | hw_events_country | 8/1221 | 65536 | 1179648 |
| все страны | hw_events_time | 102/1221 | 835584 | 15040512 |
| все страны | hw_events_country | 114/1221 | 931456 | 16766208 |

SELECT по DE за 24.10 на обеих таблицах один и тот же (59 423, 24,96%). Меняется только чтение с диска.

Страна + день: с `country` в ключе чтение сильно меньше (DE, 8 vs 102 гранул). Все страны за сутки чуть выгоднее на чистом `ended_at`. На `hw_events_time` DE и все страны читают одинаково: страну отсекли при агрегации.

## 3. Кодеки

`sql/03_codecs.sql`: 500k таймстемпов, ordered (время подряд) и mixed (перемешанный порядок в ключе).

Delta/DoubleDelta нормально жмут, когда соседние значения меняются ровно (0, 1, 2, 3). В mixed соседи в файле далёкие числа (36993, 222135 и т.д.), Delta почти не помогает.

`results/03_codecs_sizes.tsv`:

| table | column | compressed_bytes |
|-------|--------|------------------|
| ordered | t_double_delta | 2325 |
| ordered | t_delta | 2234 |
| ordered | t_zstd | 1332284 |
| mixed | t_zstd | 1543831 |
| mixed | t_delta | 1586160 |
| mixed | t_double_delta | 1962850 |

На ordered Delta сильно лучше одного ZSTD, на mixed нет. Узкая колонка сама по себе не делает быстрыми запросы из задания 2, там важнее ORDER BY.

## 4. Материализованное представление

INSERT в `hw_mv_events` дописывает агрегат в `hw_country_hourly` (SummingMergeTree). Старые строки MV не пересчитывает, историю залили `INSERT SELECT` в target. Сверка из `04_mv.sql`: 0 расхождений.

Порции А и Б в конце файла. Отчёт 27.10 19-21 считает и датасет за эти часы, и тестовые VALUES.

- после А: `results/04_mv_report_after_a.tsv`
- после Б: `results/04_mv_report_after_b.tsv`

Поздний INSERT 24.10 12:34 сдвинул бакет 12:00 по RU. Один прогон А+Б даёт `count()` 10 000 008 на источнике; повторные INSERT при отладке портят число.

Читать target с `sum()` и `GROUP BY`. Долю `<10` с одного счётчика `<20` не посчитать, нужны сырые `played_seconds` или отдельные поля.

https://github.com/kozyreva-m/msc-dbms/tree/dz4-clickhouse/dz4-clickhouse