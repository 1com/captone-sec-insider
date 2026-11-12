"""Key financials as first filed (026, T015, FR-013): which figure each statement date shows."""

from datetime import date

import duckdb

from sentinel.web import data

D = date.fromisoformat


def _con(rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("create schema app")
    con.execute(
        "create table app.financials (cik varchar, item varchar, period_start date, "
        "period_end date, period_days integer, value double, unit varchar, filed date, "
        "known_at date, form varchar, fp varchar, tag varchar)"
    )
    con.executemany(
        "insert into app.financials values ('1', ?, ?, ?, ?, ?, 'USD', ?, ?, '10-Q', 'Q', 't')",
        [(i, s and D(s), D(e), n, v, D(f), D(f)) for i, s, e, n, v, f in rows],
    )
    return con


ROWS = [  # item, period start, period end, days, value, filed
    ("revenue", "2025-01-01", "2025-03-31", 89, 100.0, "2025-05-05"),
    ("operating_cash_flow", "2025-01-01", "2025-03-31", 89, -10.0, "2025-05-05"),
    ("cash", None, "2025-03-31", None, 50.0, "2025-05-05"),
    ("shares_outstanding", None, "2025-05-01", None, 1000.0, "2025-05-05"),
    ("revenue", "2025-04-01", "2025-06-30", 90, 110.0, "2025-08-05"),
    ("revenue", "2025-04-01", "2025-06-30", 90, 999.0, "2025-09-01"),  # a later amendment
    ("revenue", "2025-01-01", "2025-06-30", 180, 210.0, "2025-08-05"),
    ("operating_cash_flow", "2025-01-01", "2025-06-30", 180, -25.0, "2025-08-05"),
    ("cash", None, "2025-06-30", None, 40.0, "2025-08-05"),
    ("shares_outstanding", None, "2025-08-01", None, 1200.0, "2025-08-05"),
    ("revenue", "2025-01-01", "2025-12-31", 364, 450.0, "2026-03-01"),
    ("operating_cash_flow", "2025-01-01", "2025-12-31", 364, -60.0, "2026-03-01"),
    ("cash", None, "2025-12-31", None, 30.0, "2026-03-01"),
    ("long_term_debt", None, "2025-12-31", None, 5.0, "2026-03-01"),
    ("shares_outstanding", None, "2026-02-20", None, 1500.0, "2026-03-01"),
]


def _cell(col: dict, item: str):
    v = col["values"].get(item)
    return None if v is None else (v["value"], v["months"])


def test_each_statement_date_shows_the_figures_first_filed():
    f = data.financials(_con(ROWS), "1")
    q = {c["period_end"]: c for c in f["quarters"]}
    assert [c["period_end"] for c in f["quarters"]] == ["2025-12-31", "2025-06-30", "2025-03-31"]
    assert q["2025-06-30"]["filed"] == "2025-08-05"
    assert _cell(q["2025-06-30"], "revenue") == (110.0, 3)  # the quarter, not the amendment
    assert _cell(q["2025-06-30"], "operating_cash_flow") == (-25.0, 6)  # only six months reported
    assert _cell(q["2025-06-30"], "cash") == (40.0, None)
    assert _cell(q["2025-06-30"], "shares_outstanding") == (1200.0, None)  # filed the same day
    assert _cell(q["2025-06-30"], "long_term_debt") is None  # not reported: missing, not zero
    assert _cell(q["2025-12-31"], "revenue") == (450.0, 12)  # no fourth quarter on its own
    assert _cell(q["2025-03-31"], "operating_cash_flow") == (-10.0, 3)


def test_fiscal_years_show_the_twelve_month_totals():
    f = data.financials(_con(ROWS), "1")
    assert [c["period_end"] for c in f["years"]] == ["2025-12-31"]
    y = f["years"][0]
    assert _cell(y, "revenue") == (450.0, 12)
    assert _cell(y, "operating_cash_flow") == (-60.0, 12)
    assert _cell(y, "long_term_debt") == (5.0, None)
    assert _cell(y, "shares_outstanding") == (1500.0, None)
    assert [i["item"] for i in f["items"]][:2] == ["revenue", "net_income"]


def test_a_company_without_statements_shows_none():
    f = data.financials(_con(ROWS), "2")
    assert f["quarters"] == [] and f["years"] == []
