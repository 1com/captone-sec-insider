"""W25 on the real data (feature 004, research R8; SC-006). Run with `uv run pytest -m slow`
under the memory ceiling.

20 (issuer, T) pairs, seed 20261023, from issuers with at least two final-event candidates. Each
issuer's raw insider rows, price rows, headers and facts are copied into a scratch database; Steps
3–4 and final detection are rebuilt from records dated on or before T, and every G8 result,
candidate, outcome, floor value and event dated on or before T must equal the full build.
"""

import random

import duckdb
import pytest
from conftest import REPO

from sentinel import warehouse
from sentinel.config import Paths
from sentinel.core import entities, gates
from sentinel.events import final

pytestmark = pytest.mark.slow
SEED, PAIRS = 20261023, 20
WAREHOUSE = Paths.from_root(REPO).warehouse
COMPARED = {
    "evt.event_candidate": "issuer_cik = $cik and signal_date <= $t",
    "evt.event": "issuer_cik = $cik and signal_date <= $t",
    "core.price_check": "issuer_cik = $cik and accession in "
    "(select accession from core.filing where filing_date <= $t)",
}


@pytest.fixture(scope="module")
def pairs():
    con = warehouse.connect(Paths.from_root(REPO), read_only=True)
    try:
        if not warehouse.table_exists(con, "evt.event_candidate"):
            pytest.skip("run `sentinel detect` first")
        issuers = [
            r[0]
            for r in con.execute(
                "select issuer_cik from evt.event_candidate group by 1 having count(*) >= 2 "
                "order by 1"
            ).fetchall()
        ]
        rng = random.Random(SEED)
        out = []
        for cik in sorted(rng.sample(issuers, min(PAIRS, len(issuers)))):
            dates = [
                r[0]
                for r in con.execute(
                    "select distinct signal_date from evt.event_candidate where issuer_cik = ? "
                    "order by 1",
                    [cik],
                ).fetchall()
            ]
            out.append((cik, rng.choice(dates[:-1] or dates)))
        return out
    finally:
        con.close()


@pytest.mark.parametrize("i", range(PAIRS))
def test_detection_up_to_t_matches_the_full_build(pairs, params, tmp_path, i):
    if i >= len(pairs):
        pytest.skip("fewer issuers than pairs")
    cik, t = pairs[i]
    con = duckdb.connect(
        str(tmp_path / "scratch.duckdb"),
        config={"memory_limit": warehouse.MEMORY_LIMIT, "threads": 4},
    )
    try:
        _rebuild_and_compare(con, params, cik, t)
    finally:
        con.close()


def _copy(con, table: str, where: str, args=None) -> None:
    con.execute(f"create table {table} as select * from src.{table} where {where}", args or [])


def _in_source(con, table: str) -> bool:
    schema, name = table.split(".")
    return bool(
        con.execute(
            "select count(*) from information_schema.tables "
            "where table_catalog = 'src' and table_schema = ? and table_name = ?",
            [schema, name],
        ).fetchone()[0]
    )


def _rebuild_and_compare(con, params, cik, t):
    con.execute(f"attach '{WAREHOUSE}' as src (read_only)")
    for schema in warehouse.SCHEMAS:
        con.execute(f"create schema {schema}")
    _copy(con, "stg.submission", "issuercik = ?", [cik])
    for table in ("reportingowner", "nonderiv_trans", "nonderiv_holding", "footnotes"):
        _copy(
            con, f"stg.{table}", "accession_number in (select accession_number from stg.submission)"
        )
    entities.build(con, params, cutoff=t, issuers=[cik])
    gates.build(con, params, cutoff=t, issuers=[cik])
    _copy(con, "core.session", "true")
    for table in ("core.price_series", "core.price_daily"):
        _copy(con, table, "issuer_cik = ?", [cik])
    _copy(con, "core.filing_header", "issuer_cik = ?", [cik])
    for table in ("core.issuer", "core.xbrl_fact", "core.header_failure"):
        if _in_source(con, table):
            key = "true" if table == "core.header_failure" else "issuer_cik = ?"
            _copy(con, table, key, [] if key == "true" else [cik])
    final.detect(con, params, cutoff=t, issuers=[cik])
    args = {"cik": cik, "t": t}
    for table, where in COMPARED.items():
        # execute() returns the connection itself, so each result is fetched before the next query
        rebuilt = con.execute(f"select * from {table} where {where} order by all", args).fetchall()
        full = con.execute(
            f"select * from src.{table} where {where.replace('core.filing', 'src.core.filing')} "
            "order by all",
            args,
        ).fetchall()
        assert rebuilt == full, f"{table} differs for issuer {cik} at {t}"
