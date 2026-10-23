"""Price tests on the real warehouse (T020; plan §8.5 price tests). Marked slow."""

from datetime import date

import pytest

from sentinel import warehouse
from sentinel.config import Paths, repo_root

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def con():
    con = warehouse.connect(Paths.from_root(repo_root()), read_only=True)
    if not warehouse.table_exists(con, "core.price_daily"):
        pytest.skip("run `sentinel prices` first")
    yield con
    con.close()


def test_reverse_split_prices_are_as_traded_with_equal_dollar_volume(con):
    """On the session before a reverse split, as-traded = Yahoo × the split ratio (and any later
    ones), with the same dollar volume."""
    rows = con.execute(
        """
        with split as (
            select y.ticker, y.session as day, y.split_ratio from stg.price_yahoo y
            join core.price_series s
              on s.ticker = y.ticker and s.price_source = 'yahoo' and s.chosen
            where y.split_ratio < 1
            order by y.ticker, y.session limit 5
        ),
        before as (
            select s.ticker, s.split_ratio, max(d.session) as session from split s
            join core.price_daily d on d.ticker = s.ticker and d.price_source = 'yahoo'
                 and d.session < s.day
            group by all
        )
        select b.ticker, b.split_ratio, d.close, d.volume, d.cum_split_after, y.close, y.volume
        from before b
        join core.price_daily d on d.ticker = b.ticker and d.session = b.session
             and d.price_source = 'yahoo'
        join stg.price_yahoo y on y.ticker = b.ticker and y.session = b.session
        """
    ).fetchall()
    if not rows:
        pytest.skip("no reverse split among the chosen Yahoo series")
    for ticker, ratio, close, volume, cum, y_close, y_volume in rows:
        assert cum <= ratio + 1e-9, ticker  # the split (and any later ones) is undone
        assert close == pytest.approx(y_close * cum, rel=1e-6), ticker
        assert close * volume == pytest.approx(y_close * y_volume, rel=1e-4), ticker


def test_spy_calendar_matches_the_2024_exchange_calendar(con):
    sessions = [
        r[0]
        for r in con.execute(
            "select session from core.session where year(session) = 2024 order by 1"
        ).fetchall()
    ]
    assert len(sessions) == 252
    assert date(2024, 3, 29) not in sessions  # Good Friday
    assert date(2024, 7, 4) not in sessions  # Independence Day
    assert date(2024, 7, 5) in sessions
