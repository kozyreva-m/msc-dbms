#!/usr/bin/env python3
"""Collect task 2–4 metrics from local ClickHouse HTTP API."""
import re
import urllib.parse
import urllib.request

CH = "http://127.0.0.1:8123/"
AUTH = {"user": "student", "password": "takt"}
SETTINGS = (
    "SETTINGS max_threads = 4, use_query_cache = 0, "
    "use_query_condition_cache = 0, optimize_move_to_prewhere = 0"
)


def query(sql: str, timeout: int = 600, *, with_summary: bool = False) -> tuple[str, dict]:
    params = {**AUTH, "default_format": "TabSeparatedWithNames"}
    if with_summary:
        params["wait_end_of_query"] = "1"
    url = CH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=sql.encode("utf-8"), method="POST")
    import json

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        summary_raw = resp.headers.get("X-ClickHouse-Summary", "{}")
        body = resp.read().decode("utf-8")
    summary = json.loads(summary_raw) if summary_raw else {}
    return body, summary


def run_select(sql: str) -> tuple[str, int, int, str]:
    body, summary = query(sql, with_summary=True)
    read_rows = int(summary.get("read_rows", 0))
    read_bytes = int(summary.get("read_bytes", 0))
    explain, _ = query(f"EXPLAIN indexes = 1 {sql}")
    return body.strip(), read_rows, read_bytes, explain


def granules_from_explain(explain: str) -> str:
    m = re.search(r"Granules:\s*(\d+/\d+)", explain)
    return m.group(1) if m else "?"


def report_sql(table: str, country: str | None) -> str:
    where = (
        "ended_at >= toDateTime('2026-10-24 00:00:00', 'UTC') "
        "AND ended_at < toDateTime('2026-10-25 00:00:00', 'UTC')"
    )
    if country:
        where += f" AND country = '{country}'"
    return f"""
SELECT
    country,
    count() AS events_total,
    countIf(played_seconds < 20) AS events_under_20,
    round(100 * countIf(played_seconds < 20) / count(), 2) AS under_20_percent
FROM takt.{table}
WHERE {where}
GROUP BY country
ORDER BY country
{SETTINGS}
""".strip()


def main() -> None:
    cases = [
        ("DE", "hw_events_time", "DE"),
        ("DE", "hw_events_country", "DE"),
        ("ALL", "hw_events_time", None),
        ("ALL", "hw_events_country", None),
    ]
    lines = ["query\ttable\tgranules\tread_rows\tread_bytes"]
    explains_dir = []
    for label, table, country in cases:
        sql = report_sql(table, country)
        body, rr, rb, explain = run_select(sql)
        gran = granules_from_explain(explain)
        lines.append(f"{label}\t{table}\t{gran}\t{rr}\t{rb}")
        explains_dir.append(f"--- {label} / {table} ---\n{explain}\n")
        print(f"{label} {table}: granules={gran} read_rows={rr} read_bytes={rb}")
        print(body[:200], "...")

    out = Path(__file__).resolve().parent.parent / "results"
    out.mkdir(exist_ok=True)
    (out / "02_read_stats.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "02_explain.txt").write_text("\n".join(explains_dir), encoding="utf-8")


if __name__ == "__main__":
    from pathlib import Path

    main()