#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ДЗ_3 (Cassandra): контрольные данные, проверки сценариев, сбор результатов.
# Запуск: docker compose run --rm lab <сценарий>. Команды и порядок работы -
# в Задание.md.

import json
import os
import re
import subprocess
import sys
import time
import hashlib
import datetime
import traceback

from cassandra.cluster import Cluster
from cassandra.query import ConsistencyLevel

HW_CASE = os.environ.get('HW_CASE', 'help')
DATASET_VERSION = '2026-10-07'
SCENARIO_NAMES = ['data', 'compaction', 'bulk', 'consistency', 'metrics']
OUT = os.environ.get('OUT_DIR', '/out')
WORK = os.environ.get('WORK_DIR', '/work')
CONTACT_POINTS = os.environ.get('CONTACT_POINTS', 'c1,c2,c3').split(',')
PORT = int(os.environ.get('PORT', '9042'))

# Драйвер возвращает timestamp без таймзоны (наивный UTC), поэтому база событий
# тоже наивная, чтобы сравнения с прочитанными значениями были корректны.
BASE_EVENT_TIME = datetime.datetime(2026, 1, 1)
EVENT_TYPES = ['login', 'purchase', 'view']


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def connect():
    return Cluster(contact_points=CONTACT_POINTS, port=PORT,
                   connect_timeout=30,
                   control_connection_timeout=30)


def connect_hw3(cluster):
    for _ in range(30):
        try:
            return cluster.connect('hw3')
        except Exception:
            time.sleep(1.0)
    raise RuntimeError('keyspace hw3 не готов')


def reset_keyspace(cluster):
    admin = cluster.connect()
    admin.execute('DROP KEYSPACE IF EXISTS hw3')
    admin.execute(
        "CREATE KEYSPACE hw3 "
        "WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3}"
    )
    time.sleep(1.0)


