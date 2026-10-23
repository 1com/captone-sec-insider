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


class NeedsFetch(MissingInput):
    """A step needs raw files another command must fetch first (CLI exit code 3)."""


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


def explore_connection(paths: Paths) -> duckdb.DuckDBPyConnection:
    """For browsing: a connection to `data/explore.duckdb` (where the DuckDB UI keeps its
    notebooks) with the warehouse attached read-only as `warehouse`."""
    con = duckdb.connect(
        str(paths.warehouse.with_name("explore.duckdb")), config={"memory_limit": MEMORY_LIMIT}
    )
    target = str(paths.warehouse).replace("'", "''")
    con.execute(f"attach '{target}' as warehouse (read_only)")
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


def exact_sum(expr: str) -> str:
    """SQL for a sum that does not depend on row order. Floating-point addition does, so each
    term is rounded to 1e-8 and added as DECIMAL; a rebuild then gives identical values."""
    return f"cast(sum(cast({expr} as DECIMAL(38, 8))) as DOUBLE)"


def row_count(con: duckdb.DuckDBPyConnection, name: str) -> int:
    return con.execute(f"select count(*) from {name}").fetchone()[0]


def log_build(
    con: duckdb.DuckDBPyConnection, step: str, started_at: datetime, fingerprint: str, rows: int
) -> None:
    con.execute(
        "insert into core.build_log values (?, ?, ?, ?, ?)",
        [step, started_at, datetime.now(), fingerprint, rows],
    )


# Feature 004 raw sources feeding the warehouse (Yahoo, Tiingo, French, FINRA, SEC bulk).
MARKET_SOURCES = ("yahoo", "tiingo", "french", "finra", "sec_company")


def input_fingerprint(paths: Paths) -> str:
    """SHA-256 over the stored archives' hashes, feature 004's raw files and the parameter file."""
    entries = manifest.read_all(paths.manifest)
    originals = sorted(
        (e.key, e.sha256) for e in entries if e.source == SOURCE and e.role == "original"
    )
    market = sorted(
        (e.source, e.key, e.sha256)
        for e in entries
        if e.source in MARKET_SOURCES and e.role == "original"
    )
    blob = json.dumps(
        {"archives": originals, "params": params_sha256(paths.params_file)}
        | ({"market": market} if market else {})
    )
    return hashlib.sha256(blob.encode()).hexdigest()


STAGED = ("submission", "reportingowner", "nonderiv_trans", "nonderiv_holding", "deriv_trans",
          "deriv_holding", "footnotes", "owner_signature")  # fmt: skip
PRIMARY_KEYS = {
    "core.filing": "accession",
    "core.transaction": "accession, line_sk",
    "core.entity_member": "issuer_cik, owner_cik, valid_from",
    "core.owner_role": "issuer_cik, owner_cik, valid_from",
    "core.clean_purchase": "accession",
    "evt.prelim_event": "event_id",
    "stg.price_yahoo": "ticker, session",
    "stg.price_tiingo": "ticker, session",
    "core.price_series": "issuer_cik, price_source, ticker",
    "core.price_daily": "issuer_cik, session",
    "core.session": "session",
    "core.price_check": "accession, line_sk",
    "core.priced_purchase": "accession",
    "evt.event_candidate": "candidate_id",
    "evt.event": "event_id",
    "core.issuer": "issuer_cik",
    "core.company_filing": "issuer_cik, accession",
    "core.delisting": "issuer_cik",
}


def check_invariants(
    con: duckdb.DuckDBPyConnection, params: dict, snapshot=None, paths: Paths | None = None
) -> list[str]:
    """W1–W8, W10–W24 (feature 002 and 004 contracts/warehouse-schema.md) for the steps that have
    been built. W9 and W25 are truncation tests; W11 needs the SEC ticker snapshot the map was built
    from, and W12 the raw-data paths."""
    from sentinel.core import (
        company,
        delistings,
        entities,
        gates,
        prices,
        symbols,
        tiingo_register,
    )
    from sentinel.events import final

    problems = []

    def add(rule: str, found: list) -> None:
        if found:
            problems.append(f"{rule}: {len(found):,} (first {found[0]})")

    if table_exists(con, "stg.load_report"):
        counts = " union all ".join(
            f"select '{t}' as table_name, quarter, count(*) as n from stg.{t} group by 2"
            for t in STAGED
        )
        add("W1 staged rows differ from the files", con.execute(
            f"select r.table_name, r.quarter from stg.load_report r "
            f"left join ({counts}) c using (table_name, quarter) "
            f"where coalesce(c.n, 0) <> r.rows_expected order by all"
        ).fetchall())  # fmt: skip
        add("W2 (quarter, src_row) not unique", [
            t for t in STAGED
            if con.execute(
                f"select count(*) <> count(distinct (quarter, src_row)) from stg.{t}"
            ).fetchone()[0]
        ])  # fmt: skip
    for table, key in PRIMARY_KEYS.items():
        if (
            table_exists(con, table)
            and con.execute(f"select count(*) <> count(distinct ({key})) from {table}").fetchone()[
                0
            ]
        ):
            add("W3 primary key not unique", [table])
    if table_exists(con, "core.transaction"):
        add("W4 transactions without a filing", [r[0] for r in con.execute(
            "select distinct accession from core.transaction "
            "where accession not in (select accession from core.filing) order by 1"
        ).fetchall()])  # fmt: skip
        add("W5 funnel does not reconcile", gates.check_funnel(con))
        add("W6 clean purchases below the G6 minimum", gates.check_min_value(con, params))
    if table_exists(con, "core.entity_member"):
        add("W7 membership not monotonic", entities.check_monotonic(con))
        add("W8 filing owners in several entities", entities.check_filings_map_to_one_entity(con))
    if table_exists(con, "core.symbol_map"):
        add("W10 event companies neither mapped nor listed", symbols.check_events_covered(con))
        if snapshot is not None:
            add("W11 tickers not from SEC data", symbols.check_sec_only(con, snapshot))
    if paths is not None:
        add(
            "W12 Tiingo data outside the register",
            tiingo_register.status(con, paths, params).problems,
        )
    if table_exists(con, "core.price_daily"):
        add("W14 price series not unique per issuer", prices.check_one_series(con))
        add("W15 invalid or inconsistent prices", prices.check_valid_prices(con))
    if table_exists(con, "core.price_check"):
        add("W16 G8 rows inconsistent", final.check_price_check(con))
        add("W17 priced purchases below the G6 minimum", final.check_priced_minimum(con, params))
    if table_exists(con, "evt.event"):
        add("W18 entry sessions", final.check_entry_sessions(con))
        add("W19 events inside a cooldown", final.check_cooldown(con, params))
        add("W20 kept events failing G7 or the floors", final.check_kept_events(con, params))
        add("W21 events and funnel disagree", final.check_funnel(con))
        add("W22 market caps from later share counts", final.check_market_caps(con))
    if table_exists(con, "core.xbrl_fact"):
        add("W22 XBRL facts not first-filed only", company.check_first_filed(con))
    if table_exists(con, "core.delisting"):
        add("W23 delisting classes or returns", delistings.check_delistings(con, params))
    return problems
