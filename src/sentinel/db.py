"""The build database, `data/sentinel.duckdb`: layers 2–5 of docs/architecture.md, one schema per
layer or source. One writer at a time; readers use the serving copy (layer 6)."""

import contextlib

import duckdb

from sentinel.config import Paths

MEMORY_LIMIT = "3GB"  # leaves room for pandas in the same process on a 5 GB job limit
SCHEMAS = (
    "stg_sec_form4", "stg_sec_filings", "stg_sec_xbrl", "stg_sec_headers", "stg_sec_tickers",
    "stg_yahoo", "stg_tiingo", "stg_market", "ref", "core", "feature", "label", "model", "score",
)  # fmt: skip


class MissingInput(Exception):
    """A step's input tables are not built yet (CLI exit code 3)."""


class StepFailed(Exception):
    """A step finished but its own checks failed (for example row counts against the files)."""


def connect(p: Paths, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if not read_only:
        p.data.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p.build_db), read_only=read_only,
                         config={"memory_limit": MEMORY_LIMIT})  # fmt: skip
    if not read_only:
        for schema in SCHEMAS:
            con.execute(f"create schema if not exists {schema}")
    return con


@contextlib.contextmanager
def transaction(con: duckdb.DuckDBPyConnection):
    con.execute("begin transaction")
    try:
        yield
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def require(con: duckdb.DuckDBPyConnection, tables: list[str], step: str) -> None:
    """Stop with a clear message if any `schema.table` is missing."""
    have = {f"{s}.{t}" for s, t in con.execute(
        "select schema_name, table_name from duckdb_tables() "
        "union all select schema_name, view_name from duckdb_views()").fetchall()}  # fmt: skip
    missing = [t for t in tables if t not in have]
    if missing:
        raise MissingInput(f"{step} needs {', '.join(missing)}: build the layers before it")


def count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return con.execute(f"select count(*) from {table}").fetchone()[0]


def exact_sum(expr: str, scale: int = 8) -> str:
    """SQL for a sum that does not depend on row order. Floating-point addition does, so each term
    is rounded to 10^-scale and added as DECIMAL; a rebuild then gives identical values."""
    return f"cast(sum(cast({expr} as DECIMAL(38, {scale}))) as DOUBLE)"
