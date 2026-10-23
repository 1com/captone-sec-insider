"""Truncation (W25; FR-015): deleting everything after T leaves every decision at or before T
unchanged — G8, candidates, outcomes, floor values and events (T025). Synthetic cases."""

from datetime import date

from test_final_events import CAL, SESSIONS, T1, cluster, path

from sentinel.events import final


def snapshot(con, t: date):
    q = {
        "candidates": "select candidate_id, outcome, close_t, addv20, active_sessions_20 "
        "from evt.event_candidate where signal_date <= ? order by 1",
        "events": "select event_id, t_session, entry_session, priced, close_t, addv20, "
        "active_sessions_20, g7_sic, market_cap from evt.event where signal_date <= ? order by 1",
        "g8": "select c.accession, c.line_sk, c.passes_g8, c.reason, c.ref_session "
        "from core.price_check c join core.filing f using (accession) "
        "where f.filing_date <= ? order by 1, 2",
    }
    return {k: con.execute(sql, [t]).fetchall() for k, sql in q.items()}


def same_at(con, params, t: date):
    final.detect(con, params)
    full = snapshot(con, t)
    final.detect(con, params, cutoff=t)
    cut = snapshot(con, t)
    assert full == cut
    return full


def test_reverse_split_after_t(market_events, params):
    t = SESSIONS[SESSIONS.index(T1) + 5]
    split_day = SESSIONS[SESSIONS.index(T1) + 3]
    rows = [{**r, "cum_split_after": 0.1 if r["session"] < split_day else 1.0} for r in path()]
    con = market_events(*cluster("a", T1), prices={"100": rows}, sessions=CAL)
    full = same_at(con, params, t)
    assert [e[0] for e in full["events"]] == [f"100:A:{T1}"]


def test_floor_that_would_pass_only_with_later_prices(market_events, params):
    after = SESSIONS[SESSIONS.index(T1) + 1]
    prices = {"100": path(close=1.5, volume=200_000, low_from=after, low_close=10.0)}
    con = market_events(*cluster("a", T1, price=1.5), prices=prices, sessions=CAL)
    full = same_at(con, params, T1)
    assert [c[1] for c in full["candidates"]] == ["floor_price"]


def test_cooldown_chain_crossing_t(market_events, params):
    t2 = SESSIONS[SESSIONS.index(T1) + 40]
    t3 = SESSIONS[SESSIONS.index(T1) + 70]
    con = market_events(*cluster("a", T1), *cluster("b", t2), *cluster("c", t3),
                        prices={"100": path()}, sessions=CAL)  # fmt: skip
    for t in (T1, SESSIONS[SESSIONS.index(T1) + 50], t3):
        same_at(con, params, t)
    final.detect(con, params)
    outcomes = [r[0] for r in con.execute(
        "select outcome from evt.event_candidate order by signal_date").fetchall()]  # fmt: skip
    assert outcomes == ["event", "cooldown", "event"]


def test_unpriced_and_weekend_cutoffs(market_events, params):
    sat = date(2019, 3, 16)
    con = market_events(*cluster("a", T1, cik="200"), prices={}, sessions=CAL)
    full = same_at(con, params, sat)
    assert [c[1] for c in full["candidates"]] == ["unpriced"]


def test_share_count_filed_after_t(market_events, params):
    from datetime import timedelta

    from sentinel.core import company

    con = market_events(*cluster("a", T1), prices={"100": path()}, sessions=CAL)
    con.execute(f"create table core.xbrl_fact ({company.FACT_COLUMNS})")
    for end, value, filed in ((date(2018, 12, 31), 1e6, date(2019, 2, 1)),
                              (date(2019, 3, 1), 9e6, T1 + timedelta(days=3))):  # fmt: skip
        con.execute(
            "insert into core.xbrl_fact values ('100', 'shares_outstanding', 'shares', null, ?, "
            "?, ?, 'x', '10-Q', 'Q1', 'main:x')",
            [end, value, filed],
        )
    full = same_at(con, params, T1 + timedelta(days=1))
    assert full["events"][0][-1] == 10.0 * 1e6
