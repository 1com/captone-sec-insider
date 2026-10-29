"""Layer 3b: which series prices each company, and the daily price table."""

from datetime import date, timedelta

import pandas as pd
import pytest

from sentinel import db
from sentinel.core import prices

QUIET = {"echo": lambda s: None}
SESSIONS = [d.date() for d in pd.bdate_range("2014-01-02", "2016-12-30")]
LIST_DAY = date(2016, 12, 30)  # the SEC's ticker list


def _frame(con, table: str, rows: list[dict]) -> None:
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


def _series(ticker, start, end, close=10.0, split_on=None, ratio=2.0, spike=None, src="yahoo"):
    out = []
    for d in SESSIONS:
        if not start <= d <= end:
            continue
        c = close * (2.5 if d == spike else 1.0)
        row = {"ticker": ticker, "session": d, "open": c, "high": c, "low": c, "close": c,
               "volume": 100.0, "adj_close": c, "dividend": 0.0,
               "raw_file": f"{src}/{ticker}"}  # fmt: skip
        if src == "yahoo":
            row["split_ratio"] = ratio if d == split_on else 0.0
        else:
            row["split_factor"] = 1.0
        out.append(row)
    return out


@pytest.fixture
def con(tmp_data):
    con = db.connect(tmp_data)
    _frame(con, "ref.calendar", [{"session": d, "session_no": i} for i, d in enumerate(SESSIONS)])
    companies = [
        # cik, name, filer_type, tickers, first_form4, last_form4, first_periodic, last_filing
        ("1", "Listed Corp", "us", ["LST"], date(2015, 1, 5), date(2016, 6, 1), None, None),
        ("2", "Late Corp", "us", ["LATE"], date(2015, 1, 5), date(2016, 6, 1), None, None),
        ("3", "Nodata Corp", "us", ["NOYH"], date(2015, 1, 5), date(2016, 6, 1), None, None),
        ("4", "Gone Widgets Inc", "us", None, date(2014, 3, 3), date(2015, 3, 2), None, None),
        ("5", "Searchco Mining Ltd", "foreign", None, None, None, date(2014, 2, 3),
         date(2015, 9, 1)),
        ("6", "Wrongname Inc", "us", None, date(2014, 3, 3), date(2015, 3, 2), None, None),
        # renamed since it stopped filing: Tiingo knows it as "Brand New Holdings"
        ("7", "Old Name Plc", "non_reporting", ["NEWN"], None, None, None, None),
        ("8", "Reuse Inc", "us", ["REU"], date(2016, 1, 4), date(2016, 6, 1), None, None),
        ("9", "First Reuse Corp", "us", None, date(2014, 2, 3), date(2014, 9, 2), None, None),
        ("10", "Empty Co", "non_reporting", ["EMTY"], None, None, None, None),  # no data anywhere
    ]  # fmt: skip
    _frame(con, "ref.company", [
        {"cik": c, "name": n, "former_names": [], "filer_type": ft, "tickers": t,
         "exchanges": None, "first_form4": f4a, "last_form4": f4b, "first_periodic": fp,
         "last_filing": lf, "is_fund": False, "is_blank_check": False}
        for c, n, ft, t, f4a, f4b, fp, lf in companies])  # fmt: skip
    con.execute("alter table ref.company alter former_names type STRUCT(name VARCHAR, "
                "valid_from VARCHAR, valid_to VARCHAR)[]")  # fmt: skip
    _frame(con, "ref.ticker_history", [
        {"cik": "4", "ticker": "GWI", "exchange": None, "valid_from": date(2014, 3, 3),
         "valid_to": date(2015, 3, 2), "evidence": "form4"},
        {"cik": "6", "ticker": "WRN", "exchange": None, "valid_from": date(2014, 3, 3),
         "valid_to": date(2015, 3, 2), "evidence": "form4"},
        {"cik": "9", "ticker": "REU", "exchange": None, "valid_from": date(2014, 2, 3),
         "valid_to": date(2014, 9, 2), "evidence": "form4"},  # REU's earlier owner
        *({"cik": c, "ticker": t, "exchange": None, "valid_from": LIST_DAY, "valid_to": None,
           "evidence": "sec_list"} for c, t in (("7", "NEWN"), ("8", "REU"), ("10", "EMTY"))),
    ])  # fmt: skip
    _frame(con, "stg_sec_tickers.snapshot", [{"snapshot_date": LIST_DAY, "cik": "7",
                                              "ticker": "NEWN"}])  # fmt: skip
    _frame(con, "stg_sec_form4.submission", [
        {"issuercik": "4", "issuername": "GONE WIDGETS INC"},
        {"issuercik": "6", "issuername": "WRONGNAME INC"}])  # fmt: skip
    _frame(con, "stg_yahoo.price",
           _series("LST", SESSIONS[0], SESSIONS[-1], 50.0, split_on=date(2016, 1, 4))
           + _series("LATE", date(2016, 6, 1), SESSIONS[-1])
           + _series("REU", SESSIONS[0], SESSIONS[-1]))  # fmt: skip
    _frame(con, "stg_tiingo.price",
           _series("LST", SESSIONS[0], SESSIONS[-1], 50.0, src="t")
           + _series("LATE", SESSIONS[0], SESSIONS[-1], src="t")
           + _series("NOYH", SESSIONS[0], SESSIONS[-1], src="t")
           + _series("GWI", SESSIONS[0], SESSIONS[-1], spike=date(2014, 9, 2), src="t")
           + _series("SRCH", SESSIONS[0], date(2015, 12, 31), src="t")
           + _series("WRN", SESSIONS[0], SESSIONS[-1], src="t")
           + _series("NEWN", SESSIONS[0], SESSIONS[-1], src="t"))  # fmt: skip
    _frame(con, "stg_tiingo.meta", [
        {"ticker": t, "name": n, "start_date": SESSIONS[0], "end_date": SESSIONS[-1]}
        for t, n in (("LST", "Listed Corp"), ("LATE", "Late Corp"), ("NOYH", "Nodata Corp"),
                     ("GWI", "Gone Widgets Inc"), ("SRCH", "Searchco Mining Limited"),
                     ("WRN", "Another Company Inc"), ("NEWN", "Brand New Holdings"))])  # fmt: skip
    _frame(con, "stg_tiingo.listing", [
        {"ticker": "NEWN", "exchange": "PINK", "asset_type": "Stock", "currency": "USD",
         "start_date": date(2014, 6, 2), "end_date": None},  # its current listing began then
        {"ticker": "GWI", "exchange": "NYSE", "asset_type": "Stock", "currency": "USD",
         "start_date": date(2010, 1, 4), "end_date": date(2015, 6, 30)},
        {"ticker": "GWI", "exchange": "NASDAQ", "asset_type": "Stock", "currency": "USD",
         "start_date": date(2019, 1, 2), "end_date": None},  # the ticker reused later
        {"ticker": "SRCH", "exchange": "NYSE", "asset_type": "Stock", "currency": "USD",
         "start_date": date(2010, 1, 4), "end_date": date(2015, 12, 31)},
        {"ticker": "WRN", "exchange": "NYSE", "asset_type": "Stock", "currency": "USD",
         "start_date": date(2010, 1, 4), "end_date": None},
    ])  # fmt: skip
    _frame(
        con,
        "stg_tiingo.search",
        [{"query": "Searchco Mining Ltd", "hit_rank": 0, "ticker": "srch", "asset_type": "Stock"}],
    )
    return con


