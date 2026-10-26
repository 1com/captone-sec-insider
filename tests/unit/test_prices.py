"""One price series per issuer: as-traded rebuild, series choice, issues, calendar (T012)."""

from datetime import date

import pytest
from conftest import PAID_DAY, issuer, store_tiingo, store_yahoo, universe_tables, weekdays

from sentinel.core import prices
from sentinel.core.tiingo_register import OutsidePaidWindow

DAYS = weekdays(date(2012, 1, 3), 6)  # Tue 3 … Tue 10 January 2012
INSIDE = PAID_DAY


@pytest.fixture
def paid(params):
    params["ops"]["tiingo_paid_until"] = date(2026, 11, 28)
    return params


@pytest.fixture
def con(tmp_data):
    from sentinel import warehouse

    con = warehouse.connect(tmp_data)
    universe_tables(con)
    yield con
    con.close()


def spy(close=100.0):
    return [{"session": d, "close": close} for d in DAYS]


def daily(con, cik):
    return con.execute(
        "select session, close, volume, dollar_volume, cum_split_after, price_source "
        "from core.price_daily where issuer_cik = ? order by session",
        [cik],
    ).fetchall()


def test_reverse_split_is_undone_for_as_traded_prices(con, tmp_data, params):
    """Spec US1 acceptance 1: a 1-for-10 reverse split on day 3."""
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    rows = [{"session": d, "close": 10.0, "volume": 100, "split": 0.1 if i == 2 else 1.0}
            for i, d in enumerate(DAYS)]  # fmt: skip
    store_yahoo(tmp_data, params, {"SPY": spy(), "AAA": rows})
    prices.build(con, tmp_data, params)
    got = daily(con, "1")
    assert got[0][1:5] == (1.0, 1000.0, 1000.0, 0.1)  # before: ten times smaller, same $ volume
    assert got[2][1:5] == (10.0, 100.0, 1000.0, 1.0)  # from the split on
    assert {r[5] for r in got} == {"yahoo"}


def test_stacked_reverse_splits_keep_full_precision(con, tmp_data, params):
    """Three 1-for-10,000 splits: the first session's factor is 1e-12 and its as-traded close
    5e-8. Rounding to fixed decimals stored both as 0 (W15 as-traded mismatch, feature 004 runs)."""
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    rows = [{"session": d, "close": 50_000.0, "volume": 1e9, "split": 1e-4 if 1 <= i <= 3 else 1.0}
            for i, d in enumerate(DAYS)]  # fmt: skip
    store_yahoo(tmp_data, params, {"SPY": spy(), "AAA": rows})
    prices.build(con, tmp_data, params)
    first = daily(con, "1")[0]
    assert first[4] == pytest.approx(1e-12, rel=1e-9)
    assert first[1] == pytest.approx(5e-8, rel=1e-9)
    assert prices.check_valid_prices(con) == []


def test_session_calendar_is_spy_numbered(con, tmp_data, params):
    store_yahoo(tmp_data, params, {"SPY": spy()})
    prices.build(con, tmp_data, params)
    assert con.execute("select session, session_no from core.session order by 1").fetchall() == [
        (d, i + 1) for i, d in enumerate(DAYS)
    ]


def test_spy_is_required(con, tmp_data, params):
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    store_yahoo(tmp_data, params, {"AAA": spy()})
    from sentinel.warehouse import MissingInput

    with pytest.raises(MissingInput, match="SPY"):
        prices.build(con, tmp_data, params)


