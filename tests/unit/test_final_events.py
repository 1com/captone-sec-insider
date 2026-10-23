"""Final events: G7, floors, cooldown in sessions, unpriced events, calendar (T024; FR-009–FR-014).

Outcome order per candidate: cooldown → G7 → priced → floors (research R7).
"""

from datetime import date, timedelta

import pytest
from conftest import line, owner, sub, weekdays

from sentinel.events import final

D1, D2 = ("9001", ("Director", "")), ("9002", ("Director", ""))
GOOD_FRIDAY = date(2019, 4, 19)
CAL = {"start": date(2018, 10, 1), "n": 280, "holidays": (GOOD_FRIDAY,)}
SESSIONS = weekdays(CAL["start"], CAL["n"], CAL["holidays"])


def buy(acc, filed: date, cik, who, value=60_000, price=10.0):
    """A Form 4 filed on `filed` for a purchase traded the session before."""
    shares = value / price
    return (
        [sub(acc, date=filed.strftime("%d-%b-%Y").upper(), cik=cik)],
        [owner(acc, ocik=who[0], rel=who[1][0], title=who[1][1])],
        [line(acc, "1", tdate=(filed - timedelta(days=1)).strftime("%d-%b-%Y").upper(),
              shares=str(shares), price=str(price))],
    )  # fmt: skip


def cluster(prefix, t: date, cik="100", price=10.0):
    """Two directors, $60k each, the second filing on T: one A candidate at T."""
    return [
        buy(f"{prefix}1", t - timedelta(days=2), cik, D1, price=price),
        buy(f"{prefix}2", t, cik, D2, price=price),
    ]


def path(close=10.0, volume=50_000, skip=(), zero=(), low_from=None, low_close=None):
    rows = []
    for d in SESSIONS:
        if d in skip:
            continue
        c = low_close if low_from is not None and d >= low_from else close
        rows.append({"session": d, "close": c, "volume": 0 if d in zero else volume})
    return rows


T1 = date(2019, 3, 14)  # a Thursday


def detect(market_events, params, *filings, prices=None, headers=None, issuer_sic=None,
           shares=None):  # fmt: skip
    con = market_events(*filings, prices=prices if prices is not None else {"100": path()},
                        headers=headers, sessions=CAL)  # fmt: skip
    if shares is not None:
        from sentinel.core import company

        con.execute(f"create table core.xbrl_fact ({company.FACT_COLUMNS})")
        for cik, end, value, filed in shares:
            con.execute(
                "insert into core.xbrl_fact values (?, 'shares_outstanding', 'shares', null, ?, ?, "
                "?, 'x', '10-Q', 'Q1', 'main:EntityCommonStockSharesOutstanding')",
                [cik, end, value, filed],
            )
    if issuer_sic is not None:
        con.execute(
            "create table core.issuer (issuer_cik VARCHAR, name VARCHAR, sic VARCHAR, "
            "sic_label VARCHAR, exchanges VARCHAR[], tickers VARCHAR[], raw_path VARCHAR)"
        )
        for cik, sic in issuer_sic.items():
            con.execute(
                "insert into core.issuer values (?, 'x', ?, null, [], [], null)", [cik, sic]
            )
    final.detect(con, params)
    return con


def outcomes(con):
    return {
        (r[0], r[1]): r[2]
        for r in con.execute(
            'select signal_date, "group", outcome from evt.event_candidate order by 1, 2'
        ).fetchall()
    }


def event(con, t=T1):
    return (
        con.execute("select * from evt.event where signal_date = ?", [t])
        .fetchdf()
        .to_dict("records")[0]
    )


def test_a_clean_cluster_becomes_an_event_with_its_inputs(market_events, params):
    con = detect(market_events, params, *cluster("a", T1))
    assert outcomes(con) == {(T1, "A"): "event"}
    e = event(con)
    assert (e["group"], e["priced"], e["close_t"], e["addv20"], e["active_sessions_20"]) == (
        "A",
        True,
        10.0,
        500_000.0,
        20,
    )
    assert e["t_session"].date() == T1 and e["entry_session"].date() == date(2019, 3, 15)
    assert (e["g7_sic"], e["g7_sic_source"], e["in_labelled_window"]) == ("3674", "header", True)
    assert e["event_id"] == f"100:A:{T1}" and e["price_source"] == "yahoo"
    members = con.execute("select accession from evt.event_member order by 1").fetchall()
    assert members == [("a1",), ("a2",)]


@pytest.mark.parametrize(
    ("sic", "expected"), [("6726", "g7_issuer_type"), ("6770", "g7_issuer_type"),
                          (None, "g7_no_sic"), ("0000", "g7_no_sic"),
                          ("missing", "needs_header")],
)  # fmt: skip
def test_g7_uses_the_signal_filings_header(market_events, params, sic, expected):
    """Spec US2 acceptance 2 (D45 as adopted: no header SIC is excluded)."""
    con = detect(market_events, params, *cluster("a", T1), headers={"a2": sic})
    assert outcomes(con) == {(T1, "A"): expected}
    assert con.execute("select count(*) from evt.event").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("current", "expected", "source"),
    [("3674", "event", "current"), (None, "g7_no_sic", None), ("6770", "g7_issuer_type", None)],
)
def test_the_d45_fallback_uses_the_current_sic(market_events, params, current, expected, source):
    params["rules"]["g7_no_sic"] = "current_sic"
    con = detect(market_events, params, *cluster("a", T1), headers={"a2": None},
                 issuer_sic={"100": current})  # fmt: skip
    assert outcomes(con) == {(T1, "A"): expected}
    if source:
        assert event(con)["g7_sic_source"] == source