def test_each_company_gets_the_series_its_evidence_supports(con, tmp_data):
    prices.build_candidates(con, tmp_data, **QUIET)
    prices.build_choice(con, tmp_data, **QUIET)
    got = {c: (s, t, r) for c, s, t, r in con.execute(
        "select cik, source, ticker, reason from core.price_choice").fetchall()}  # fmt: skip
    assert got["1"] == ("yahoo", "LST", "yahoo_primary")
    assert got["2"] == ("tiingo", "LATE", "yahoo_starts_late→tiingo")
    assert got["3"] == ("tiingo", "NOYH", "yahoo_missing→tiingo")
    assert got["4"] == ("tiingo", "GWI", "tiingo_resolved")  # matched by its own dates
    assert got["5"] == ("tiingo", "SRCH", "tiingo_resolved")  # found by name search
    assert got["6"] == (None, None, "rejected_name")  # Tiingo's company is another one


def test_daily_prices_are_as_traded_trimmed_and_glitches_flagged(con, tmp_data):
    for step in (prices.build_candidates, prices.build_choice, prices.build_daily):
        step(con, tmp_data, **QUIET)
    before, after = con.execute(
        "select max(close) filter (where session < '2016-01-04'), "
        "max(close) filter (where session >= '2016-01-04') from core.price_daily where cik = '1'"
    ).fetchone()
    assert (before, after) == (100.0, 50.0)  # Yahoo's split-adjusted 50 was 100 before the split
    span = con.execute(
        "select min(session), max(session) from core.price_daily where cik = '4'"
    ).fetchone()
    assert span[0] >= date(2014, 3, 3) - timedelta(days=prices.WARMUP_DAYS)
    assert span[1] <= date(2015, 3, 2) + timedelta(days=prices.TAIL_DAYS)  # tail trimmed
    flagged = con.execute("select cik, session from core.price_daily where glitch").fetchall()
    assert flagged == [("4", date(2014, 9, 2))]


