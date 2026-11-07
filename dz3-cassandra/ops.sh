#!/usr/bin/env bash
set -euo pipefail

mkdir -p results

mode=${1:-all}

case "$mode" in
  all)
    bash "$BASH_SOURCE" tablestats
    bash "$BASH_SOURCE" repair
    ;;
  tablestats)
    # Сброс memtable на диск, чтобы метрики (Bloom, размер SSTable) были
    # по реальным файлам, а не по данным, ещё лежащим в памяти.
    docker compose exec -T c1 nodetool flush hw3 >/dev/null
    docker compose exec -T c1 nodetool tablestats hw3.user_actions > results/tablestats.txt
    echo "Сохранено: results/tablestats.txt"
    docker compose exec -T c1 nodetool tablestats hw3.user_actions_none > results/tablestats_plain.txt
    echo "Сохранено: results/tablestats_plain.txt"
    ;;
  repair)
    docker compose exec -T c1 nodetool repair hw3 > results/repair.txt
    echo "Сохранено: results/repair.txt"
    ;;
  compact)
    # Принудительная компакция user_actions: сначала flush, чтобы данные
    # из memtable точно попали на диск, затем compact. В файл идут
    # последние записи истории - свежие в начале вывода compactionhistory.
    docker compose exec -T c1 nodetool flush hw3 user_actions >/dev/null
    docker compose exec -T c1 nodetool compact hw3 user_actions >/dev/null
    hist=$(mktemp)
    docker compose exec -T c1 nodetool compactionhistory > "$hist"
    head -n 30 "$hist" > results/compaction.txt
    rm -f "$hist"
    echo "Сохранено: results/compaction.txt"
    ;;
  *)
    echo "Неизвестный режим: $mode"
    echo "Использование: bash ops.sh [all|tablestats|compact|repair]"
    exit 1
    ;;
esac

echo OK
