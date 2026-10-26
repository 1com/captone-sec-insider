"""Offline rebuild (SC-008; constitution V): from the stored raw files alone, with the network
blocked, the feature 004 tables come out identical, and their steps take under 30 minutes (T066).

Run under the memory ceiling, before the paid Tiingo month ends:
    systemd-run --user --wait --pipe -p MemoryMax=5G … uv run pytest -m slow \
        tests/integration/test_rebuild_identical.py
"""

import dataclasses
import time

import duckdb
import pytest
from conftest import REPO

from sentinel import cli, warehouse
from sentinel.config import Paths, load_params

pytestmark = pytest.mark.slow
FEATURE_002 = ["stage", "entities", "gates", "prelim", "symbols", "headers"]
FEATURE_004 = ["prices", "reference", "company", "detect", "delistings", "costs"]
TABLES = [
    "stg.price_yahoo", "stg.price_tiingo", "core.session", "core.price_series",
    "core.price_daily", "core.tiingo_listing", "core.tick_pilot", "core.ff_factor_daily",
    "core.ff_industry_daily", "core.sic_industry", "core.me_breakpoint", "core.issuer",
    "core.company_filing", "core.xbrl_fact", "core.price_check", "core.priced_purchase",
    "evt.event_candidate", "evt.event", "evt.event_member", "evt.event_cost", "core.delisting",
    "audit.price_issue", "audit.g8_rate", "audit.event_funnel", "audit.price_coverage",
    "audit.price_crosscheck",
]  # fmt: skip
LIMIT_SECONDS = 30 * 60


def test_offline_rebuild_is_identical_and_fast(tmp_path):
    real = Paths.from_root(REPO)
    con = warehouse.connect(real, read_only=True)
    try:
        if not warehouse.table_exists(con, "evt.event_cost"):
            pytest.skip("run `sentinel build` with the feature 004 steps first")
    finally:
        con.close()
    paths = dataclasses.replace(real, warehouse=tmp_path / "rebuild.duckdb")
    params = load_params(real.params_file)
    scratch = warehouse.connect(paths)
    scratch.execute("set threads = 4")
    try:
        for step in FEATURE_002:
            assert cli.STEPS[step](paths, params, scratch)[1], step
        started = time.monotonic()
        for step in FEATURE_004:
            assert cli.STEPS[step](paths, params, scratch)[1], step
        elapsed = time.monotonic() - started
    finally:
        scratch.close()
    assert elapsed < LIMIT_SECONDS, f"feature 004 steps took {elapsed / 60:.1f} min"
    con = duckdb.connect(config={"memory_limit": warehouse.MEMORY_LIMIT, "threads": 4})
    try:
        con.execute(f"attach '{real.warehouse}' as a (read_only)")
        con.execute(f"attach '{paths.warehouse}' as b (read_only)")
        for table in TABLES:
            for x, y in (("a", "b"), ("b", "a")):
                diff = con.execute(
                    f"select count(*) from (select * from {x}.{table} except all "
                    f"select * from {y}.{table})"
                ).fetchone()[0]
                assert diff == 0, f"{table}: {diff} rows of {x} missing from {y}"
    finally:
        con.close()
