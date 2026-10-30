"""Layer 3b: filings, financial facts and share counts with `known_at`; results releases."""

from datetime import date, datetime

import pandas as pd
import pytest

from sentinel import db
from sentinel.core import filings

QUIET = {"echo": lambda s: None}


def _frame(con, table: str, rows: list[dict]) -> None:
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


@pytest.fixture
def con(tmp_data):
    con = db.connect(tmp_data)
    sessions = [d.date() for d in pd.bdate_range("2022-01-03", "2022-12-30")]
    _frame(con, "ref.calendar", [{"session": d, "session_no": i} for i, d in enumerate(sessions)])
    return con


def _filing(cik, acc, form, filed, items=None, report=None):
    return {"cik": cik, "accession": acc, "form": form, "filing_date": filed,
            "report_date": report or filed, "items": items}  # fmt: skip


def _header(acc, accepted, items=None, period=None):
    return {"accession": acc, "accepted_at_et": accepted, "items": items,
            "period_of_report": period}  # fmt: skip


def test_a_filing_counts_the_same_day_only_if_accepted_before_the_close(con, tmp_data):
    _frame(con, "stg_sec_filings.filing", [
        _filing("1", "a", "8-K", date(2022, 4, 20)),  # header: 10:00, before the close
        _filing("1", "b", "8-K", date(2022, 4, 20)),  # header: 16:30, after the close
        _filing("1", "c", "8-K", date(2022, 4, 22)),  # no header: a Friday, so Monday
        _filing("1", "d", "8-K", date(2022, 4, 22)) | {"report_date": None},  # from a daily index
    ])  # fmt: skip
    _frame(con, "stg_sec_headers.header", [
        _header("a", datetime(2022, 4, 20, 10, 0)),
        _header("b", datetime(2022, 4, 20, 16, 30)),
        _header("d", datetime(2022, 4, 22, 17, 5), "2.02,9.01", date(2022, 4, 21)),
    ])  # fmt: skip
    filings.build_filing(con, tmp_data, **QUIET)
    got = dict(con.execute("select accession, known_at from core.filing").fetchall())
    assert got == {"a": date(2022, 4, 20), "b": date(2022, 4, 21), "c": date(2022, 4, 25),
                   "d": date(2022, 4, 25)}  # fmt: skip
    daily = con.execute("select items, report_date from core.filing where accession = 'd'")
    assert daily.fetchone() == ("2.02,9.01", date(2022, 4, 21))  # from its header


def test_filings_before_the_calendar_keep_their_order(con, tmp_data):
    _frame(con, "stg_sec_filings.filing", [
        _filing("1", "a", "10-Q", date(2021, 6, 4)),  # a Friday, before the calendar's 2022 start
        _filing("1", "b", "10-Q", date(2021, 6, 8)),
    ])  # fmt: skip
    _frame(con, "stg_sec_headers.header",
           [_header("x", datetime(2022, 1, 3, 9, 0), "8.01", date(2022, 1, 3))])  # fmt: skip
    filings.build_filing(con, tmp_data, **QUIET)
    got = dict(con.execute("select accession, known_at from core.filing").fetchall())
    assert got == {"a": date(2021, 6, 7), "b": date(2021, 6, 9)}  # not both 3 January 2022


def _fact(cik, tax, tag, unit, start, end, value, filed, accn):
    return {"cik": cik, "taxonomy": tax, "tag": tag, "unit": unit, "period_start": start,
            "period_end": end, "value": value, "accession": accn, "fy": 2022, "fp": "Q1",
            "form": "10-Q", "filed": filed, "frame": None, "raw_file": "x"}  # fmt: skip


