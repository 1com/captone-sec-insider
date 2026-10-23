"""Delistings: class, evidence windows, re-mapping, venue and returns (T040; FR-017 – FR-019)."""

from datetime import date, timedelta

import pytest
from conftest import market_prices, market_sessions

from sentinel import warehouse
from sentinel.core import delistings, prices


def test_add_months_clamps_the_day():
    assert delistings.add_months(date(2020, 3, 31), -1) == date(2020, 2, 29)
    assert delistings.add_months(date(2019, 1, 15), -12) == date(2018, 1, 15)


LAST = date(2019, 10, 15)


@pytest.mark.parametrize(
    ("filings", "expected"),
    [
        ([("DEFM14A", LAST - timedelta(days=150), "m")], ("acquired", "DEFM14A")),
        ([("DEFM14A", date(2018, 10, 15), "m")], ("acquired", "DEFM14A")),  # exactly 12 months
        ([("DEFM14A", date(2018, 10, 14), "m")], ("unknown", None)),  # one day too early
        ([("DEFM14A/A", LAST - timedelta(days=30), "m")], ("acquired", "DEFM14A/A")),
        ([("SC 14D9", LAST - timedelta(days=30), "m")], ("acquired", "SC 14D9")),
        ([("25-NSE", LAST + timedelta(days=10), "n")], ("performance", "25-NSE")),
        ([("15-12G", date(2020, 10, 15), "n")], ("performance", "15-12G")),  # 12 months after
        ([("15-12G", date(2020, 10, 16), "n")], ("unknown", None)),
        ([("25-NSE", LAST + timedelta(days=10), "n"), ("DEFM14A", LAST - timedelta(days=60), "m")],
         ("acquired", "DEFM14A")),  # merger evidence wins
        ([("10-Q", LAST + timedelta(days=120), "q")], ("remap", "10-Q")),
        ([("10-Q", LAST + timedelta(days=60), "q")], ("unknown", None)),
        ([], ("unknown", None)),
    ],
)  # fmt: skip
def test_classes_and_evidence_windows(params, filings, expected):
    cls, evidence = delistings.classify(params, LAST, filings)
    assert (cls, evidence[0] if evidence else None) == expected


@pytest.mark.parametrize(
    ("cls", "venue", "expected"),
    [("acquired", "nasdaq", 0.0), ("performance", "nasdaq", -0.55),
     ("performance", "nyse", -0.30), ("performance", "other", -0.55)],
)  # fmt: skip
def test_returns_by_class_and_venue(params, cls, venue, expected):
    assert delistings.delisting_return(params, cls, venue) == expected


def test_venue_names():
    assert delistings.venue_of(["Nasdaq"]) == "nasdaq"
    assert delistings.venue_of(["NYSE"]) == "nyse"
    assert delistings.venue_of(["NYSE MKT"]) == "nyse"
    assert delistings.venue_of(["OTC"]) == "other" and delistings.venue_of([]) == "other"


@pytest.fixture
def con(tmp_data):
    con = warehouse.connect(tmp_data)
    yield con
    con.close()


def _company_tables(con):
    con.execute(
        "create table if not exists core.company_filing (issuer_cik VARCHAR, accession VARCHAR, "
        "form VARCHAR, filing_date DATE, report_date DATE, items VARCHAR)"
    )
    con.execute(
        "create table if not exists core.issuer (issuer_cik VARCHAR, name VARCHAR, sic VARCHAR, "
        "sic_label VARCHAR, exchanges VARCHAR[], tickers VARCHAR[], raw_path VARCHAR)"
    )
    con.execute(f"create table if not exists core.tiingo_listing ({prices.LISTING_COLUMNS})")


def issuer(con, days, cik, last_index, filings=(), exchanges=("Nasdaq",), source="yahoo",
           ticker=None):  # fmt: skip
    market_prices(con, cik, [{"session": d, "close": 5.0} for d in days[: last_index + 1]],
                  source=source, ticker=ticker)  # fmt: skip
    for form, filed, acc in filings:
        con.execute(
            "insert into core.company_filing values (?, ?, ?, ?, null, null)",
            [cik, acc, form, filed],
        )
    con.execute("insert into core.issuer values (?, 'x', '3674', null, ?, [], null)",
                [cik, list(exchanges)])  # fmt: skip


def test_build_classifies_only_series_that_end_early(con, params):
    days = market_sessions(con, start=date(2019, 1, 2), n=300)
    _company_tables(con)
    last = len(days) - 1
    issuer(con, days, "1", 200, [("DEFM14A", days[200] - timedelta(days=150), "m1")])
    issuer(con, days, "2", 200, [("25-NSE", days[200] + timedelta(days=10), "n2")])
    issuer(con, days, "3", 200, [("25", days[200] + timedelta(days=10), "n3")], exchanges=["NYSE"])
    issuer(con, days, "4", 200)
    issuer(con, days, "5", 200, [("10-K", days[200] + timedelta(days=120), "k5")])
    issuer(con, days, "6", last - 3)  # ends inside the 5-session gap: not early
    issuer(con, days, "7", last)  # trades to the end
    report = delistings.build(con, params)
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            "select issuer_cik, class, remap_status, evidence_form, venue, delisting_return, "
            "bound_low, bound_high from core.delisting order by 1"
        ).fetchall()
    }
    assert rows == {
        "1": ("acquired", None, "DEFM14A", "nasdaq", 0.0, -1.0, 0.0),
        "2": ("performance", None, "25-NSE", "nasdaq", -0.55, -1.0, 0.0),
        "3": ("performance", None, "25", "nyse", -0.30, -1.0, 0.0),
        "4": ("unknown", None, None, "nasdaq", -0.55, -1.0, 0.0),
        "5": ("remap", "not_found", "10-K", "nasdaq", -0.55, -1.0, 0.0),
    }
    assert report.ended_early == 5
    assert delistings.check_delistings(con, params) == []


def test_tiingo_venue_is_the_last_exchange_listed_ticker(con, params):
    days = market_sessions(con, start=date(2019, 1, 2), n=300)
    _company_tables(con)
    issuer(con, days, "8", 200, exchanges=[], source="tiingo", ticker="XYZQ")
    issuer(con, days, "9", 200, exchanges=[], source="tiingo", ticker="OTCQ")
    con.execute(
        "insert into core.price_series values ('8', 'tiingo', 'XYZ', 'fill_in', null, null, 0, "
        "'ok', false, 'not_chosen')"
    )
    con.executemany(
        "insert into core.tiingo_listing values (?, ?, ?, ?, null, null, null, null)",
        [("XYZQ", "PINK", date(2019, 6, 1), date(2019, 11, 1)),
         ("XYZ", "NASDAQ", date(2005, 1, 3), date(2019, 5, 31)),
         ("OTCQ", "PINK", date(2015, 1, 2), date(2019, 11, 1))],
    )  # fmt: skip
    delistings.build(con, params)
    rows = dict(con.execute("select issuer_cik, venue from core.delisting").fetchall())
    assert rows == {"8": "nasdaq", "9": "other"}
    prices_ = dict(con.execute("select issuer_cik, price_source from core.delisting").fetchall())
    assert prices_ == {"8": "tiingo", "9": "tiingo"}  # registered for deletion


def test_unpriced_issuers_are_not_classified(con, params):
    market_sessions(con, start=date(2019, 1, 2), n=300)
    _company_tables(con)
    con.execute(
        "insert into core.company_filing values ('50', 'x', '25-NSE', '2019-05-01', null, null)"
    )
    delistings.build(con, params)
    assert con.execute("select count(*) from core.delisting").fetchone()[0] == 0
