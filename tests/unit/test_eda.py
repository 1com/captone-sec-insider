"""The EDA helpers (004) on small synthetic training sets: development rows only, feature families,
and the tables the three notebooks share."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from sentinel import eda


def _frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    as_of = pd.to_datetime(rng.choice(pd.date_range("2016-01-31", "2023-06-30", freq="ME"), n))
    x = rng.normal(size=n)
    return pd.DataFrame({
        "cik": rng.integers(1, 40, n).astype(str), "as_of": as_of, "eligible": rng.random(n) > 0.2,
        "active_filer": True, "excluded": False, "close": rng.uniform(0.5, 50, n),
        "addv20": rng.uniform(5_000, 1e6, n), "sessions_listed": rng.integers(10, 2000, n),
        "vol_63": np.exp(x), "vol_63_copy": np.exp(x) * 2, "ret_1m": rng.normal(size=n),
        "n_offering_12m": rng.integers(0, 3, n), "market_cap": rng.uniform(1e7, 5e10, n),
        "vol_63_future": np.exp(x + rng.normal(scale=0.3, size=n)),
        "window_end": as_of + pd.Timedelta(days=91),
    })  # fmt: skip


def test_load_keeps_only_development_rows(tmp_path, monkeypatch):
    _frame().to_parquet(tmp_path / "volatility.parquet")
    monkeypatch.setattr(eda, "EXPORT", tmp_path)
    rows = eda.load("volatility")
    assert rows["as_of"].max() <= pd.Timestamp(eda.DEV_END)
    assert rows[["cik", "as_of"]].equals(rows[["cik", "as_of"]].sort_values(["cik", "as_of"]))
    assert list(eda.load("volatility", columns=["vol_63"]).columns) == ["cik", "as_of", "vol_63"]


def test_every_feature_has_one_family_and_nothing_else_has_one():
    assert eda.family("vol_63") == "price" and eda.family("n_offering_12m") == "filing events"
    assert eda.family("short_ratio_1m") == "short volume" and eda.family("vix_chg_1m") == "macro"
    for col in ("cik", "as_of", "eligible", "vol_63_future", "move", "dilution", "window_end",
                "prev4_mean", "n_prev", "close_after", "sector"):  # fmt: skip
        assert eda.family(col) is None
    assert eda.features(_frame()) == ["close", "addv20", "sessions_listed", "vol_63", "ret_1m",
                                      "n_offering_12m", "market_cap"]  # fmt: skip


def test_size_bands():
    caps = pd.Series([1e8, 1e9, 5e9, 2e10, np.nan])
    assert list(eda.size_band(caps)) == ["micro", "small", "mid", "large", "unknown"]


def test_eligibility_reasons_explain_every_ineligible_row():
    f = pd.DataFrame({"eligible": [True, False, False], "active_filer": [True, False, True],
                      "excluded": [False, False, False], "close": [5.0, 5.0, 0.5],
                      "addv20": [1e5, 1e5, 1e5], "sessions_listed": [100, 100, 100]})  # fmt: skip
    reasons = eda.eligibility_reasons(f)
    assert reasons.loc["not an active filer", "rows"] == 1
    assert reasons.loc["close below $1", "rows"] == 1
    assert reasons.loc["no reason found", "rows"] == 0


def test_missing_and_extremes():
    f = pd.DataFrame({"a": [1.0, np.nan, np.nan, 4.0], "n_offering_12m": [0, -1, 2, 1],
                      "ret_1m": [0.1, np.inf, 0.0, -0.2]})  # fmt: skip
    assert eda.missing_table(f, ["a", "ret_1m"]).loc["a", "missing"] == 0.5
    ext = eda.extremes_table(f, ["n_offering_12m", "ret_1m"])
    assert ext.loc["n_offering_12m", "negative"] == 1 and ext.loc["ret_1m", "negative"] == 0
    assert ext.loc["ret_1m", "infinite"] == 1


def test_rank_decile_and_redundant_tables():
    f = _frame(2000)
    ranks = eda.rank_table(f, ["vol_63", "ret_1m"], "vol_63_future")
    assert ranks.index[0] == "vol_63" and ranks.loc["vol_63", "spearman"] > 0.8
    yearly = eda.rank_by_year(f, ["vol_63"], "vol_63_future")
    assert set(yearly.columns) == set(f["as_of"].dt.year.unique())
    deciles = eda.decile_table(f, "vol_63", "vol_63_future")
    assert len(deciles) == 10 and deciles["mean"].is_monotonic_increasing
    pairs = eda.redundant_pairs(f, ["vol_63", "vol_63_copy", "ret_1m"])
    assert list(map(tuple, pairs[["a", "b"]].to_numpy())) == [("vol_63", "vol_63_copy")]


def test_purge_drops_training_rows_whose_window_ends_in_the_test_year():
    as_of = pd.to_datetime(["2018-06-30", "2018-11-30", "2019-03-31"])
    ends = pd.to_datetime(["2018-09-30", "2019-02-28", "2019-06-30"])
    f = pd.DataFrame({"as_of": as_of, "window_end": ends})
    t = eda.purge_table(f, "window_end", [2019])
    assert (t.loc[2019, "train_rows"], t.loc[2019, "purged"], t.loc[2019, "test_rows"]) == (1, 1, 1)


def test_auc_and_lift():
    y = pd.Series([0, 0, 0, 1] * 25)
    score = pd.Series(np.arange(100.0))
    assert eda.auc(y, score) == pytest.approx(eda.auc(y, score))  # deterministic
    assert eda.auc(y, y.astype(float)) == 1.0
    assert eda.top_decile_lift(y, y.astype(float)) == pytest.approx(1 / 0.25)


def test_dev_end_and_test_years_follow_the_registration():
    assert date(2022, 12, 31) == eda.DEV_END
    assert eda.TEST_YEARS == [2019, 2020, 2021, 2022]
