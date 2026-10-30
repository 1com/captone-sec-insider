"""Layer 4: the feature rows and families on a synthetic market (conftest `build_world`)."""

from datetime import date

import pytest
from conftest import WORLD_SESSIONS, build_world

from sentinel import build, db

QUIET = {"echo": lambda s: None}


@pytest.fixture
def con(tmp_data):
    con = db.connect(tmp_data)
    build_world(con)
    build.run(con, tmp_data, "features", **QUIET)
    yield con
    con.close()


def _row(con, cik: str, as_of: date, *cols: str) -> tuple:
    return con.execute(
        f"select {', '.join(cols)} from feature.snapshot where cik = ? and as_of = ?", [cik, as_of]
    ).fetchone()


def test_rows_are_month_ends_release_eves_and_each_companys_latest_day(con):
    kinds = con.execute(
        "select count(*) filter (where month_end), count(*) filter (where release_eve), "
        "count(*) filter (where latest) from feature.row where cik = '1'"
    ).fetchone()
    assert kinds == (36, 11, 1)  # 36 months, 11 results releases, 1 latest day
    eve = con.execute(
        "select as_of from feature.row where cik = '1' and release_eve order by 1 limit 1"
    ).fetchone()[0]
    assert eve == date(2019, 4, 24)  # the close before the 25 April 2019 release


def test_price_features_follow_the_adjusted_series_across_the_split(con):
    ret_1m, vol_63, close = _row(con, "1", date(2020, 7, 31), "ret_1m", "vol_63", "close")
    assert ret_1m == pytest.approx(1.001**21 - 1)  # the split does not show as a fall
    assert vol_63 == pytest.approx(0.0, abs=1e-9)
    day = WORLD_SESSIONS.index(date(2020, 7, 31))
    assert close == pytest.approx(10.0 * 1.001**day)  # as traded: after the split, the adjusted


def test_market_value_puts_a_pre_split_count_in_post_split_shares(con):
    shares, cap, close = _row(con, "1", date(2020, 7, 31), "shares_outstanding", "market_cap",
                              "close")  # fmt: skip
    assert shares == 2600.0  # 1,300 counted in April, before the 2-for-1 split
    assert cap == pytest.approx(close * 2600.0)


def test_financial_ratios_use_values_known_by_the_row_date(con):
    growth, runway, loss = _row(con, "1", date(2021, 3, 31), "revenue_growth",
                                "cash_runway_years", "loss_making")  # fmt: skip
    assert growth == pytest.approx(0.2)  # 2020's revenue against 2019's
    assert runway == pytest.approx(4.0)  # cash 2,000 over a yearly burn of 500
    assert loss == 1.0
    before = _row(con, "1", date(2021, 1, 29), "revenue_growth")[0]
    assert before is None  # 2020's revenue was filed on 1 February 2021


def test_offerings_skip_a_424b5_that_follows_a_term_sheet(con):
    assert _row(con, "1", date(2021, 4, 30), "n_offering_12m")[0] == 1


def test_insider_short_and_macro_values(con):
    cols = ("buy_value_12m", "sell_value_12m", "planned_sell_share_12m", "ceo_cfo_sold_12m",
            "buyers_14d")  # fmt: skip
    # the sale was filed on 30 June, so it is known only from the next session
    assert _row(con, "1", date(2021, 6, 30), *cols) == (50_000.0, 0.0, None, 0.0, 1)
    assert _row(con, "1", date(2021, 7, 30), *cols) == (50_000.0, 30_000.0, 1.0, 1.0, 0)
    short, change = _row(con, "1", date(2021, 6, 30), "short_ratio_1m", "short_ratio_chg")
    assert (short, change) == (pytest.approx(0.4), pytest.approx(0.0))
    vix, inflation = _row(con, "1", date(2021, 6, 30), "vix", "cpi_yoy")
    assert vix == 20.0 and inflation == pytest.approx(1.002**12 - 1)


def test_foreign_filers_have_no_insider_8k_or_market_value_features(con):
    cap, log_cap, buys, results_8k, ret = _row(con, "2", date(2021, 6, 30), "market_cap",
                                               "log_market_cap", "buy_value_12m",
                                               "n_exec_change_12m", "ret_1m")  # fmt: skip
    assert (cap, log_cap, buys, results_8k) == (None, None, None, None)  # market value: V2-22
    assert ret is not None


def test_rows_are_eligible_once_the_floors_and_history_are_met(con):
    assert _row(con, "1", date(2019, 1, 31), "eligible")[0] is False  # 21 price days so far
    assert _row(con, "1", date(2019, 6, 28), "eligible", "active_filer") == (True, True)
    assert _row(con, "2", date(2019, 1, 31), "active_filer")[0] is False  # no filing yet


def test_values_filed_on_the_calendars_last_day_wait_for_the_next_session(tmp_data):
    # their next trading day is not in the calendar yet, so they have no `known_at`
    con = db.connect(tmp_data)
    build_world(con)
    for table, end in (("core.financial_fact", "period_end"), ("core.shares_outstanding", "as_of")):
        con.execute(f"insert into {table} select * replace (null as known_at, "
                    f"({end} + interval 5 year)::date as {end}) from {table} "
                    "where cik = '1' limit 1")  # fmt: skip
    build.run(con, tmp_data, "features", **QUIET)
    assert con.execute("select count(*) from feature.fundamental where cik = '1'").fetchone()[0]
    con.close()