def test_financial_facts_keep_versions_and_fallback_tags_fill_only_gaps(con, tmp_data):
    rev, alt = "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"
    q1 = (date(2022, 1, 1), date(2022, 3, 31))
    q2 = (date(2022, 4, 1), date(2022, 6, 30))
    _frame(con, "stg_sec_xbrl.fact", [
        _fact("1", "us-gaap", rev, "USD", *q1, 100.0, date(2022, 5, 2), "a1"),
        _fact("1", "us-gaap", rev, "USD", *q1, 105.0, date(2022, 8, 1), "a2"),  # restated later
        _fact("1", "us-gaap", alt, "USD", *q1, 999.0, date(2022, 5, 2), "a1"),  # main tag wins
        _fact("1", "us-gaap", alt, "USD", *q2, 120.0, date(2022, 8, 1), "a2"),  # fills Q2
        _fact("1", "us-gaap", rev, "USD", date(2201, 7, 1), date(2201, 9, 30), 130.0,
              date(2022, 11, 1), "a3"),  # 2201 typed for 2022: impossible, left out
    ])  # fmt: skip
    assert filings.build_financial_fact(con, tmp_data, **QUIET)["impossible_dates"] == 1
    got = con.execute(
        "select period_end, value, first_filed, known_at, tag from core.financial_fact "
        "where item = 'revenue' order by period_end, filed"
    ).fetchall()
    assert got == [
        (date(2022, 3, 31), 100.0, True, date(2022, 5, 3), rev),
        (date(2022, 3, 31), 105.0, False, date(2022, 8, 2), rev),
        (date(2022, 6, 30), 120.0, True, date(2022, 8, 2), alt),
    ]


def test_companies_without_a_cover_page_count_use_quarterly_basic_shares(con, tmp_data):
    dei, basic = (
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    )
    _frame(con, "stg_sec_xbrl.fact", [
        _fact("1", "dei", dei, "shares", None, date(2022, 4, 25), 1e6, date(2022, 5, 2), "a1"),
        _fact("1", "us-gaap", basic, "shares", date(2022, 1, 1), date(2022, 3, 31), 990e3,
              date(2022, 5, 2), "a1"),
        _fact("2", "us-gaap", basic, "shares", date(2022, 1, 1), date(2022, 3, 31), 500e3,
              date(2022, 5, 2), "b1"),  # a quarter
        _fact("2", "us-gaap", basic, "shares", date(2021, 4, 1), date(2022, 3, 31), 480e3,
              date(2022, 5, 2), "b1"),  # a year: not used
    ])  # fmt: skip
    filings.build_financial_fact(con, tmp_data, **QUIET)
    filings.build_shares(con, tmp_data, **QUIET)
    got = con.execute(
        "select cik, shares, source from core.shares_outstanding order by cik"
    ).fetchall()
    assert got == [("1", 1e6, "cover_page"), ("2", 500e3, "basic_average")]


def test_results_releases_follow_the_registered_announcement_rule(con, tmp_data):
    _frame(con, "core.filing", [
        _filing("1", "a", "8-K", date(2022, 4, 2), "2.02,9.01"),  # deliveries
        _filing("1", "b", "8-K", date(2022, 4, 20), "2.02,9.01"),  # results
        _filing("1", "b2", "8-K", date(2022, 4, 21), "2.02"),  # its supplement
        _filing("1", "c", "10-Q", date(2022, 4, 25)),
        _filing("1", "e", "10-Q", date(2022, 7, 25)),
        _filing("1", "d", "8-K", date(2022, 7, 26), "2.02"),  # filed after the 10-Q
        _filing("1", "f", "8-K", date(2022, 12, 1), "2.02"),  # no report follows
    ])  # fmt: skip
    filings.build_results_release(con, tmp_data, **QUIET)
    got = con.execute(
        "select filing_date, confirmed from core.results_release order by filing_date"
    ).fetchall()
    assert got == [(date(2022, 4, 20), date(2022, 4, 25)), (date(2022, 7, 26), date(2022, 7, 26))]


