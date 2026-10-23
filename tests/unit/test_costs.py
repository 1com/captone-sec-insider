"""Spreads and trading costs (T056; FR-026 – FR-028; plan §6.8)."""

import math
import random
import statistics
from datetime import date

import pytest
from test_final_events import CAL, SESSIONS, T1, cluster

from sentinel.events import costs, final


def simulate(spread: float, sigma: float, days: int, seed: int = 7):
    """Closes at the bid or the ask around a random-walk mid; high and low from the intraday path
    widened by half the spread (the Abdi–Ranaldo model)."""
    rng = random.Random(seed)
    mid, closes, highs, lows = 10.0, [], [], []
    for _ in range(days):
        path = [mid]
        for _ in range(50):
            path.append(path[-1] * math.exp(rng.gauss(0, sigma / math.sqrt(50))))
        mid = path[-1]
        half = math.exp(spread / 2)
        closes.append(mid * (half if rng.random() < 0.5 else 1 / half))
        highs.append(max(path) * half)
        lows.append(min(path) / half)
    return closes, highs, lows


def test_abdi_ranaldo_recovers_a_known_spread():
    est = costs.ar_spread(*simulate(0.02, 0.01, 250))
    assert est == pytest.approx(0.02, rel=0.25)


def test_negative_two_day_estimates_are_averaged_before_the_floor():
    c, h, low = [10.0, 10.0, 10.0], [10.5, 10.1, 10.2], [9.9, 9.95, 9.6]
    pairs = [costs.ar_two_day(c[i], h[i], low[i], h[i + 1], low[i + 1]) for i in range(2)]
    assert costs.ar_spread(c, h, low) == math.sqrt(max(sum(pairs) / 2, 0.0))
    assert costs.ar_spread([10.0], [10.0], [10.0]) is None


def test_the_plan_illustration():
    """§6.8: a $2 stock, 1% spread, 4% volatility."""
    assert costs.round_trip_cost(0.01, 0.04, 100_000, 10_000, 1.0) == pytest.approx(0.035, abs=1e-3)
    assert costs.round_trip_cost(0.01, 0.04, 1_000_000, 10_000, 1.0) == pytest.approx(
        0.018, abs=1e-3
    )


def test_corwin_schultz_shifts_the_next_day_after_an_overnight_gap():
    assert costs.cs_two_day(10.0, 10.2, 9.8, 10.2, 9.8) > 0
    # Opening above the close: the next day's range moves down so that its low is the close
    assert costs.cs_two_day(10.0, 10.2, 9.8, 11.3, 10.9) == costs.cs_two_day(
        10.0, 10.2, 9.8, 10.4, 10.0
    )
    # Opening below the close: it moves up so that its high is the close
    assert costs.cs_two_day(10.0, 10.2, 9.8, 9.0, 8.6) == costs.cs_two_day(
        10.0, 10.2, 9.8, 10.0, 9.6
    )


def priced_path(seed=3, start=None):
    rng = random.Random(seed)
    rows, close = [], 10.0
    for d in SESSIONS:
        if start is not None and d < start:
            continue
        close *= math.exp(rng.gauss(0, 0.02))
        rows.append({"session": d, "close": close, "high": close * 1.03, "low": close * 0.97,
                     "volume": 50_000, "adj_close": close})  # fmt: skip
    return rows


def run(market_events, params, rows, tick_pilot=None):
    con = market_events(*cluster("a", T1, price=close_on(rows, T1)), prices={"100": rows},
                        sessions=CAL)  # fmt: skip
    if tick_pilot:
        from sentinel.core import reference

        con.execute(f"create table core.tick_pilot ({reference.TICK_PILOT_COLUMNS})")
        con.execute("insert into core.tick_pilot values (?, 'G2', ?, ?, 'Q')", tick_pilot)
    final.detect(con, params)
    costs.build(con, params)
    return con


def close_on(rows, t):
    return round(next(r["close"] for r in rows if r["session"] == t), 6)


def test_sql_matches_the_reference_formulas(market_events, params):
    rows = priced_path()
    con = run(market_events, params, rows)
    got = con.execute(
        "select spread_ar, spread_cs, volatility, n_returns, tick, spread, cost from evt.event_cost"
    ).fetchone()
    upto = [r for r in rows if r["session"] <= T1]
    last20 = upto[-20:]
    c, h, low = (
        [r["close"] for r in last20],
        [r["high"] for r in last20],
        [r["low"] for r in last20],
    )
    assert got[0] == pytest.approx(costs.ar_spread(c, h, low), rel=1e-9)
    cs = [costs.cs_two_day(c[i], h[i], low[i], h[i + 1], low[i + 1]) for i in range(19)]
    assert got[1] == pytest.approx(sum(cs) / 19, rel=1e-9)
    last64 = [r["adj_close"] for r in upto[-64:]]
    rets = [math.log(b / a) for a, b in zip(last64, last64[1:], strict=False)]
    assert got[2] == pytest.approx(statistics.stdev(rets), rel=1e-9) and got[3] == 63
    e = con.execute("select close_t, addv20 from evt.event").fetchone()
    assert got[4] == 0.01 and got[5] == max(got[0], 0.01 / e[0])
    assert got[6] == pytest.approx(costs.round_trip_cost(got[5], got[2], e[1], 10_000, 1.0))
    assert costs.check_costs(con) == []


def flat_path(close=2.0, start=None):
    return [{"session": d, "close": close, "volume": 100_000}
            for d in SESSIONS if start is None or d >= start]  # fmt: skip


def test_tick_floor_of_one_cent(market_events, params):
    con = run(market_events, params, flat_path())
    assert con.execute("select spread_ar, spread from evt.event_cost").fetchone() == (0.0, 0.005)


def test_tick_floor_of_five_cents_in_the_pilot(market_events, params):
    con = run(market_events, params, flat_path(), tick_pilot=["T100", date(2018, 10, 1), None])
    assert con.execute("select tick, spread from evt.event_cost").fetchone() == (0.05, 0.025)


def test_too_few_returns_leave_the_cost_null(market_events, params):
    start = SESSIONS[SESSIONS.index(T1) - 30]
    con = run(market_events, params, flat_path(start=start))
    row = con.execute("select n_returns, volatility, cost from evt.event_cost").fetchone()
    assert row[0] == 30 and row[2] is None


def test_costs_are_registered_for_tiingo_deletion():
    from sentinel.core.tiingo_register import TIINGO_DERIVED

    assert ("evt.event_cost", "price_source = 'tiingo'") in TIINGO_DERIVED


def test_report_by_price_bucket(market_events, params, tmp_path):
    con = run(market_events, params, priced_path())
    flags = costs.write_report(con, params, tmp_path / "costs.md")
    text = (tmp_path / "costs.md").read_text()
    assert "| $5–10 | 1 |" in text and "below $2" in text and flags == []
