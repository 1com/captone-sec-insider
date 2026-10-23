"""G8: the reported price must lie within the day's as-traded range ± 10% (T023; FR-008)."""

from datetime import date

import pytest
from conftest import line, owner, sub, weekdays

from sentinel.events import final

D = ("Director", "")
MARCH = weekdays(date(2019, 3, 1), 21)  # 1–29 March 2019


def purchase(acc, filed, cik, lines, owners=(("9001", D),)):
    """A Form 4 filed on `filed` with `lines` = [(sk, trade date, shares, price)]."""
    return (
        [sub(acc, date=filed, cik=cik)],
        [owner(acc, ocik=o, rel=r, title=t) for o, (r, t) in owners],
        [line(acc, sk, tdate=td, shares=str(sh), price=str(pr)) for sk, td, sh, pr in lines],
    )


def band(days, low=1.80, high=2.10):
    return [{"session": d, "close": (low + high) / 2, "low": low, "high": high} for d in days]


def run(market_events, params, *filings, prices=None):
    con = market_events(*filings, prices=prices if prices is not None else {"100": band(MARCH)})
    final.build_price_check(con, params)
    final.build_priced_purchase(con, params)
    return con


def checks(con):
    return dict(con.execute("select accession, reason from core.price_check order by 1").fetchall())


def priced(con):
    return dict(
        con.execute("select accession, g8_status from core.priced_purchase order by 1").fetchall()
    )


def test_a_price_far_outside_the_days_range_fails(market_events, params):
    """Spec US2 acceptance 1: $200 in a stock that traded between $1.80 and $2.10."""
    con = run(
        market_events,
        params,
        purchase("a1", "15-MAR-2019", "100", [("1", "13-MAR-2019", 500, 200)]),
    )
    assert checks(con) == {"a1": "outside_range"}
    assert priced(con) == {}
    assert con.execute("select count(*) from core.clean_purchase").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("price", "reason"),
    [(1.62, "ok"), (2.31, "ok"), (1.61, "outside_range"), (2.32, "outside_range")],
)
def test_the_range_is_widened_by_the_tolerance_inclusively(market_events, params, price, reason):
    con = run(
        market_events,
        params,
        purchase("a1", "15-MAR-2019", "100", [("1", "13-MAR-2019", 20_000, price)]),
    )
    assert checks(con) == {"a1": reason}
    assert ("a1" in priced(con)) == (reason == "ok")


def test_a_weekend_trade_uses_the_last_session_before_it(market_events, params):
    con = run(
        market_events,
        params,
        purchase("a1", "18-MAR-2019", "100", [("1", "16-MAR-2019", 20_000, 2.0)]),
    )
    ref = con.execute("select ref_session, reason from core.price_check").fetchone()
    assert ref == (date(2019, 3, 15), "ok")


def test_a_trade_before_the_series_starts_has_no_session(market_events, params):
    con = run(
        market_events,
        params,
        purchase("a1", "22-FEB-2019", "100", [("1", "20-FEB-2019", 20_000, 2.0)]),
    )
    assert checks(con) == {"a1": "no_session"}
    assert priced(con) == {}


def test_unpriced_issuers_skip_g8(market_events, params):
    con = run(
        market_events,
        params,
        purchase("b1", "15-MAR-2019", "200", [("1", "13-MAR-2019", 1_000, 200)]),
    )
    assert checks(con) == {}
    assert priced(con) == {"b1": "skipped_unpriced"}


def test_the_g6_minimum_is_applied_again_after_g8(market_events, params):
    """A $30k filing loses its $10k line to G8 and falls below the $25k minimum."""
    con = run(
        market_events, params,
        purchase("c1", "15-MAR-2019", "100",
                 [("1", "13-MAR-2019", 10_000, 2.0), ("2", "13-MAR-2019", 1_000, 10.0)]),
    )  # fmt: skip
    assert con.execute("select value_usd from core.clean_purchase").fetchone()[0] == 30_000
    assert dict(
        con.execute("select line_sk, reason from core.price_check order by 1").fetchall()
    ) == {"1": "ok", "2": "outside_range"}
    assert priced(con) == {}


def test_g8_rate_by_year_and_in_total(market_events, params):
    con = run(
        market_events,
        params,
        purchase("a1", "15-MAR-2019", "100", [("1", "13-MAR-2019", 20_000, 2.0)]),
        purchase("a2", "15-MAR-2019", "100", [("1", "13-MAR-2019", 500, 200)]),
    )
    rates = {
        r[0]: r[1:]
        for r in con.execute(
            "select year, lines_checked, lines_passed, rate from audit.g8_rate"
        ).fetchall()
    }
    assert rates == {"2019": (2, 1, 0.5), "total": (2, 1, 0.5)}
    assert final.check_price_check(con) == []  # W16
    assert final.check_priced_minimum(con, params) == []  # W17