def _counts(*rows):
    """Share counts in the order they became known: (cik, shares, source, basic, cum[, close])."""
    rows = [r if len(r) == 6 else (*r, None) for r in rows]
    return pd.DataFrame(rows, columns=["cik", "shares", "source", "basic", "cum", "close"])


def test_share_typos_are_judged_only_by_what_was_known_when_filed():
    c, b = "cover_page", "basic_average"
    counts = _counts(
        ("1", 1000.0, c, 990.0, None), ("1", 1_000_000.0, c, 1000.0, None),  # unit typo
        ("1", 1010.0, c, 1005.0, None),
        ("2", 500.0, c, None, None), ("2", 0.0, c, None, None),  # not a count
        ("2", 50_000.0, c, None, None), ("2", 520.0, c, None, None),  # jump, then back
        ("3", 1000.0, b, None, 0.005), ("3", 5.0, b, None, 1.0),  # 1-for-200 reverse split
        ("4", 1000.0, c, None, None), ("4", 200_000.0, c, None, None),  # a real change the
        ("4", 201_000.0, c, None, None), ("4", 199_000.0, c, None, None),  # next count confirms
        ("5", 1000.0, c, None, None, 10.0), ("5", 200_000.0, c, None, None, 0.06),  # a real issue:
        ("6", 1000.0, c, None, None, 10.0), ("6", 1_000_000.0, c, None, None, 10.0),  # the price
        ("6", 1_000_000.0, c, None, None, 10.0), ("6", 1010.0, c, None, None, 10.0),  # fell
        ("7", 1e-6, c, None, None),  # one share, in millions: a placeholder (V2-30)
    )  # fmt: skip
    counts[["shares", "basic"]] *= 1e6  # in millions above
    assert filings.share_typos(counts) == [
        None, "far from the same filing's average count", None,
        None, "not positive", "jump from the last accepted count", None,
        None, None,
        None, "jump from the last accepted count", None, None,
        None, None,  # value 10,000 then 12,000: kept
        None, "jump from the last accepted count",  # value 10,000 then 10 million: a typo,
        "jump from the last accepted count", None,  # repeated in the next filing (Legg Mason)
        "below 1,000 shares",
    ]  # fmt: skip
    # truncation: dropping the later counts leaves every earlier verdict unchanged
    for n in range(1, len(counts)):
        assert filings.share_typos(counts.iloc[:n]) == filings.share_typos(counts)[:n]


def test_rejected_share_counts_are_kept_apart_with_their_reason(con, tmp_data):
    dei = "EntityCommonStockSharesOutstanding"
    _frame(con, "stg_sec_xbrl.fact", [
        _fact("1", "dei", dei, "shares", None, date(2022, 4, 25), 1000.0, date(2022, 5, 2), "a1"),
        _fact("1", "dei", dei, "shares", None, date(2022, 7, 25), 9e8, date(2022, 8, 1), "a2"),
        _fact("1", "dei", dei, "shares", None, date(2022, 10, 25), 1020.0, date(2022, 11, 1),
              "a3"),
        _fact("9", "us-gaap", "Revenues", "USD", date(2022, 1, 1), date(2022, 3, 31), 1.0,
              date(2022, 5, 2), "z1"),  # gives period_start its date type
    ])  # fmt: skip
    filings.build_financial_fact(con, tmp_data, **QUIET)
    counts = filings.build_shares(con, tmp_data, **QUIET)
    assert counts["rejected: jump from the last accepted count"] == 1
    kept = con.execute("select as_of, shares from core.shares_outstanding order by 1").fetchall()
    assert kept == [(date(2022, 4, 25), 1000.0), (date(2022, 10, 25), 1020.0)]
    assert con.execute("select shares, reason from core.shares_rejected").fetchall() == [
        (9e8, "jump from the last accepted count")
    ]
    types = dict(con.execute("select column_name, data_type from duckdb_columns() "
                             "where table_name = 'shares_outstanding'").fetchall())  # fmt: skip
    assert types["as_of"] == types["known_at"] == "DATE"
