"""W1–W8, W10, W11 in one check (contracts/warehouse-schema.md), on a small synthetic warehouse."""

import json

import pytest
from conftest import line, owner, sub

from sentinel import warehouse


@pytest.fixture
def built(archives, pipeline, tmp_path):
    snapshot = tmp_path / "company_tickers_exchange_20261022.json"
    snapshot.write_text(json.dumps({"fields": ["cik", "name", "ticker", "exchange"], "data": []}))
    subs = [sub("a1", date="01-MAR-2019", cik="100"), sub("a2", date="05-MAR-2019", cik="100")]
    owners = [owner("a1", ocik="9001"), owner("a2", ocik="9002", rel="TenPercentOwner")]
    lines = [line("a1", "1", tdate="01-MAR-2019"), line("a2", "1", tdate="05-MAR-2019")]
    archives({"2019q1": {"SUBMISSION": subs, "REPORTINGOWNER": owners, "NONDERIV_TRANS": lines}})
    return pipeline(until="symbols", snapshot=snapshot), snapshot


def test_a_fresh_build_satisfies_every_invariant(built, params):
    con, snapshot = built
    assert con.execute("select count(*) from evt.prelim_event").fetchone()[0] == 1
    assert warehouse.check_invariants(con, params, snapshot) == []


def test_broken_invariants_are_reported(built, params):
    con, snapshot = built
    con.execute("insert into core.filing select * from core.filing limit 1")
    con.execute("delete from stg.reportingowner where accession_number = 'a2'")
    con.execute("update core.clean_purchase set value_usd = 1 where accession = 'a1'")
    con.execute("insert into core.symbol_map values ('100', 'ZZZ', DATE '2019-01-01', NULL, "
                "'tiingo', 'form4_history')")  # fmt: skip
    rules = [p.split(":")[0] for p in warehouse.check_invariants(con, params, snapshot)]
    assert rules == [
        "W1 staged rows differ from the files",
        "W3 primary key not unique",
        "W6 clean purchases below the G6 minimum",
        "W11 tickers not from SEC data",
    ]


def test_exact_sum_does_not_depend_on_row_order():
    import duckdb

    con = duckdb.connect()
    sql = f"select {warehouse.exact_sum('x')} from (values {{}}) t(x)"
    forward = con.execute(sql.format("(0.1::DOUBLE), (0.2), (0.3)")).fetchone()[0]
    backward = con.execute(sql.format("(0.3::DOUBLE), (0.2), (0.1)")).fetchone()[0]
    assert forward == backward == 0.6
    assert 0.1 + 0.2 + 0.3 != 0.3 + 0.2 + 0.1  # plain floating-point addition differs