def test_tiingo_series_is_resolved_checked_and_copied_as_traded(con, tmp_data, paid):
    issuer(con, "2", "XYZ", "tiingo", "Xyz Corp", valid=(date(2010, 2, 1), date(2012, 1, 5)))
    store_yahoo(tmp_data, paid, {"SPY": spy()})
    store_tiingo(
        tmp_data, paid, [("XYZQ", "PINK", "Stock", "USD", "2009-01-02", "2012-01-10")],
        {"XYZQ": [{"session": d, "close": 0.5, "volume": 1000} for d in DAYS]},
        {"XYZQ": {"ticker": "xyzq", "name": "XYZ Corp", "startDate": "2009-01-02",
                  "endDate": "2012-01-10"}},
    )  # fmt: skip
    prices.build(con, tmp_data, paid, today=INSIDE)
    assert [r[1:4] for r in daily(con, "2")][0] == (0.5, 1000.0, 500.0)
    series = con.execute(
        "select price_source, ticker, role, identity, chosen, reason from core.price_series "
        "where issuer_cik = '2'"
    ).fetchall()
    assert series == [("tiingo", "XYZQ", "primary", "ok", True, "tiingo_resolved")]
    listing = con.execute("select ticker, list_exchange, meta_name from core.tiingo_listing")
    assert listing.fetchall() == [("XYZQ", "PINK", "XYZ Corp")]


def test_tiingo_series_of_another_company_is_rejected(con, tmp_data, paid):
    issuer(con, "2", "XYZ", "tiingo", "Xyz Corp", valid=(date(2010, 2, 1), date(2012, 1, 5)))
    store_yahoo(tmp_data, paid, {"SPY": spy()})
    store_tiingo(
        tmp_data, paid, [("XYZ", "NYSE", "Stock", "USD", "2009-01-02", "")],
        {"XYZ": [{"session": d, "close": 30.0} for d in DAYS]},
        {"XYZ": {"ticker": "xyz", "name": "Zeta Biotech Inc", "startDate": "2009-01-02"}},
    )  # fmt: skip
    prices.build(con, tmp_data, paid, today=INSIDE)
    assert daily(con, "2") == []
    assert con.execute(
        "select identity, chosen from core.price_series where issuer_cik = '2'"
    ).fetchall() == [("name", False)]


def test_yahoo_series_starting_after_the_first_event_falls_back_to_tiingo(con, tmp_data, paid):
    issuer(con, "3", "LATE", "yahoo", "Late Co", first_event=DAYS[0])
    store_yahoo(tmp_data, paid, {"SPY": spy(), "LATE": [{"session": DAYS[4], "close": 9.0}]})
    store_tiingo(
        tmp_data, paid, [("LATE", "NASDAQ", "Stock", "USD", "2005-01-03", "")],
        {"LATE": [{"session": d, "close": 8.0} for d in DAYS]},
        {"LATE": {"ticker": "late", "name": "Late Co", "startDate": "2005-01-03"}},
    )  # fmt: skip
    prices.build(con, tmp_data, paid, today=INSIDE)
    assert prices.yahoo_fallback_issuers(con, paid) == ["3"]
    rows = con.execute(
        "select price_source, ticker, role, chosen, reason from core.price_series "
        "where issuer_cik = '3' order by 1"
    ).fetchall()
    assert rows == [("tiingo", "LATE", "fallback", True, "yahoo_starts_late→tiingo"),
                    ("yahoo", "LATE", "primary", False, "yahoo_starts_late")]  # fmt: skip
    assert len(daily(con, "3")) == len(DAYS)


def test_issuer_without_any_series_is_unpriced(con, tmp_data, params):
    issuer(con, "4", "NONE", "tiingo", "None Inc")
    store_yahoo(tmp_data, params, {"SPY": spy()})
    report = prices.build(con, tmp_data, params)
    assert daily(con, "4") == [] and report.unpriced == 1


def test_duplicate_sessions_keep_the_last_row_and_bad_rows_are_dropped(con, tmp_data, params):
    issuer(con, "5", "DUP", "yahoo", "Dup Inc")
    rows = [{"session": DAYS[0], "close": 1.0}, {"session": DAYS[0], "close": 2.0},
            {"session": DAYS[1], "close": 0.0}, {"session": DAYS[2], "close": 3.0, "high": 2.0,
                                                  "low": 4.0},
            {"session": DAYS[3], "close": 3.0, "open": 0.0}]  # fmt: skip
    store_yahoo(tmp_data, params, {"SPY": spy()})
    store_yahoo(tmp_data, params, {"DUP": rows})  # alone: pandas cannot align duplicates
    prices.build(con, tmp_data, params)
    assert [r[:2] for r in daily(con, "5")] == [(DAYS[0], 2.0), (DAYS[3], 3.0)]
    issues = con.execute(
        "select session, issue from audit.price_issue where ticker = 'DUP' order by 1, 2"
    ).fetchall()
    assert issues == [(DAYS[0], "duplicate_session"), (DAYS[1], "nonpositive_close"),
                      (DAYS[2], "high_below_low"), (DAYS[3], "zero_open")]  # fmt: skip


