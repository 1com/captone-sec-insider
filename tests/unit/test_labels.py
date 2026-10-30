"""Layer 5: the risk labels on the synthetic market (conftest `build_world`); the lock."""

import math
from datetime import date

import numpy as np
import pytest
from conftest import WORLD_SESSIONS, build_world

from sentinel import build, db
from sentinel.labels import lock, risk

QUIET = {"echo": lambda s: None}


@pytest.fixture
def con(tmp_data):
    con = db.connect(tmp_data)
    build_world(con)
    build.run(con, tmp_data, "features", **QUIET)
    yield con
    con.close()


def test_labels_refuse_to_run_unless_the_registration_is_locked(con, tmp_data):
    with pytest.raises(db.StepFailed, match="prereg-risk-v5"):  # the copy is not a repository
        risk.build_labels(con, tmp_data, **QUIET)


def test_the_three_labels_follow_their_registered_definitions(con, tmp_data, monkeypatch):
    monkeypatch.setattr(lock, "require", lambda p: None)
    risk.build_labels(con, tmp_data, **QUIET)
    # volatility: company 2 alternates 10 and 10.1; the next 63 sessions' returns
    k = WORLD_SESSIONS.index(date(2019, 1, 31))
    adj = [10.0 * (1.01 if i % 2 else 1.0) for i in range(k, k + 64)]
    expected = np.std(np.diff(np.log(adj)), ddof=1) * math.sqrt(252)
    vol, end = con.execute(
        "select vol_63_future, window_end from label.volatility "
        "where cik = '2' and as_of = '2019-01-31'"
    ).fetchone()
    assert vol == pytest.approx(expected) and end == WORLD_SESSIONS[k + 63]
    # dilution: shares up 30% within 182 days in 2019; a 2-for-1 split in 2020 is not dilution
    dilution = dict(con.execute(
        "select as_of, dilution from label.dilution where cik = '1' "
        "and as_of in ('2019-05-31', '2020-05-29')").fetchall())  # fmt: skip
    assert dilution == {date(2019, 5, 31): 1.0, date(2020, 5, 29): 0.0}
    # results move: released 25 April 2019, from the close of the 24th to that of the 26th
    first = con.execute(
        "select as_of, close_after, move, prev4_mean, n_prev from label.results_move "
        "where cik = '1' order by filing_date limit 1"
    ).fetchone()
    move = abs((1.001**2 - 1) - (1.0005**2 - 1))
    assert first == (date(2019, 4, 24), date(2019, 4, 26), pytest.approx(move), None, 0)
    # every label window ends by the development cut-off; the world ends in 2021
    latest = con.execute(
        "select max(window_end) from label.volatility union all "
        "select max(close_after) from label.results_move"
    ).fetchall()
    assert all(d <= date(2022, 12, 31) for (d,) in latest)


def test_a_split_is_applied_where_the_share_counts_show_it():
    # V2-29, on three real cases read in their filings (notebooks/022-validation.ipynb)
    from sentinel.labels.risk import split_adjusted_before

    def ratio(counts, cums):
        c, s = np.array(counts, float), np.array(cums, float)
        return c[-1] / split_adjusted_before(c, s, 0, len(c) - 1)

    # Blackstone Mortgage Trust 2013: 1-for-10 reverse split in May, then a large share sale
    assert ratio([29.27e6, 2.93e6, 28.80e6], [0.1, 0.1, 1.0]) > 9
    # LookSmart 2013: 17,308,059 shares in every filing; the price series has a 1-for-3 split
    assert ratio([17.3e6, 17.3e6, 17.3e6], [1 / 3, 1 / 3, 1.0]) == 1.0
    # Medical Innovation 2016: counts already after the split the price series dates later
    assert abs(ratio([38.07e6, 38.42e6, 38.76e6], [0.1, 1.0, 1.0]) - 1.018) < 0.001
    # an ordinary split shown by both: no change in value
    assert ratio([100e6, 200e6], [2.0, 1.0]) == 1.0  # a 2-for-1 split
