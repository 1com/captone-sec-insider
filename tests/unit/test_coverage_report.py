"""coverage.md: XBRL coverage per item is a share of each year's events (FR-021)."""

import duckdb

from sentinel.core.company import FACT_COLUMNS
from sentinel.events import coverage


def test_financials_divide_by_every_event_of_the_year(params):
    con = duckdb.connect()
    con.execute("create schema evt; create schema core")
    con.execute(
        "create table evt.event (event_id VARCHAR, issuer_cik VARCHAR, signal_date DATE, "
        "priced BOOLEAN, market_cap DOUBLE)"
    )
    con.execute(
        "insert into evt.event values ('1:A:2019-03-14', '1', '2019-03-14', true, 5e8), "
        "('2:A:2019-06-14', '2', '2019-06-14', true, null)"
    )
    con.execute(f"create table core.xbrl_fact ({FACT_COLUMNS})")
    facts = [("shares_outstanding", "2019-02-01"), ("equity", "2019-02-01"), ("cash", "2019-04-01")]
    for concept, filed in facts:  # issuer 1 only; cash is filed after its T
        con.execute(
            "insert into core.xbrl_fact values ('1', ?, 'USD', null, '2018-12-31', 1, ?, 'x', "
            "'10-K', 'FY', 'main')",
            [concept, filed],
        )
    lines = coverage._financials(con, params)
    assert "| 2019 | 2 | 50.0% | 50.0% | 0.0% | 0.0% | 0.0% | 0.0% |" in lines
    assert any("exists for 50.0% of priced events" in line for line in lines)