def test_cutoff_drops_rows_after_t_but_not_sessions(con, tmp_data, params):
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    store_yahoo(tmp_data, params, {"SPY": spy(), "AAA": spy(5.0)})
    # T on a Saturday: the last session on or before it is Friday 6 January
    prices.build(con, tmp_data, params, cutoff=date(2012, 1, 7))
    assert [r[0] for r in daily(con, "1")] == DAYS[:4]
    assert con.execute("select count(*) from core.session").fetchone()[0] == len(DAYS)


def test_tiingo_files_outside_the_paid_window_are_refused(con, tmp_data, paid):
    store_yahoo(tmp_data, paid, {"SPY": spy()})
    store_tiingo(tmp_data, paid, [("X", "NYSE", "Stock", "USD", "2009-01-02", "")], {}, {})
    with pytest.raises(OutsidePaidWindow):
        prices.build(con, tmp_data, paid, today=date(2026, 12, 1))


def test_price_tables_are_registered_for_deletion():
    from sentinel.core.tiingo_register import TIINGO_DERIVED

    registered = {t for t, _ in TIINGO_DERIVED}
    assert {"stg.price_tiingo", "core.tiingo_listing", "core.price_series",
            "core.price_daily", "audit.price_crosscheck"} <= registered  # fmt: skip


def test_build_needs_no_tiingo_files(con, tmp_data, params):
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    store_yahoo(tmp_data, params, {"SPY": spy(), "AAA": spy(5.0)})
    report = prices.build(con, tmp_data, params)
    assert report.tiingo_rows == 0
    assert con.execute("select count(*) from stg.price_tiingo").fetchone()[0] == 0


# --- Yahoo checked against Tiingo (audit.price_crosscheck) -------------------------------------

LONG = weekdays(date(2012, 1, 3), 45)


def path(start=10.0, wobble=0.03):
    """A price path whose daily returns alternate between +wobble and -wobble."""
    out, p = [], start
    for i, d in enumerate(LONG):
        p *= 1 + (wobble if i % 2 else -wobble)
        out.append({"session": d, "close": round(p, 4), "volume": 1000})
    return out


def listed(con, tmp_data, paid, yahoo_rows, tiingo_rows, meta_name="Aaa Inc", tried=True):
    """Listed company AAA with Yahoo prices, and Tiingo's file for the same ticker."""
    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    store_yahoo(tmp_data, paid, {"SPY": [{"session": d, "close": 100.0} for d in LONG],
                                 "AAA": yahoo_rows})  # fmt: skip
    if tried:
        meta = (
            {"ticker": "aaa", "name": meta_name, "startDate": "2010-01-04"} if tiingo_rows else {}
        )
        store_tiingo(tmp_data, paid, [], {"AAA": tiingo_rows} if tiingo_rows else {}, {"AAA": meta})
    prices.build(con, tmp_data, paid, today=INSIDE)
    return con.execute("select * from audit.price_crosscheck").fetchall()


def test_the_same_company_in_both_sources_agrees(con, tmp_data, paid):
    rows = path()
    [(cik, ticker, n, bad, share, name, ident, verdict)] = listed(con, tmp_data, paid, rows, rows)
    assert (cik, ticker, n, bad, share, ident, verdict) == ("1", "AAA", 44, 0, 0.0, "ok", "agree")
    assert name == "Aaa Inc"


def test_another_company_under_the_same_ticker_is_a_mismatch(con, tmp_data, paid):
    other = path(start=25.0, wobble=0.08)
    [(*_, share, name, ident, verdict)] = listed(
        con, tmp_data, paid, path(), other, meta_name="Zeta Biotech Inc"
    )
    assert share > 0.9 and verdict == "mismatch" and ident == "name"


