"""The Tiingo deletion register (feature 004, FR-005; constitution VI; Tiingo ToS §1.6).

Tiingo data may be stored only while the paid plan is active, and must be deleted everywhere when
it ends. Per-security values derived from Tiingo prices count as Tiingo data. The register is
(1) every manifest line with `source = tiingo`, all under `data/raw/tiingo/`, and (2) the warehouse
tables below with the predicate selecting their Tiingo-derived rows.
Contract: specs/004-market-data-events/contracts/tiingo-register.md
"""

import os
import shutil
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

import duckdb

SOURCE = "tiingo"
WHOLE_TABLE = None

# (table, predicate); WHOLE_TABLE drops the table. Every warehouse table with a `price_source`
# column must be listed (tests/unit/test_tiingo_register.py).
TIINGO_DERIVED: list[tuple[str, str | None]] = [
    ("stg.price_tiingo", WHOLE_TABLE),
    ("core.tiingo_listing", WHOLE_TABLE),
    ("core.price_series", "price_source = 'tiingo'"),
    ("core.price_daily", "price_source = 'tiingo'"),
    ("core.price_check", "price_source = 'tiingo'"),
    ("evt.event_candidate", "price_source = 'tiingo'"),
    ("evt.event", "price_source = 'tiingo'"),
    ("evt.event_cost", "price_source = 'tiingo'"),
    ("core.delisting", "price_source = 'tiingo'"),
]
# Tables whose `price_source` names the *intended* provider of SEC-derived tickers: no Tiingo data.
NOT_TIINGO_DATA = {"core.symbol_map"}


class OutsidePaidWindow(Exception):
    """Tiingo data would be written outside [ops.tiingo_paid_from, ops.tiingo_paid_until)."""


def paid_window_open(params: dict, today: date) -> bool:
    ops = params["ops"]
    until = ops.get("tiingo_paid_until")
    return until is not None and ops["tiingo_paid_from"] <= today < until


def require_paid_window(params: dict, today: date | None = None) -> None:
    today = today or date.today()
    if paid_window_open(params, today):
        return
    ops = params["ops"]
    if ops.get("tiingo_paid_until") is None:
        raise OutsidePaidWindow(
            "Tiingo data can be stored only during the paid month: set ops.tiingo_paid_until in "
            "config/params.yaml to the day the plan ends"
        )
    raise OutsidePaidWindow(
        f"today ({today}) is outside the paid Tiingo window "
        f"[{ops['tiingo_paid_from']}, {ops['tiingo_paid_until']}); Tiingo data cannot be written"
    )


# --- Status and deletion (contracts/tiingo-register.md) ------------------------------------------


@dataclass
class TiingoStatus:
    window_open: bool
    paid_until: date | None
    files: int = 0
    bytes: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _table_exists(con, name: str) -> bool:
    schema, table = name.split(".")
    return bool(
        con.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = ? and table_name = ?",
            [schema, table],
        ).fetchone()[0]
    )