def test_the_price_floor_uses_the_as_traded_close(market_events, params):
    """Spec US2 acceptance 3: $1.95 at T fails even if later adjusted prices exceed $2."""
    prices = {"100": [{**r, "adj_close": 2.5} for r in path(close=1.95, volume=100_000)]}
    con = detect(market_events, params, *cluster("a", T1, price=1.95), prices=prices)
    assert outcomes(con) == {(T1, "A"): "floor_price"}


def test_activity_and_liquidity_floors(market_events, params):
    """Spec US2 acceptance 4: 15 of 20 active sessions; then $80,000 average dollar volume."""
    window = [d for d in SESSIONS if d <= T1][-20:]
    con = detect(market_events, params, *cluster("a", T1),
                 prices={"100": path(zero=window[:5])})  # fmt: skip
    assert outcomes(con) == {(T1, "A"): "floor_activity"}
    inputs = con.execute("select active_sessions_20, addv20 from evt.event_candidate").fetchone()
    assert inputs == (15, 375_000.0)


def test_liquidity_floor(market_events, params):
    con = detect(market_events, params, *cluster("a", T1), prices={"100": path(volume=8_000)})
    assert outcomes(con) == {(T1, "A"): "floor_liquidity"}


def test_missing_rows_count_as_inactive_with_zero_dollar_volume(market_events, params):
    window = [d for d in SESSIONS if d <= T1][-20:]
    con = detect(market_events, params, *cluster("a", T1), prices={"100": path(skip=window[:5])})
    assert outcomes(con) == {(T1, "A"): "floor_activity"}


def test_a_second_cluster_within_63_sessions_is_cooled_down(market_events, params):
    """Spec US2 acceptance 5."""
    t2 = SESSIONS[SESSIONS.index(T1) + 40]
    con = detect(market_events, params, *cluster("a", T1), *cluster("b", t2))
    assert outcomes(con) == {(T1, "A"): "event", (t2, "A"): "cooldown"}


def test_the_cooldown_ends_after_63_sessions(market_events, params):
    t2 = SESSIONS[SESSIONS.index(T1) + 63]
    con = detect(market_events, params, *cluster("a", T1), *cluster("b", t2))
    assert outcomes(con) == {(T1, "A"): "event", (t2, "A"): "event"}


def test_a_floor_failure_starts_no_cooldown(market_events, params):
    t2 = SESSIONS[SESSIONS.index(T1) + 15]
    after_t1 = SESSIONS[SESSIONS.index(T1) + 1]
    prices = {"100": path(close=1.5, volume=200_000, low_from=after_t1, low_close=10.0)}
    # $1.50 until T1, then $10
    con = detect(market_events, params, *cluster("a", T1, price=1.5), *cluster("b", t2),
                 prices=prices)  # fmt: skip
    assert outcomes(con) == {(T1, "A"): "floor_price", (t2, "A"): "event"}


def test_unpriced_events_are_kept_and_start_a_cooldown(market_events, params):
    """Spec US2 acceptance 7."""
    t2 = SESSIONS[SESSIONS.index(T1) + 15]
    con = detect(market_events, params, *cluster("a", T1, cik="200"), *cluster("b", t2, cik="200"),
                 prices={})  # fmt: skip
    assert outcomes(con) == {(T1, "A"): "unpriced", (t2, "A"): "cooldown"}
    e = event(con)
    assert not e["priced"] and e["close_t"] != e["close_t"]  # NaN: no floor inputs
    assert e["price_source"] is None


def test_a_signal_on_good_friday_uses_thursday_and_enters_on_monday(market_events, params):
    """Spec US2 acceptance 6."""
    con = detect(market_events, params, *cluster("a", GOOD_FRIDAY))
    e = event(con, GOOD_FRIDAY)
    assert e["t_session"].date() == date(2019, 4, 18)
    assert e["entry_session"].date() == date(2019, 4, 22)


def test_warm_up_events_are_flagged_and_earlier_ones_ignored(market_events, params):
    cal = {"start": date(2011, 3, 1), "n": 200}
    days = weekdays(cal["start"], cal["n"])
    t_warm, t_before = date(2011, 9, 15), date(2011, 6, 15)
    rows = [{"session": d, "close": 10.0, "volume": 50_000} for d in days]
    con = market_events(*cluster("a", t_warm), *cluster("b", t_before), prices={"100": rows},
                        sessions=cal)  # fmt: skip
    final.detect(con, params)
    assert outcomes(con) == {(t_warm, "A"): "event"}
    assert not event(con, t_warm)["in_labelled_window"]


def test_invariants_hold(market_events, params):
    t2 = SESSIONS[SESSIONS.index(T1) + 40]
    con = detect(market_events, params, *cluster("a", T1), *cluster("b", t2))
    assert final.check_entry_sessions(con) == []
    assert final.check_cooldown(con, params) == []
    assert final.check_kept_events(con, params) == []
    assert final.check_funnel(con) == []


def test_market_cap_uses_shares_first_filed_on_or_before_t(market_events, params):
    """Spec US4 acceptance 2: the day-after filing is ignored."""
    shares = [("100", date(2018, 12, 31), 1_000_000, date(2019, 2, 1)),
              ("100", date(2019, 3, 1), 2_000_000, T1 + timedelta(days=1))]  # fmt: skip
    con = detect(market_events, params, *cluster("a", T1), shares=shares)
    e = event(con)
    assert (e["shares_outstanding"], e["shares_filed"].date(), e["market_cap"]) == (
        1_000_000,
        date(2019, 2, 1),
        10_000_000,
    )


def test_market_cap_is_missing_without_earlier_shares(market_events, params):
    shares = [("100", date(2019, 3, 1), 2_000_000, T1 + timedelta(days=1))]
    con = detect(market_events, params, *cluster("a", T1), shares=shares)
    assert event(con)["market_cap"] != event(con)["market_cap"]  # NaN
