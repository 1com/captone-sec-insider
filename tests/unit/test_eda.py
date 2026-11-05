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
                "prev4_mean", "n_prev", "close_after", "sector", "cum_split_after"):  # fmt: skip
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


def _monthly(first="2016-01-31", last="2019-12-31", days=182) -> pd.DataFrame:
    """One row per month-end; its answer is known `days` later (the dilution window)."""
    as_of = pd.date_range(first, last, freq="ME")
    return pd.DataFrame({"as_of": as_of, "window_end": as_of + pd.Timedelta(days=days)})


def test_folds_cut_every_block_by_date():
    f = _monthly()
    fold = eda.folds(f, "dilution", [2019])[2019]
    months = {k: (f.as_of[m].min().strftime("%Y-%m"), f.as_of[m].max().strftime("%Y-%m"))
              for k, m in fold.items()}  # fmt: skip
    assert months == {"inner": ("2016-01", "2017-06"),  # answers known by Dec 2017
                      "gap": ("2017-07", "2017-12"),  # answers known during validation
                      "valid": ("2018-01", "2018-06"),  # answers known before 2019
                      "purged": ("2018-07", "2018-12"),  # answers known in 2019
                      "test": ("2019-01", "2019-12")}  # fmt: skip
    table = eda.check_folds(f, {2019: fold}, "dilution")
    assert table.loc[2019, "inner answers known by"] < pd.Timestamp("2018-01-01")
    counts = eda.purge_table(f, "window_end", [2019]).loc[2019]  # the EDA's counts agree
    assert int((fold["inner"] | fold["gap"] | fold["valid"]).sum()) == counts["train_rows"]
    assert (int(fold["purged"].sum()), int(fold["test"].sum())) == (counts["purged"], 12)


def test_check_folds_refuses_any_block_out_of_time_order():
    f = _monthly()
    for block, row in (("valid", "2018-08-31"), ("inner", "2017-09-30"), ("test", "2018-10-31")):
        fold = eda.folds(f, "dilution", [2019])[2019]
        leak = f.as_of == pd.Timestamp(row)  # an answer that lands in a later block
        fold = {k: (m | leak) if k == block else (m & ~leak) for k, m in fold.items()}
        with pytest.raises(AssertionError, match="2019"):
            eda.check_folds(f, {2019: fold}, "dilution")


def test_holdout_answers_and_missing_answers_are_in_no_block():
    f = _monthly(last="2023-06-30")
    f.loc[f.as_of >= "2022-07-01", "window_end"] = pd.NaT  # sealed: no answer in the export
    fold = eda.folds(f, "dilution", [2023])[2023]  # the frozen model's fold
    assert not fold["test"].any()
    eda.check_folds(f, {2023: fold}, "dilution")
    f.loc[f.as_of == "2022-08-31", "window_end"] = pd.Timestamp("2023-02-28")  # unsealed by error
    with pytest.raises(AssertionError, match="holdout"):
        eda.check_folds(f, eda.folds(f, "dilution", [2023]), "dilution")


def test_known_before_guards_every_fit():
    f = _monthly()
    eda.known_before(f[f.as_of <= "2017-06-30"], "dilution", "2018-01-01")
    with pytest.raises(AssertionError, match="not known before"):
        eda.known_before(f[f.as_of <= "2017-07-31"], "dilution", "2018-01-01")


def test_auc_and_lift():
    y = pd.Series([0, 0, 0, 1] * 25)
    score = pd.Series(np.arange(100.0))
    assert eda.auc(y, score) == pytest.approx(eda.auc(y, score))  # deterministic
    assert eda.auc(y, y.astype(float)) == 1.0
    assert eda.top_decile_lift(y, y.astype(float)) == pytest.approx(1 / 0.25)


def test_dev_end_and_test_years_follow_the_registration():
    assert date(2022, 12, 31) == eda.DEV_END
    assert eda.TEST_YEARS == [2019, 2020, 2021, 2022]
