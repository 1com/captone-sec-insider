"""Each update run's record, in schema `ops` of the build database (data-model.md):

- `ops.update_run`: one row per run: trigger, start and end, status, the raw bytes added, its log.
- `ops.update_source`: per run and source: status, requests, files, bytes, latest date, error.
- `ops.update_table`: per run and table: rows and checksum before and after; for the product's
  `app` tables also rows added, changed and removed by key.
- `ops.coverage`: per run, the listed companies by price source and reason, and per year and status
  the companies with prices (constitution III).
- `ops.staged_file`: the stored files each staging step has applied, so an update re-stages only
  the sources with new files.

A table's checksum is its row count and the XOR of its rows' hashes: independent of row order, so
two builds of the same data give the same checksum.
"""

from datetime import datetime
from pathlib import Path

import duckdb
import pyarrow as pa

from sentinel.raw import FetchReport

STATUSES = ("started", "fetching", "staging", "building", "publishing", "complete", "partial",
            "nothing_new", "failed")  # fmt: skip
BUILD_SCHEMAS = ("stg_sec_form4", "stg_sec_form4_daily", "stg_sec_filings", "stg_sec_xbrl",
                 "stg_sec_headers", "stg_sec_tickers", "stg_yahoo", "stg_tiingo", "stg_market",
                 "ref", "core", "feature", "label")  # fmt: skip
# the key of each product table, for the change report
APP_KEYS = {
    "stock": ["cik"], "price_daily": ["cik", "session"], "company_card": ["cik"],
    "financials": ["cik", "item", "period_start", "period_end"], "filings": ["cik", "accession"],
    "insider_activity": ["accession", "side"], "insider_feed": ["cik", "cluster_date", "grp"],
    "screener": ["cik"], "freshness": ["dataset"],
}  # fmt: skip