def registered_rows(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = {}
    for table, predicate in TIINGO_DERIVED:
        if _table_exists(con, table):
            where = f"where {predicate}" if predicate else ""
            rows[table] = con.execute(f"select count(*) from {table} {where}").fetchone()[0]
    return rows


def unregistered_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Tables with a `price_source` column that the register does not list (must be empty)."""
    listed = {t for t, _ in TIINGO_DERIVED} | NOT_TIINGO_DATA
    found = con.execute(
        "select distinct table_schema || '.' || table_name from information_schema.columns "
        "where column_name = 'price_source' and table_schema in ('stg', 'core', 'evt', 'lab', "
        "'hold', 'feat', 'ml') order by 1"
    ).fetchall()
    return [t for (t,) in found if t not in listed]


def _stray_files(paths) -> list[str]:
    """Files under data/ that look like Tiingo data but sit outside data/raw/tiingo/."""
    inside = paths.tiingo.resolve()
    data = paths.data_raw.parent
    stray = []
    if data.exists():
        for p in data.rglob("*"):
            if "tiingo" in p.name.lower() and inside not in (p.resolve(), *p.resolve().parents):
                stray.append(str(p.relative_to(data)))
    return sorted(stray)


def status(con, paths, params: dict, today: date | None = None) -> TiingoStatus:
    """The register (W12): stored Tiingo files and rows, and anything outside it."""
    from sentinel.ingest import manifest

    today = today or date.today()
    st = TiingoStatus(paid_window_open(params, today), params["ops"].get("tiingo_paid_until"))
    for e in manifest.read_all(paths.manifest):
        if e.source == SOURCE and e.role == "original":
            path = paths.data_raw / e.path
            if path.exists():
                st.files += 1
                st.bytes += path.stat().st_size
                if not e.path.startswith("tiingo/"):
                    st.problems.append(f"Tiingo file outside data/raw/tiingo: {e.path}")
    if con is not None:
        st.rows = registered_rows(con)
        st.problems += [
            f"table with price_source not registered: {t}" for t in unregistered_tables(con)
        ]
    st.problems += [f"Tiingo-named file outside the register: {p}" for p in _stray_files(paths)]
    if not st.window_open and (st.files or any(st.rows.values())):
        st.problems.append("Tiingo data is stored outside the paid window")
    return st


@dataclass
class DeletionReport:
    files: int
    bytes: int
    rows: dict[str, int]
    deleted: bool
    log_line: str = ""


def _rewrite(warehouse_path, memory_limit: str) -> None:
    """Copy the warehouse into a fresh file and replace it, so freed blocks holding deleted values
    do not survive in the old file."""
    fresh = warehouse_path.with_name(warehouse_path.stem + ".rewrite.duckdb")
    fresh.unlink(missing_ok=True)
    con = duckdb.connect(config={"memory_limit": memory_limit})
    try:
        con.execute(
            f"attach '{str(warehouse_path).replace(chr(39), chr(39) * 2)}' as src (read_only)"
        )
        con.execute(f"attach '{str(fresh).replace(chr(39), chr(39) * 2)}' as dst")
        con.execute("copy from database src to dst")
        tables = con.execute(
            "select schema_name, table_name from duckdb_tables() where database_name = 'src'"
        ).fetchall()
        for schema, table in tables:
            a = con.execute(f'select count(*) from src."{schema}"."{table}"').fetchone()[0]
            b = con.execute(f'select count(*) from dst."{schema}"."{table}"').fetchone()[0]
            if a != b:
                raise RuntimeError(f"rewrite lost rows in {schema}.{table}: {a} → {b}")
    finally:
        con.close()
    os.replace(fresh, warehouse_path)


def delete(paths, params: dict, yes: bool = False, today: date | None = None) -> DeletionReport:
    """Delete every registered Tiingo row, table and file (constitution VI). Without `yes`, only
    report what would be deleted."""
    from sentinel import warehouse
    from sentinel.ingest import manifest

    con = warehouse.connect(paths)  # raises if `sentinel explore` or a step holds the lock
    try:
        st = status(con, paths, params, today)
        report = DeletionReport(st.files, st.bytes, st.rows, deleted=False)
        if not yes:
            return report
        con.execute("begin transaction")
        try:
            for table, predicate in TIINGO_DERIVED:
                if _table_exists(con, table):
                    if predicate is None:
                        con.execute(f"drop table {table}")
                    else:
                        con.execute(f"delete from {table} where {predicate}")
        except BaseException:
            con.execute("rollback")
            raise
        con.execute("commit")
        con.execute("checkpoint")
    finally:
        con.close()
    _rewrite(paths.warehouse, warehouse.MEMORY_LIMIT)
    book = manifest.Manifest(paths.manifest)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for e in manifest.read_all(paths.manifest):
        if e.source == SOURCE and e.role == "original" and (paths.data_raw / e.path).exists():
            book.add(replace(e, path=f"deleted:{e.path}", role="deleted", fetched_at=now))
    if paths.tiingo.exists():
        shutil.rmtree(paths.tiingo)
    for stray in _stray_files(paths):
        target = paths.data_raw.parent / stray
        shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    con = warehouse.connect(paths)
    try:
        after = status(con, paths, params, today)
    finally:
        con.close()
    if (
        after.files
        or any(after.rows.values())
        or any("outside the register" in p for p in after.problems)
    ):
        raise RuntimeError(f"Tiingo data remains after deletion: {after}")
    report.deleted = True
    report.log_line = (
        f"Tiingo data deleted on {date.today()} (constitution VI): {report.files:,} files "
        f"({report.bytes / 1e6:,.1f} MB) and "
        + ", ".join(f"{n:,} rows of {t}" for t, n in report.rows.items() if n)
        + "; the warehouse file was rewritten."
    )
    return report