def test_securities_get_their_coverage_and_the_sources_are_cross_checked(con, tmp_data):
    for step in (prices.build_candidates, prices.build_choice, prices.build_daily,
                 prices.build_check, prices.build_security):  # fmt: skip
        step(con, tmp_data, **QUIET)
    cov = dict(con.execute("select cik, coverage from ref.security").fetchall())
    assert cov == {
        "1": "full",
        "2": "full",
        "3": "full",
        "4": "full",
        "5": "foreign",
        "7": "price_only",
        "8": "full",
    }
    check = con.execute("select cik, verdict from core.price_check order by cik").fetchall()
    assert ("1", "agree") in check  # Yahoo and Tiingo give the same returns for LST


def test_identity_needs_a_shared_word_or_the_same_squeezed_name():
    span = (date(2014, 1, 1), date(2015, 1, 1))
    assert prices.identity(("Sigma Aldrich Corp", date(2010, 1, 4), None), ["SIGMA ALDRICH CORP"],
                           span) == "ok"  # fmt: skip
    assert prices.identity(("SigmaAldrich Corp", date(2010, 1, 4), None), ["SIGMA ALDRICH CORP"],
                           span) == "ok"  # fmt: skip
    assert prices.identity(("Other Inc", date(2010, 1, 4), None), ["Acme Corp"], span) == "name"
    assert prices.identity(("Acme", date(2016, 1, 4), None), ["Acme Corp"], span) == "dates"
    assert prices.identity(None, ["Acme Corp"], span) == "no_data"


def test_listed_tickers_are_trusted_on_dates_and_reach_back_to_their_listing(con, tmp_data):
    for step in (prices.build_candidates, prices.build_choice, prices.build_daily,
                 prices.build_check, prices.build_security, prices.build_coverage):  # fmt: skip
        step(con, tmp_data, **QUIET)
    choice = {c: (s, t, r) for c, s, t, r in con.execute(
        "select cik, source, ticker, reason from core.price_choice").fetchall()}  # fmt: skip
    assert choice["7"] == ("tiingo", "NEWN", "yahoo_missing→tiingo")  # renamed: still priced
    starts = dict(
        con.execute("select cik, min(session) from core.price_daily group by 1").fetchall()
    )
    assert starts["7"] == date(2014, 6, 2)  # its listing's start, not 400 days before the SEC list
    assert starts["8"] == date(2014, 9, 3)  # the day after REU's earlier owner last used it
    coverage = {c: (s, r, t) for c, s, r, t in con.execute(
        "select cik, source, reason, tiingo_only from core.price_coverage").fetchall()}  # fmt: skip
    assert coverage["7"] == ("tiingo", "priced", True)
    assert coverage["1"] == ("yahoo", "priced", False)
    assert coverage["10"] == ("none", "no data in any source", False)