def create(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists ops")
    con.execute(
        "create table if not exists ops.update_run (run_id VARCHAR, trigger VARCHAR, "
        "started_at TIMESTAMP, finished_at TIMESTAMP, status VARCHAR, raw_bytes_added BIGINT, "
        "log_file VARCHAR)"
    )
    con.execute(
        "create table if not exists ops.update_source (run_id VARCHAR, source VARCHAR, "
        "status VARCHAR, requests INTEGER, files_stored INTEGER, bytes BIGINT, latest_date DATE, "
        "error VARCHAR)"
    )
    con.execute(
        "create table if not exists ops.update_table (run_id VARCHAR, table_name VARCHAR, "
        "rows_before BIGINT, rows_after BIGINT, checksum_before UBIGINT, checksum_after UBIGINT, "
        "added BIGINT, changed BIGINT, removed BIGINT)"
    )
    con.execute(
        "create table if not exists ops.coverage (run_id VARCHAR, kind VARCHAR, "
        "filer_type VARCHAR, source VARCHAR, reason VARCHAR, year INTEGER, status VARCHAR, "
        "companies BIGINT)"
    )
    con.execute(
        "create table if not exists ops.staged_file (step VARCHAR, source VARCHAR, "
        "raw_file VARCHAR, sha256 VARCHAR, staged_at TIMESTAMP)"
    )


def record_staged(con, step: str, entries: list) -> None:
    """Every stored file staging step `step` has just applied (it re-stages its sources whole)."""
    create(con)
    con.execute("delete from ops.staged_file where step = ?", [step])
    if not entries:
        return
    now = datetime.now().replace(microsecond=0)
    con.register("_staged", pa.table({
        "step": [step] * len(entries), "source": [e.source for e in entries],
        "raw_file": [e.path for e in entries], "sha256": [e.sha256 for e in entries],
        "staged_at": pa.array([now] * len(entries), pa.timestamp("s"))}))  # fmt: skip
    try:
        con.execute("insert into ops.staged_file select * from _staged")
    finally:
        con.unregister("_staged")


def staged(con, step: str) -> set[str]:
    """The stored files staging step `step` has applied."""
    create(con)
    rows = con.execute("select raw_file from ops.staged_file where step = ?", [step]).fetchall()
    return {f for (f,) in rows}


def unstaged_steps(con, entries: list, step_sources: dict[str, tuple[str, ...]]) -> list[str]:
    """The staging steps with stored files they have not applied yet, in `step_sources` order."""
    create(con)
    staged = set(con.execute("select step, raw_file from ops.staged_file").fetchall())
    return [
        step
        for step, sources in step_sources.items()
        if any(e.source in sources and (step, e.path) not in staged for e in entries)
    ]


def tables(con: duckdb.DuckDBPyConnection, schemas=BUILD_SCHEMAS, catalog: str | None = None):
    """`schema.table` of every table in `schemas` (of attached database `catalog` if given)."""
    where = f"and database_name = '{catalog}'" if catalog else ""
    names = ", ".join(f"'{s}'" for s in schemas)
    return [f"{s}.{t}" for s, t in con.execute(
        f"select schema_name, table_name from duckdb_tables() where schema_name in ({names}) "
        f"{where} and not temporary order by 1, 2").fetchall()]  # fmt: skip


def checksum(con: duckdb.DuckDBPyConnection, table: str) -> tuple[int, int]:
    """(rows, XOR of row hashes): the same for the same rows in any order."""
    rows, digest = con.execute(f"select count(*), bit_xor(hash(r)) from {table} r").fetchone()
    return rows, digest or 0


def checksums(con: duckdb.DuckDBPyConnection, schemas=BUILD_SCHEMAS) -> dict[str, tuple]:
    return {t: checksum(con, t) for t in tables(con, schemas)}


def app_changes(prev: Path, new: Path) -> dict[str, tuple[int, int, int, int, int]]:
    """Per `app` table of the new serving copy: (rows before, rows after, added, changed,
    removed) by its key against the previous copy (all added when there was none)."""
    out = {}
    with duckdb.connect() as con:
        con.execute(f"attach '{new.as_posix()}' as n (read_only)")
        has_prev = prev.exists()
        if has_prev:
            con.execute(f"attach '{prev.as_posix()}' as o (read_only)")
        before = set(tables(con, ("app",), "o")) if has_prev else set()
        for table in tables(con, ("app",), "n"):
            name = table.split(".")[1]
            rows_after = con.execute(f"select count(*) from n.{table}").fetchone()[0]
            if table not in before or name not in APP_KEYS:
                out[name] = (0, rows_after, rows_after, 0, 0)
                continue
            key = ", ".join(APP_KEYS[name])
            on = " and ".join(f"a.{k} is not distinct from b.{k}" for k in APP_KEYS[name])
            rows_before = con.execute(f"select count(*) from o.{table}").fetchone()[0]
            missing = ("select count(*) from {}.{} a "
                       "where not exists (select 1 from {}.{} b where {})")  # fmt: skip
            added = con.execute(missing.format("n", table, "o", table, on)).fetchone()[0]
            removed = con.execute(missing.format("o", table, "n", table, on)).fetchone()[0]
            changed = con.execute(
                f"""
                select count(*) from (select {key}, hash(a) as h from n.{table} a) a
                join (select {key}, hash(b) as h from o.{table} b) b on {on}
                where a.h <> b.h
                """
            ).fetchone()[0]
            out[name] = (rows_before, rows_after, added, changed, removed)
    return out


def record_sources(con, run_id: str, reports: list[FetchReport]) -> None:
    if not reports:  # an update without fetching
        return
    con.executemany("insert into ops.update_source values (?, ?, ?, ?, ?, ?, ?, ?)", [
        (run_id, r.source, r.status, r.requests, r.files_stored, r.bytes, r.latest_date,
         "; ".join(r.errors)[:2000] or None) for r in reports])  # fmt: skip


def record_tables(con, run_id: str, before: dict, after: dict, app: dict) -> None:
    rows = []
    for t in sorted(set(before) | set(after)):
        rows_before, sum_before = before.get(t, (None, None))
        rows_after, sum_after = after.get(t, (None, None))
        rows.append((run_id, t, rows_before, rows_after, sum_before, sum_after, None, None, None))
    rows += [(run_id, f"app.{name}", b, a, None, None, add, chg, rem)
             for name, (b, a, add, chg, rem) in sorted(app.items())]  # fmt: skip
    if rows:
        con.executemany("insert into ops.update_table values (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def record_coverage(con, run_id: str) -> None:
    """Copies the coverage counts of this run (when the core tables exist)."""
    have = set(tables(con, ("core", "ref")))
    if "core.price_coverage" in have:
        con.execute(
            """
            insert into ops.coverage
            select ?, 'listed', filer_type, source, reason, null, null, count(*)
            from core.price_coverage group by all
            """,
            [run_id],
        )
    if "ref.security" in have:
        con.execute(
            """
            insert into ops.coverage
            select ?, 'year', null, null, null, y, status, count(*) from (
                select unnest(range(year(first_session), year(last_session) + 1)) as y,
                       case when listed then 'listed' else 'gone' end as status
                from ref.security
            ) group by y, status
            """,
            [run_id],
        )


def write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"# {datetime.now().isoformat(timespec='seconds')}\n")
        f.writelines(line + "\n" for line in lines)
