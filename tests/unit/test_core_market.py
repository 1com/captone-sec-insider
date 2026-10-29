"""Layer 3b: macro observations with `known_at`; ticker spans and short volume per company."""

from datetime import date

import pandas as pd
import pytest

from sentinel import db
from sentinel.core import market

QUIET = {"echo": lambda s: None}


def _frame(con, table: str, rows: list[dict]) -> None:
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


@pytest.fixture
def con(tmp_data):
    con = db.connect(tmp_data)
    sessions = [d.date() for d in pd.bdate_range("2019-01-02", "2019-12-31")]
    _frame(con, "ref.calendar", [{"session": d, "session_no": i} for i, d in enumerate(sessions)])
    return con


def test_macro_values_count_from_the_first_session_they_were_public(con, tmp_data):
    _frame(con, "stg_market.fred", [
        {"series": "DGS10", "mode": "market", "period": date(2019, 3, 8), "value": 2.6,
         "available": date(2019, 3, 8)},
        {"series": "CPIAUCSL", "mode": "first", "period": date(2019, 2, 1), "value": 252.8,
         "available": date(2019, 3, 9)},  # published on a Saturday: usable from Monday
        {"series": "UNRATE", "mode": "first", "period": date(2018, 11, 1), "value": 3.7,
         "available": date(2018, 12, 7)},  # before the calendar: its own date
    ])  # fmt: skip
    _frame(con, "stg_market.vix", [{"session": date(2019, 3, 8), "close": 16.0, "raw_file": "x"}])
    market.build_macro(con, tmp_data, **QUIET)
    got = dict(con.execute("select series, known_at from core.macro_observation").fetchall())
    assert got == {"DGS10": date(2019, 3, 8), "CPIAUCSL": date(2019, 3, 11),
                   "UNRATE": date(2018, 12, 7), "VIX": date(2019, 3, 8)}  # fmt: skip


def test_ticker_spans_follow_v1s_rules():
    form4 = [
        ("1", "OLD", date(2015, 1, 5), date(2017, 6, 1)),  # renamed to NEW, listed today
        ("3", "OLD", date(2012, 2, 1), date(2013, 5, 1)),  # an earlier company used OLD
    ]
    listed = [("1", "NEW", date(2026, 10, 20)), ("2", "BBB", date(2026, 10, 20))]
    series = [("2", "BBB", date(2014, 3, 3), date(2026, 10, 16), "yahoo"),
              ("4", "GONE", date(2011, 1, 3), date(2016, 8, 1), "tiingo")]  # fmt: skip
    got = {(c, t): (a, b, ev) for c, t, a, b, ev in market.ticker_spans(form4, listed, series)}
    assert got == {
        ("1", "OLD"): (date(2013, 5, 2), date(2017, 6, 1), "form4"),  # back to 3's last use
        ("1", "NEW"): (date(2017, 6, 1), None, "listed"),  # from where OLD ends
        ("2", "BBB"): (market.EARLIEST, None, "listed"),  # its series' ticker, no earlier user
        ("3", "OLD"): (market.EARLIEST, date(2013, 5, 1), "form4"),
        ("4", "GONE"): (market.EARLIEST, date(2016, 8, 1), "price_series"),
    }


def test_short_volume_is_summed_per_company_and_day_over_its_symbols(con, tmp_data):
    _frame(con, "core.ticker_span", [
        {"cik": "1", "ticker": "BRK-A", "valid_from": date(2019, 1, 1), "valid_to": None,
         "evidence": "form4"},
        {"cik": "1", "ticker": "BRK-B", "valid_from": date(2019, 1, 1), "valid_to": None,
         "evidence": "form4"},
        {"cik": "2", "ticker": "XYZ", "valid_from": date(2019, 1, 1),
         "valid_to": date(2019, 3, 1), "evidence": "form4"},
    ])  # fmt: skip
    day, later = date(2019, 3, 8), date(2019, 6, 3)
    _frame(con, "stg_market.short_volume", [
        {"session": day, "symbol": "BRK.A", "short_volume": 10.0, "total_volume": 40.0},
        {"session": day, "symbol": "BRK/B", "short_volume": 30.0, "total_volume": 60.0},
        {"session": later, "symbol": "XYZ", "short_volume": 5.0, "total_volume": 9.0},
    ])  # fmt: skip
    market.build_short_volume(con, tmp_data, **QUIET)
    got = con.execute("select cik, session, short_volume, total_volume, n_symbols "
                      "from core.short_volume").fetchall()  # fmt: skip
    assert got == [("1", day, 40.0, 100.0, 2)]  # XYZ's June volume is after cik 2's span
