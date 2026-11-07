# -*- coding: utf-8 -*-
# Заготовка решения ДЗ_3 (Cassandra). Заполняйте места с TODO -
# остальное (стенд, контрольные данные, проверки) уже готово в lab.py.
# Служебный lab.py менять не нужно

import json
from datetime import datetime, timedelta

from cassandra.query import ConsistencyLevel

# База отсчёта времени событий: 2026-01-01T00:00:00Z. Важно: без таймзоны (UTC)
# драйвер возвращает timestamp без tzinfo, и сценарий data
# сравнивает прочитанные значения именно с наивной базой.
BASE_EVENT_TIME = datetime(2026, 1, 1)

# Типы событий: циклично по индексу i - login, purchase, view.
EVENT_TYPES = ['login', 'purchase', 'view']


def create_tables(session):
    # Для подзадачи 2 по сценарию data необходимо создать две таблицы
    # в keyspace hw3 - сессия уже подключена к нему.
    #
    # Написать два CQL-запроса CREATE TABLE и выполнить их через
    # session.execute(...).
    #
    # Структура для обеих таблиц - колонки и типы взять из таблицы
    # в разделе 2 Задания. PRIMARY KEY - (user_id, event_time);
    # порядок кластеризации - по убыванию event_time: в CREATE TABLE
    # после PRIMARY KEY добавить блок WITH CLUSTERING ORDER BY с
    # направлением DESC по event_time.
    #
    # user_actions - включить сжатие LZ4. Оно задаётся параметром
    # COMPRESSION в том же CREATE TABLE (через AND после блока
    # CLUSTERING ORDER BY), значением - словарь с указанием класса
    # компрессора.
    #
    # user_actions_none - та же структура, но сжатие отключено.
    # Отключается тем же параметром COMPRESSION; конкретный способ
    # найти в документации Cassandra - среди вариантов есть класс
    # NoCompressor.
    #
    # Таблица user_actions_none нужна только для сравнения размеров
    # SSTable в разделе 5.
    #
    # Сценарий data проверяет по system_schema: partition key, DESC
    # у event_time, настройки сжатия обеих таблиц.
    session.execute(
        "CREATE TABLE IF NOT EXISTS user_actions ("
        " user_id int,"
        " event_time timestamp,"
        " event_type text,"
        " payload text,"
        " PRIMARY KEY (user_id, event_time)"
        ") WITH CLUSTERING ORDER BY (event_time DESC)"
        " AND compression = {'class': 'LZ4Compressor'}"
    )
    session.execute(
        "CREATE TABLE IF NOT EXISTS user_actions_none ("
        " user_id int,"
        " event_time timestamp,"
        " event_type text,"
        " payload text,"
        " PRIMARY KEY (user_id, event_time)"
        ") WITH CLUSTERING ORDER BY (event_time DESC)"
        " AND compression = {'enabled': 'false'}"
    )
    return ['user_actions', 'user_actions_none']



def insert_events(session, table, user_id, n, consistency):
    # Для подзадач 3-4 по сценариям bulk и consistency необходимо
    # вставить n событий пользователя user_id в таблицу table
    # (сценарий передаёт и 'user_actions', и 'user_actions_none' -
    # обе должны получить данные).
    #
    # Дописать только CQL-запрос INSERT с плейсхолдерами ?;
    # порядок аргументов bind должен совпадать с порядком ? в запросе.
    # Уровень консистентности - на утверждении, не на сессии: сессия
    # у сценария consistency одна на все четыре замера.
    query = (
        f"INSERT INTO {table} (user_id, event_time, event_type, payload)"
        " VALUES (?, ?, ?, ?)"
    )
    if not query:
        raise NotImplementedError('TODO: insert_events')
    prepared = session.prepare(query)
    for i in range(n):
        event_time = BASE_EVENT_TIME + timedelta(minutes=i)
        event_type = EVENT_TYPES[i % 3]
        payload = json.dumps({'seq': i})
        bound = prepared.bind((user_id, event_time, event_type, payload))
        bound.consistency_level = consistency
        session.execute(bound)
    return n


def read_last(session, table, user_id, limit, consistency):
    # Для подзадач 3-4 по сценариям bulk и consistency необходимо
    # прочитать limit последних событий пользователя user_id
    # из таблицы table.
    #
    # Дописать только CQL-запрос SELECT с плейсхолдерами '?'. Порядок
    # по убыванию уже даёт кластеризация таблицы - сортировать на
    # клиенте не нужно. LIMIT - через плейсхолдер ?. Уровень
    # консистентности - на утверждении, как в insert_events.
    # Сценарий берёт из строк поля event_time и event_type.
    query = (
        f"SELECT user_id, event_time, event_type, payload FROM {table}"
        " WHERE user_id = ? LIMIT ?"
    )
    if not query:
        raise NotImplementedError('TODO: read_last')
    prepared = session.prepare(query)
    bound = prepared.bind((user_id, limit))
    bound.consistency_level = consistency
    return list(session.execute(bound))


def configure_twcs_ttl(session, table):
    # Для подзадачи 8 по сценарию compaction необходимо настроить
    # таблицу table - сессия уже подключена к keyspace hw3.
    #
    # Написать один CQL-запрос ALTER TABLE для таблицы table и
    # выполнить его через session.execute(...).
    #
    # Что задать в одном ALTER через WITH ... AND ...:
    #   - стратегия TimeWindowCompactionStrategy с окном в один день:
    #     параметры compaction_window_unit и compaction_window_size;
    #   - время жизни строк: default_time_to_live = 2592000 (30 дней).
    #
    # Сценарий compaction проверяет по system_schema.tables класс
    # стратегии, окно и default_time_to_live.
    session.execute(
        f"ALTER TABLE {table} WITH compaction = {{"
        "'class': 'TimeWindowCompactionStrategy',"
        " 'compaction_window_unit': 'DAYS',"
        " 'compaction_window_size': 1"
        "} AND default_time_to_live = 2592000"
    )