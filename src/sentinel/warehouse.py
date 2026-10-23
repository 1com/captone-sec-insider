"""The analysis database, `data/warehouse.duckdb` (specs/002-insider-warehouse/contracts/).

Every table is derived from `data/raw` by a `sentinel` command. Each command drops and recreates
only its own tables, and appends one row to `core.build_log`.
"""

import hashlib
import json
from datetime import datetime

import duckdb

from sentinel.config import Paths, params_sha256
from sentinel.ingest import manifest
from sentinel.ingest.sec_bulk import SOURCE

SCHEMAS = ("stg", "core", "evt", "audit")
# DuckDB's default cap is 80% of RAM, which together with the editor exhausted a 10 GB WSL VM
# while staging. Above this it spills to `warehouse.duckdb.tmp` instead. Operational only: no
# output depends on it, so it is not in the parameter file (which feeds the input fingerprint).
MEMORY_LIMIT = "3GB"


class MissingInput(Exception):
    """A step's input tables do not exist yet (CLI exit code 1)."""


def connect(paths: Paths, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only:
        return duckdb.connect(
            str(paths.warehouse), read_only=True, config={"memory_limit": MEMORY_LIMIT}
        )
    paths.warehouse.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(paths.warehouse), config={"memory_limit": MEMORY_LIMIT})
    # Row order is never relied on (keys, sorted comparisons), so let DuckDB stream large inserts.
    con.execute("set preserve_insertion_order = false")
    for schema in SCHEMAS:
        con.execute(f"create schema if not exists {schema}")
    con.execute(
        "create table if not exists core.build_log (step VARCHAR, started_at TIMESTAMP, "
        "finished_at TIMESTAMP, input_fingerprint VARCHAR, rows_written BIGINT)"
    )
    return con


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    schema, table = name.split(".")
    return bool(
        con.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = ? and table_name = ?",
            [schema, table],
        ).fetchone()[0]
    )


def require_tables(con: duckdb.DuckDBPyConnection, names: list[str], run_first: str) -> None:
    for name in names:
        if not table_exists(con, name):
            raise MissingInput(f"run `sentinel {run_first}` first: missing {name}")


def replace_table(con: duckdb.DuckDBPyConnection, name: str, select_sql: str, params=None) -> None:
    con.execute("begin transaction")
    try:
        con.execute(f"create or replace table {name} as {select_sql}", params)
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def scope(cutoff, issuers: list[str] | None, alias: str = "f") -> tuple[str, dict]:
    """SQL condition keeping filings dated on or before `cutoff` and of `issuers` (W9 rebuilds),
    on `{alias}.filing_date` and `{alias}.issuer_cik`, with its named parameters."""
    clauses, args = ["true"], {}
    if cutoff is not None:
        clauses.append(f"{alias}.filing_date <= cast($cutoff AS DATE)")
        args["cutoff"] = cutoff
    if issuers is not None:
        clauses.append(f"list_contains($issuers::VARCHAR[], {alias}.issuer_cik)")
        args["issuers"] = list(issuers)
    return " and ".join(clauses), args


def row_count(con: duckdb.DuckDBPyConnection, name: str) -> int:
    return con.execute(f"select count(*) from {name}").fetchone()[0]


def log_build(
    con: duckdb.DuckDBPyConnection, step: str, started_at: datetime, fingerprint: str, rows: int
) -> None:
    con.execute(
        "insert into core.build_log values (?, ?, ?, ?, ?)",
        [step, started_at, datetime.now(), fingerprint, rows],
    )


def input_fingerprint(paths: Paths) -> str:
    """SHA-256 over the stored archives' hashes and the parameter file."""
    originals = sorted(
        (e.key, e.sha256)
        for e in manifest.read_all(paths.manifest)
        if e.source == SOURCE and e.role == "original"
    )
    blob = json.dumps({"archives": originals, "params": params_sha256(paths.params_file)})
    return hashlib.sha256(blob.encode()).hexdigest()
