"""No market price can reach the stock lookup (feature 005, SC-005; constitution VI).

The lookup file is built from an allow-list of SEC-derived warehouse tables, holds no column named
like a price, and is opened read-only.
"""

import re
from pathlib import Path

import duckdb
import pytest

from sentinel.api import lookup, queries

API = Path(lookup.__file__).parent
ALLOWED = {
    "core.filing", "core.issuer", "core.transaction", "core.owner_role", "core.build_log",
    "stg.reportingowner", "stg.nonderiv_holding", "stg.footnotes", "evt.prelim_event",
    "evt.prelim_event_member",
}  # fmt: skip
PRICE_LIKE = {"close", "open", "high", "low", "adj_close", "volume", "market_cap", "addv20",
              "dollar_volume"}  # fmt: skip
FORBIDDEN = ("price_daily", "price_series", "price_tiingo", "price_yahoo", "price_check",
             "priced_purchase", "evt.event ", "evt.event_", "xbrl_fact", "ff_", "tiingo",
             "core.session", "core.delisting", "lab.", "hold.", "feat.", "ml.")  # fmt: skip


def test_the_builder_reads_only_the_allow_list():
    assert set(lookup.SOURCES) == ALLOWED
    source = (API / "lookup.py").read_text()
    assert set(re.findall(r"\bw\.(\w+\.\w+)", source)) <= ALLOWED


@pytest.mark.parametrize("module", ["lookup.py", "queries.py", "app.py"])
def test_no_market_data_table_is_named(module):
    source = (API / module).read_text()
    assert not [name for name in FORBIDDEN if name in source]


def test_the_lookup_file_has_no_price_like_column(lookup_paths):
    con = queries.open_lookup(lookup_paths)
    try:
        columns = {
            r[0]
            for r in con.execute(
                "select column_name from information_schema.columns where table_catalog = 'lk'"
            ).fetchall()
        }
    finally:
        con.close()
    assert not columns & PRICE_LIKE


def test_the_app_cannot_write(lookup_client):
    with pytest.raises(duckdb.Error):
        lookup_client.app.state.con.execute("create table lookup.x (a INTEGER)")