def wait_table(session, table):
    for _ in range(60):
        try:
            rows = session.execute(
                "SELECT table_name FROM system_schema.tables "
                "WHERE keyspace_name='hw3' AND table_name=%s",
                [table],
            ).all()
            if rows:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def solution_hash():
    with open(os.path.join(WORK, 'solution.py'), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def results_path():
    return os.path.join(OUT, 'results.json')


def load_results():
    if os.path.exists(results_path()):
        with open(results_path(), encoding='utf-8') as f:
            return json.load(f)
    return {'datasetVersion': DATASET_VERSION, 'scenarios': {}}


def persist(results):
    os.makedirs(OUT, exist_ok=True)
    tmp = results_path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        f.write('\n')
    os.replace(tmp, results_path())


def check(current, name, ok, hard=True):
    current['checks'].append(name)
    if ok:
        print('PASS ' + name)
        return
    if hard:
        raise RuntimeError('FAIL: ' + name)
    print('[SKIP] ' + name)
    current['skipped'] = current.get('skipped', 0) + 1


def descending(times):
    return all(times[i] > times[i + 1] for i in range(len(times) - 1))


def rows_snapshot(rows):
    return [
        {'event_time': str(r.event_time), 'event_type': r.event_type,
         'payload': r.payload}
        for r in rows
    ]


# ---------------------------------------------------------------- сценарии

def print_help():
    print('''Cassandra - домашняя работа 3
  docker compose up -d                       Поднять три узла и keyspace hw3
  docker compose run --rm lab reset          Сбросить keyspace hw3 и статусы проверок
  docker compose run --rm lab data           Проверить таблицы, схему, фикстуры и чтение
  docker compose run --rm lab compaction     Настроить TWCS+TTL и проверить TTL
  docker compose run --rm lab bulk           Вставить 10 000 записей (замер времени)
  docker compose run --rm lab consistency    Замеры записи/чтения при ONE и QUORUM
  bash ops.sh tablestats                     Снять tablestats (Bloom, размер) для обеих таблиц
  bash ops.sh compact                        Принудительная компакция user_actions и история
  bash ops.sh repair                         Запустить nodetool repair для keyspace hw3
  docker compose run --rm lab metrics        Проверить, что ручные шаги (ops.sh) выполнены
  docker compose run --rm lab all            Последовательно: data, compaction, bulk, consistency
  docker compose run --rm lab fixtures       Показать контрольные данные и ожидания
  docker compose run --rm lab shell          Открыть cqlsh для своих запросов
  docker compose down                        Остановить стенд, сохранив данные
  docker compose down -v                     Удалить контейнеры и данные стенда

Каждый сценарий сам готовит своё состояние (сбрасывает keyspace hw3),
поэтому запускать их можно в любом порядке. Исключение - metrics: он
проверяет файлы, которые появляются после bash ops.sh tablestats,
bash ops.sh compact и bash ops.sh repair.
Все результаты сохраняются в results/results.json.''')
    return


def print_fixtures():
    print('''Контрольные данные сценария data
  Пользователь: user_id = 1001
  События: event_time = 2026-01-01T00:00:00Z + i минут, i = 0..19
  event_type: циклично login / purchase / view (по индексу i)
  payload: {"seq": i}
  Ожидания: 20 событий, чтение 5 последних - убывание времени,
            первое = событие i=19 (purchase), последнее = i=15.

Сценарий bulk
  Вставка 10 000 событий пользователя user_id = 1001 на уровне ONE
  в обе таблицы (user_actions и user_actions_none) - чтобы после
  bash ops.sh tablestats сравнение размера SSTable было честным.

Сценарий compaction
  TWCS для user_actions и TTL 30 дней проверяются по system_schema,
  затем - TTL-эксперимент харнесса: 5 строк с TTL 5 секунд для
  user_id = 3001, до истечения их видно, после истечения партиция пуста.

Сценарий consistency
  Запись 1000 событий на ONE (user 2001) и на QUORUM (user 2002),
  чтение 20 последних на каждом уровне. Каждый замер - 6 прогонов,
  первый идёт в прогрев, итог - медиана оставшихся пяти; медианы
  и отдельные прогоны сохраняются в метрики (таблица для README).

Ручные шаги (nodetool), до сценария metrics:
  bash ops.sh tablestats  -> results/tablestats.txt, results/tablestats_plain.txt
  bash ops.sh compact     -> results/compaction.txt
  bash ops.sh repair      -> results/repair.txt
  В файлах tablestats по таблицам проверяются токены
  'Bloom filter false ratio' и 'Space used (total)': команда tablestats
  пришла на смену устаревшей cfstats (начиная с Cassandra 4.0).''')
    return


def run_shell():
    subprocess.call(['/opt/cassandra/bin/cqlsh', CONTACT_POINTS[0], str(PORT)])
    return


def scenario_data(cluster, sess, current):
    reset_keyspace(cluster)
    sess = connect_hw3(cluster)
    import solution

    tables = solution.create_tables(sess)
    check(current, 'create_tables вернул две таблицы',
          sorted(tables) == ['user_actions', 'user_actions_none'])
    check(current, 'таблица user_actions готова', wait_table(sess, 'user_actions'))
    check(current, 'таблица user_actions_none готова', wait_table(sess, 'user_actions_none'))

    columns = sess.execute(
        "SELECT column_name, kind, clustering_order, position "
        "FROM system_schema.columns "
        "WHERE keyspace_name='hw3' AND table_name='user_actions'"
    ).all()
    cols = {r.column_name: r for r in columns}
    check(current, 'partition key: user_id',
          cols.get('user_id') is not None and cols['user_id'].kind == 'partition_key')
    check(current, 'clustering key event_time по убыванию',
          cols.get('event_time') is not None
          and cols['event_time'].kind == 'clustering'
          and (cols['event_time'].clustering_order or '').upper() == 'DESC')
    check(current, 'есть колонки event_type и payload',
          'event_type' in cols and 'payload' in cols)

    tabs = sess.execute(
        "SELECT table_name, compression FROM system_schema.tables "
        "WHERE keyspace_name='hw3'"
    ).all()
    comps = {t.table_name: str(t.compression) for t in tabs}
    comp_lz4 = comps.get('user_actions', '')
    comp_plain = comps.get('user_actions_none', '')
    check(current, 'user_actions: сжатие LZ4', 'LZ4' in comp_lz4)
    # Значение колонки compression из system_schema зависит от варианта
    # отключения: {'enabled': 'false'}, {'class': 'NoCompressor'} и т.п.
    comp_plain_low = (comp_plain or '').lower()
    compression_off = ('false' in comp_plain_low
                       or 'nocompressor' in comp_plain_low
                       or comp_plain_low in ('none', '{}'))
    check(current, 'user_actions_none: сжатие отключено', compression_off)

    n = solution.insert_events(sess, 'user_actions', 1001, 20,
                               ConsistencyLevel.QUORUM)
    check(current, 'вставлено 20 фикстур', n == 20)
    # Те же фикстуры во второй таблице - чтобы обе наполнялись одинаково
    # и сравнение размеров по tablestats оставалось честным.
    solution.insert_events(sess, 'user_actions_none', 1001, 20,
                           ConsistencyLevel.QUORUM)

    count = sess.execute(
        'SELECT COUNT(*) FROM hw3.user_actions WHERE user_id=1001'
    ).one()[0]
    check(current, 'в партиции 1001 ровно 20 событий', count == 20)

    rows = solution.read_last(sess, 'user_actions', 1001, 5,
                              ConsistencyLevel.QUORUM)
    check(current, 'read_last вернул 5 строк', len(rows) == 5)
    times = [r.event_time for r in rows]
    check(current, 'порядок по убыванию времени', descending(times))
    check(current, 'первое - событие i=19',
          times[0] == BASE_EVENT_TIME + datetime.timedelta(minutes=19))
    check(current, 'последнее - событие i=15',
          times[-1] == BASE_EVENT_TIME + datetime.timedelta(minutes=15))
    check(current, 'у i=19 тип purchase', rows[0].event_type == 'purchase')
    try:
        seq = json.loads(rows[0].payload).get('seq')
    except (TypeError, ValueError, AttributeError):
        seq = None
    check(current, 'у i=19 payload отражает seq=19', seq == 19)

    current['artifacts']['columns'] = [
        {'name': c.column_name, 'kind': c.kind,
         'clustering_order': c.clustering_order, 'position': c.position}
        for c in sorted(columns, key=lambda x: (x.position, x.column_name))
    ]
    current['artifacts']['compression'] = {
        'user_actions': comp_lz4, 'user_actions_none': comp_plain}
    current['artifacts']['count'] = count
    current['artifacts']['read_last'] = rows_snapshot(rows)
    return


def scenario_bulk(cluster, sess, current):
    reset_keyspace(cluster)
    sess = connect_hw3(cluster)
    import solution

    solution.create_tables(sess)
    wait_table(sess, 'user_actions')

    start = time.perf_counter()
    n = solution.insert_events(sess, 'user_actions', 1001, 10000,
                               ConsistencyLevel.ONE)
    elapsed = time.perf_counter() - start
    check(current, 'вставлено 10 000 событий', n == 10000)

    count = sess.execute(
        'SELECT COUNT(*) FROM hw3.user_actions WHERE user_id=1001'
    ).one()[0]
    check(current, 'в партиции 1001 ровно 10 000 событий', count == 10000)

    rows = solution.read_last(sess, 'user_actions', 1001, 5,
                              ConsistencyLevel.ONE)
    check(current, 'чтение 5 последних непусто', len(rows) == 5)
    times = [r.event_time for r in rows]
    check(current, 'порядок по убыванию времени', descending(times))

    # Та же загрузка во вторую таблицу - чтобы tablestats после ops.sh
    # давал честное сравнение размера SSTable (LZ4 против без сжатия).
    solution.insert_events(sess, 'user_actions_none', 1001, 10000,
                           ConsistencyLevel.ONE)
    count_none = sess.execute(
        'SELECT COUNT(*) FROM hw3.user_actions_none WHERE user_id=1001'
    ).one()[0]
    check(current, 'user_actions_none: ровно 10 000 событий',
          count_none == 10000)

    current['artifacts']['bulk'] = {
        'user': 1001, 'n': n, 'seconds': round(elapsed, 3),
        'count': count, 'count_none': count_none}
    print('bulk: %d записей за %.3f с (время и объём - в results/results.json, '
          'раздел artifacts.bulk)' % (n, elapsed))
    return


def scenario_compaction(cluster, sess, current):
    reset_keyspace(cluster)
    sess = connect_hw3(cluster)
    import solution

    solution.create_tables(sess)
    wait_table(sess, 'user_actions')
    solution.configure_twcs_ttl(sess, 'user_actions')

    row = sess.execute(
        "SELECT compaction, default_time_to_live FROM system_schema.tables "
        "WHERE keyspace_name='hw3' AND table_name='user_actions'"
    ).one()
    # compaction приходит как map<text, text>; значения опций - строки.
    comp_raw = row.compaction
    comp_opts = ({str(k): str(v) for k, v in comp_raw.items()}
                 if hasattr(comp_raw, 'items') else {})
    comp_class = comp_opts.get('class', '')
    check(current, 'user_actions: TWCS',
          'TimeWindowCompactionStrategy' in comp_class)
    check(current, 'опции TWCS содержат окно (unit/size)',
          bool(comp_opts.get('compaction_window_unit'))
          and bool(comp_opts.get('compaction_window_size')))
    check(current, 'default_time_to_live = 2592000 (30 дней)',
          row.default_time_to_live == 2592000)

    # TTL-эксперимент в харнессе, консервативно: 5 строк с TTL 5 секунд
    # для тестового пользователя, проверка до и после истечения.
    for i in range(5):
        sess.execute(
            "INSERT INTO hw3.user_actions (user_id, event_time, event_type, payload) "
            "VALUES (3001, %s, 'view', %s) USING TTL 5",
            (BASE_EVENT_TIME + datetime.timedelta(minutes=i),
             json.dumps({'seq': i})),
        )
    count_before = sess.execute(
        'SELECT COUNT(*) FROM hw3.user_actions WHERE user_id=3001'
    ).one()[0]
    check(current, 'до истечения 5 строк', count_before == 5)
    time.sleep(8)
    count_after = sess.execute(
        'SELECT COUNT(*) FROM hw3.user_actions WHERE user_id=3001'
    ).one()[0]
    check(current, 'после истечения партиция пуста', count_after == 0)

    current['artifacts']['compaction'] = {
        'options': comp_opts,
        'default_time_to_live': row.default_time_to_live,
        'rows_before_ttl_expiry': count_before,
        'rows_after_ttl_expiry': count_after,
    }
    print('compaction: TWCS и TTL настроены, до истечения %d строк, '
          'после истечения %d (детали - в results/results.json, '
          'раздел artifacts.compaction)' % (count_before, count_after))
    return


def scenario_consistency(cluster, sess, current):
    reset_keyspace(cluster)
    sess = connect_hw3(cluster)
    import solution

    solution.create_tables(sess)
    wait_table(sess, 'user_actions')

    def measure_write(user, level):
        start = time.perf_counter()
        solution.insert_events(sess, 'user_actions', user, 1000, level)
        return time.perf_counter() - start

    def measure_read(user, level):
        start = time.perf_counter()
        solution.read_last(sess, 'user_actions', user, 20, level)
        return time.perf_counter() - start

    def timed(fn, runs=6):
        # Первый прогон - прогрев, в метрики не идёт; итог - медиана
        # оставшихся. Прогоны пишут одного и того же пользователя
        # (перезапись тех же PK), поэтому объём партиции не растёт
        # и сравнение с user_actions_none не разъезжается.
        samples = []
        for i in range(runs):
            seconds = fn()
            if i == 0:
                continue
            samples.append(seconds)
        samples.sort()
        return samples[len(samples) // 2], samples

    w_one, w_one_samples = timed(
        lambda: measure_write(2001, ConsistencyLevel.ONE))
    w_quorum, w_quorum_samples = timed(
        lambda: measure_write(2002, ConsistencyLevel.QUORUM))
    r_one, r_one_samples = timed(
        lambda: measure_read(2001, ConsistencyLevel.ONE))
    r_quorum, r_quorum_samples = timed(
        lambda: measure_read(2002, ConsistencyLevel.QUORUM))

    # Контрольные проверки чтения - отдельными финальными чтениями,
    # вне замеров.
    rows_one = solution.read_last(sess, 'user_actions', 2001, 20,
                                  ConsistencyLevel.ONE)
    rows_quorum = solution.read_last(sess, 'user_actions', 2002, 20,
                                     ConsistencyLevel.QUORUM)
    check(current, 'ONE: чтение 20 строк', len(rows_one) == 20)
    check(current, 'QUORUM: чтение 20 строк', len(rows_quorum) == 20)
    check(current, 'ONE: порядок по убыванию',
          descending([r.event_time for r in rows_one]))
    check(current, 'QUORUM: порядок по убыванию',
          descending([r.event_time for r in rows_quorum]))

    # Та же нагрузка в user_actions_none (без замера) - после прогона
    # в обеих таблицах одинаковый объём, tablestats сравнит сжатие честно.
    solution.insert_events(sess, 'user_actions_none', 2001, 1000,
                           ConsistencyLevel.ONE)
    solution.insert_events(sess, 'user_actions_none', 2002, 1000,
                           ConsistencyLevel.QUORUM)

    table = [
        {'op': 'write', 'level': 'ONE', 'user': 2001, 'count': 1000,
         'runs': 6, 'seconds': round(w_one, 3),
         'seconds_samples': [round(s, 3) for s in w_one_samples]},
        {'op': 'write', 'level': 'QUORUM', 'user': 2002, 'count': 1000,
         'runs': 6, 'seconds': round(w_quorum, 3),
         'seconds_samples': [round(s, 3) for s in w_quorum_samples]},
        {'op': 'read', 'level': 'ONE', 'user': 2001, 'count': 20,
         'runs': 6, 'seconds': round(r_one, 3),
         'seconds_samples': [round(s, 3) for s in r_one_samples]},
        {'op': 'read', 'level': 'QUORUM', 'user': 2002, 'count': 20,
         'runs': 6, 'seconds': round(r_quorum, 3),
         'seconds_samples': [round(s, 3) for s in r_quorum_samples]},
    ]
    current['artifacts']['consistency'] = table
    print('consistency: write ONE %.3f с, write QUORUM %.3f с, '
          'read ONE %.3f с, read QUORUM %.3f с (медианы по 5 прогонам; '
          'числа - в results/results.json, раздел artifacts.consistency; '
          'в секундах)' % (w_one, w_quorum, r_one, r_quorum))
    return


def scenario_metrics(cluster, sess, current):
    checks_plan = [
        ('tablestats.txt', 'ops tablestats (user_actions)', True,
         ('Bloom filter false ratio', 'Space used (total)')),
        ('tablestats_plain.txt', 'ops tablestats (user_actions_none)', True,
         ('Bloom filter false ratio', 'Space used (total)')),
        ('repair.txt', 'ops repair', False,
         ('Failed', 'ERROR', 'Exception')),
        ('compaction.txt', 'ops compact', False,
         ('Failed', 'ERROR', 'Exception')),
    ]
    for filename, label, need_tokens, bad_tokens in checks_plan:
        path = os.path.join(OUT, filename)
        if not os.path.exists(path):
            if 'repair' in label:
                cmd = 'bash ops.sh repair'
            elif 'compact' in label:
                cmd = 'bash ops.sh compact'
            else:
                cmd = 'bash ops.sh tablestats'
            check(current, '%s: не выполнен (сначала %s)' % (label, cmd),
                  False, hard=False)
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
        if not text.strip():
            check(current, '%s: файл пуст - похоже, ручная команда упала '
                           '(смотрите вывод ops.sh)' % label, False, hard=False)
            continue
        check(current, '%s: файл непустой' % label, True)
        if need_tokens:
            ok = all(tok in text for tok in ('Bloom filter false ratio',
                                             'Space used (total)'))
            check(current, '%s: содержит метрики Bloom и размер' % label, ok)
            # После bash ops.sh tablestats (с flush) должны быть реальные
            # SSTable на диске у обеих таблиц - иначе сравнение сжатия пустое.
            m = re.search(r'SSTable count:\s*(\d+)', text)
            count = int(m.group(1)) if m else -1
            check(current,
                  '%s: SSTable на диске (сначала bulk или consistency, '
                  'потом bash ops.sh tablestats)' % label, count >= 1)
        else:
            ok = not any(bad in text for bad in bad_tokens)
            check(current, '%s: без ошибок выполнения' % label, ok)
    return


HANDLERS = {
    'data': scenario_data,
    'compaction': scenario_compaction,
    'bulk': scenario_bulk,
    'consistency': scenario_consistency,
    'metrics': scenario_metrics,
}


def main():
    results = load_results()
    results['datasetVersion'] = DATASET_VERSION
    sh = solution_hash()

    for name, entry in results['scenarios'].items():
        if entry.get('status') in ('passed', 'failed') \
                and entry.get('solutionHash') != sh:
            entry['previousStatus'] = entry.get('status')
            entry['status'] = 'outdated'

    if HW_CASE == 'help':
        print_help()
        return

    if HW_CASE == 'fixtures':
        print_fixtures()
        return

    if HW_CASE == 'shell':
        run_shell()
        return

    if HW_CASE == 'reset':
        cluster = connect()
        reset_keyspace(cluster)
        for name in SCENARIO_NAMES:
            if name in results['scenarios']:
                results['scenarios'][name] = {'status': 'not_run'}
        # Файлы ручных шагов (ops.sh) с прошлого прогона убрать, иначе
        # сценарий metrics примет их за свежевыполненные шаги.
        for f in ('tablestats.txt', 'tablestats_plain.txt', 'repair.txt',
                  'compaction.txt'):
            p = os.path.join(OUT, f)
            if os.path.exists(p):
                os.remove(p)
        persist(results)
        print('OK: keyspace hw3 сброшен, статусы сценариев очищены, '
              'файлы ручных шагов удалены')
        return

    if HW_CASE == 'all':
        selected = ['data', 'compaction', 'bulk', 'consistency']
    elif HW_CASE in HANDLERS:
        selected = [HW_CASE]
    else:
        raise SystemExit(
            'Неизвестная команда. Выполните docker compose run --rm lab help')

    cluster = connect()
    for name in selected:
        current = results['scenarios'].setdefault(name, {})
        current.update({
            'status': 'running',
            'startedAt': now_iso(),
            'solutionHash': sh,
            'checks': [],
            'artifacts': {},
            'skipped': 0,
        })
        persist(results)
        try:
            sess = connect_hw3(cluster)
            HANDLERS[name](cluster, sess, current)
            # Сценарий с некритичными пропусками (например, metrics без
            # выполненных ручных шагов) - не passed, а incomplete.
            current['status'] = 'incomplete' if current.get('skipped') \
                else 'passed'
            current['finishedAt'] = now_iso()
            persist(results)
            print('COMPLETE %s (всего проверок: %d)' % (name,
                                                        len(current['checks'])))
        except Exception as exc:
            current['status'] = 'failed'
            current['finishedAt'] = now_iso()
            current['error'] = {'message': str(exc)}
            persist(results)
            traceback.print_exc()
            raise SystemExit(1)


if __name__ == '__main__':
    main()
