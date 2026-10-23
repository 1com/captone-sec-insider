"""W9 on the real data (research R10; SC-003). Run with `uv run pytest -m slow`.

20 (issuer, T) pairs, seed 2002, from issuers with at least 5 clean purchases and at least one
co-filing merge. Each issuer's raw rows are copied into a scratch database, Steps 3–5 are rebuilt
from records filed on or before T, and everything dated on or before T must equal the full build.
"""

import random

import duckdb
import pytest
from conftest import REPO

from sentinel import warehouse
from sentinel.config import Paths
from sentinel.core import entities, gates
from sentinel.events import prelim

pytestmark = pytest.mark.slow
SEED, PAIRS = 2002, 20
WAREHOUSE = Paths.from_root(REPO).warehouse
COMPARED = {
    "core.entity_member": "issuer_cik = $cik and valid_from <= $t",
    "core.owner_role": "issuer_cik = $cik and valid_from <= $t",
    "core.clean_purchase": "issuer_cik = $cik and filing_date <= $t",
    "evt.prelim_event": "issuer_cik = $cik and signal_date <= $t",
    "evt.prelim_event_member": "starts_with(event_id, $cik || ':') "
    "and cast(split_part(event_id, ':', 3) as DATE) <= $t",
}


@pytest.fixture(scope="module")
def pairs():
    con = warehouse.connect(Paths.from_root(REPO), read_only=True)
    try:
        issuers = [
            r[0]
            for r in con.execute(
                """
                with merged as (
                    select distinct issuer_cik from core.entity_member
                    where entity_id <> issuer_cik || ':' || owner_cik
                ),
                busy as (select issuer_cik from core.clean_purchase group by 1 having count(*) >= 5)
                select issuer_cik from merged join busy using (issuer_cik) order by 1
                """
            ).fetchall()
        ]
        rng = random.Random(SEED)
        out = []
        for cik in sorted(rng.sample(issuers, PAIRS)):
            dates = [
                r[0]
                for r in con.execute(
                    "select distinct filing_date from core.clean_purchase where issuer_cik = ? "
                    "order by 1",
                    [cik],
                ).fetchall()
            ]
            out.append((cik, rng.choice(dates[1:-1] or dates)))
        return out
    finally:
        con.close()


@pytest.mark.parametrize("i", range(PAIRS))
def test_a_rebuild_up_to_t_matches_the_full_build(pairs, params, tmp_path, i):
    cik, t = pairs[i]
    con = duckdb.connect(
        str(tmp_path / "scratch.duckdb"),
        config={"memory_limit": warehouse.MEMORY_LIMIT, "threads": 4},
    )
    try:
        _rebuild_and_compare(con, params, cik, t)
    finally:
        con.close()


def _rebuild_and_compare(con, params, cik, t):
    con.execute(f"attach '{WAREHOUSE}' as src (read_only)")
    for schema in warehouse.SCHEMAS:
        con.execute(f"create schema {schema}")
    con.execute(
        "create table stg.submission as select * from src.stg.submission where issuercik = ?",
        [cik],
    )
    for table in ("reportingowner", "nonderiv_trans", "nonderiv_holding", "footnotes"):
        con.execute(
            f"create table stg.{table} as select * from src.stg.{table} "
            "where accession_number in (select accession_number from stg.submission)"
        )
    entities.build(con, params, cutoff=t, issuers=[cik])
    gates.build(con, params, cutoff=t, issuers=[cik])
    prelim.detect_prelim(con, params, cutoff=t, issuers=[cik])
    args = {"cik": cik, "t": t}
    for table, where in COMPARED.items():
        # execute() returns the connection itself, so each result is fetched before the next query
        rebuilt = con.execute(f"select * from {table} where {where} order by all", args).fetchall()
        full = con.execute(f"select * from src.{table} where {where} order by all", args).fetchall()
        assert rebuilt == full, f"{table} differs for issuer {cik} at {t}"