def test_days_below_the_price_floor_are_ignored(con, tmp_data, paid):
    """Two sources print different closes for a $0.20 stock, which says nothing about identity."""
    [(*_, n, bad, share, name, ident, verdict)] = listed(
        con, tmp_data, paid, path(start=0.2, wobble=0.03), path(start=0.2, wobble=0.08)
    )
    assert (n, bad, share, verdict) == (0, 0, None, "insufficient")


def test_only_days_at_or_above_the_floor_are_counted(con, tmp_data, paid):
    """A stock that rises through the $2 floor: the days below it are left out."""
    rows, other = path(start=1.0, wobble=0.0), path(start=1.0, wobble=0.0)
    for r, o in zip(rows[20:], other[20:], strict=True):  # from the 21st day: $3, then wobble
        r["close"], o["close"] = 3.0, 3.0
    for i, o in enumerate(other[:19]):
        o["close"] = 1.0 * (1.2 if i % 2 else 0.8)  # would disagree, but below $2
    [(*_, n, bad, share, name, ident, verdict)] = listed(con, tmp_data, paid, rows, other)
    assert (n, bad, verdict) == (25, 0, "agree")


def test_a_few_glitches_are_reviewed_not_rejected(con, tmp_data, paid):
    rows, other = path(), path()
    for i in (5, 6, 20, 21):  # two bad prices: four return days differ (9% of 44)
        other[i]["close"] *= 1.3
    [(*_, n, bad, share, name, ident, verdict)] = listed(con, tmp_data, paid, rows, other)
    assert (bad, verdict) == (4, "review") and 0.02 < share < 0.10


def test_too_few_shared_days_is_insufficient(con, tmp_data, paid):
    rows = path()
    [(*_, n, bad, share, name, ident, verdict)] = listed(con, tmp_data, paid, rows, rows[:10])
    assert n == 9 and verdict == "insufficient"


def test_a_ticker_tiingo_does_not_have_is_not_in_tiingo(con, tmp_data, paid):
    [(*_, n, bad, share, name, ident, verdict)] = listed(con, tmp_data, paid, path(), [])
    assert (n, ident, verdict) == (0, "no_data", "not_in_tiingo")


def test_tickers_never_asked_of_tiingo_are_left_out(con, tmp_data, paid):
    assert listed(con, tmp_data, paid, path(), [], tried=False) == []


def test_tiingo_never_replaces_the_yahoo_series_in_the_check(con, tmp_data, paid):
    listed(con, tmp_data, paid, path(), path(start=25.0, wobble=0.08), meta_name="Zeta Inc")
    assert {r[0] for r in daily(con, "1")} and {r[5] for r in daily(con, "1")} == {"yahoo"}
    assert con.execute(
        "select chosen, reason from core.price_series where issuer_cik = '1'"
    ).fetchall() == [(True, "yahoo_primary")]


@pytest.mark.parametrize(
    ("n", "share", "identity", "verdict"),
    [(44, 0.02, "ok", "agree"), (44, 0.0227, "ok", "review"), (44, 0.0999, "ok", "review"),
     (44, 0.10, "ok", "mismatch"), (19, 0.0, "ok", "insufficient"), (20, 0.0, "ok", "agree"),
     (0, None, "no_data", "not_in_tiingo")],
)  # fmt: skip
def test_the_verdict_thresholds(n, share, identity, verdict):
    assert prices.crosscheck_verdict(n, share, identity) == verdict


def test_crosscheck_targets_are_the_chosen_yahoo_tickers(con, tmp_data, paid):
    from sentinel.ingest import tiingo

    issuer(con, "1", "AAA", "yahoo", "Aaa Inc")
    issuer(con, "2", "BBB", "yahoo", "Bbb Inc")
    store_yahoo(tmp_data, paid, {"SPY": spy(), "AAA": spy(5.0)})  # BBB has no Yahoo file
    prices.build(con, tmp_data, paid)
    assert [(t.issuer_cik, t.ticker, t.role) for t in tiingo.crosscheck_targets(con)] == [
        ("1", "AAA", "crosscheck")
    ]
