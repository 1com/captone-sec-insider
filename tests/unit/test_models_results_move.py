"""The approved results-move model (006, V2-55) on a small synthetic panel: its inputs, the cutoff
of each step, the output the daily scores read, the order of the three chances, the guard, missing
history and determinism."""

import numpy as np
import pandas as pd
import pytest

from sentinel.models import results_move


@pytest.fixture(autouse=True)
def small_grid(monkeypatch):
    monkeypatch.setattr(results_move, "GRID", [{"num_leaves": 7, "min_child_samples": 20}])
    monkeypatch.setattr(results_move, "TREES", [20, 40])


def _raw(companies: int = 80, seed: int = 0) -> pd.DataFrame:
    """Quarterly releases 2015-2021; a company that moves a lot on ordinary days moves a lot on
    its results days."""
    rng = np.random.default_rng(seed)
    as_of = pd.date_range("2015-01-01", "2021-12-31", freq="QS") + pd.Timedelta(days=20)
    f = pd.DataFrame([(f"{c:04d}", d) for c in range(companies) for d in as_of],
                     columns=["cik", "as_of"])  # fmt: skip
    n, scale = len(f), np.repeat(np.exp(rng.normal(-1.0, 0.5, companies)), len(as_of))
    f["vol_63"] = scale * np.exp(rng.normal(0, 0.1, n))  # price: an input
    f["log_market_cap"] = rng.normal(20, 2, n)  # size: an input
    f["buy_value_12m"] = rng.normal(size=n)  # insider: an input for this question
    f["vix"] = rng.normal(20, 5, n)  # macro: an input for this question
    f["days_since_results"] = 90.0  # release timing: left out (V2-54)
    f["cum_split_after"] = 1.0  # look-ahead: left out
    f["sector"] = "Hlth"  # the current SIC: left out
    f["move"] = np.abs(rng.normal(0, 1, n)) * 0.25 * scale  # some releases above each event
    by = f.groupby("cik")["move"]
    f["prev4_mean"] = by.transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
    f["n_prev"] = f.groupby("cik").cumcount().astype(float)
    f["close_after"] = f["as_of"] + pd.Timedelta(days=2)
    f["eligible"] = True
    return f


def test_the_inputs_leave_out_timing_look_ahead_and_sector():
    assert results_move.features(_raw()) == [
        "vol_63", "log_market_cap", "buy_value_12m", "vix", "prev4_mean", "n_prev"]  # fmt: skip


def test_learnable_keeps_eligible_releases_with_a_move_sorted():
    raw = _raw(companies=3).sample(frac=1, random_state=0)
    raw.loc[raw.index[0], "move"] = np.nan
    raw.loc[raw.index[1], "eligible"] = False
    rows = results_move.learnable(raw)
    assert len(rows) == len(raw) - 2
    assert rows[["cik", "as_of"]].equals(rows[["cik", "as_of"]].sort_values(["cik", "as_of"]))
    assert all(rows[c].dtype == float for c in results_move.features(rows))


def test_each_step_keeps_its_cutoff():
    model = results_move.fit(results_move.learnable(_raw()), year=2021)
    assert model.forecast.cutoff == pd.Timestamp("2020-01-01")  # moves known before 2020
    cutoffs = {cal.cutoff for cal in model.calibrators.values()} | {model.bands.cutoff}
    assert cutoffs == {pd.Timestamp("2021-01-01")}
    assert model.trained_through < "2020-01-01" and model.setting["trees"] in (20, 40)
    assert model.level == "lightgbm" and model.eligibility_col == "eligible"


def test_predict_gives_the_contract_and_refuses_earlier_rows():
    rows = results_move.learnable(_raw())
    model = results_move.fit(rows, year=2021)
    late = rows[rows["as_of"].dt.year == 2021].copy()
    late.loc[late.index[:5], "eligible"] = False
    out = results_move.predict(model, late)
    assert list(out.columns) == ["cik", "as_of", "eligible", "p_move_5", "p_move_10",
                                 "p_move_20", "move_band", "move_band_name"]  # fmt: skip
    assert out.index.equals(late.index) and out["p_move_10"].isna().sum() == 5
    scored = out[out["eligible"]]
    assert scored[results_move.CHANCES].stack().between(0, 1).all()
    assert ((scored["p_move_20"] <= scored["p_move_10"])
            & (scored["p_move_10"] <= scored["p_move_5"])).all()  # fmt: skip
    assert scored["move_band"].between(1, 5).all()
    assert set(scored["move_band_name"]) <= set(results_move.BAND_NAMES.values())
    with pytest.raises(AssertionError, match="dated before"):  # 2020: the calibrations' year
        results_move.predict(model, rows[rows["as_of"].dt.year == 2020])


def test_a_bigger_forecast_never_lowers_a_chance():
    rows = results_move.learnable(_raw())
    model = results_move.fit(rows, year=2021)
    frame = pd.DataFrame({"as_of": pd.Timestamp("2021-06-30"), "score": np.linspace(-6, 0, 50)})
    for cal in model.calibrators.values():
        assert np.all(np.diff(cal.predict(frame)) >= 0)


def test_missing_history_and_columns():
    rows = results_move.learnable(_raw())
    model = results_move.fit(rows, year=2021)
    late = rows[rows["as_of"].dt.year == 2021].assign(prev4_mean=np.nan, n_prev=np.nan)
    out = results_move.predict(model, late)  # earlier moves sealed: still scored
    assert out[results_move.CHANCES].notna().all().all()
    with pytest.raises(KeyError, match="vix"):
        results_move.predict(model, late.drop(columns=["vix"]))


def test_two_fits_and_a_saved_model_give_identical_chances(tmp_path):
    rows = results_move.learnable(_raw())
    late = rows[rows["as_of"].dt.year == 2021]
    first = results_move.predict(results_move.fit(rows, year=2021), late)
    model = results_move.fit(rows, year=2021)
    pd.testing.assert_frame_equal(first, results_move.predict(model, late))
    path = tmp_path / "results_move.joblib"
    results_move.save(model, path)
    pd.testing.assert_frame_equal(first, results_move.predict(results_move.load(path), late))


def test_a_given_setting_is_the_only_one_fitted():
    rows = results_move.learnable(_raw())
    setting = {"params": {"num_leaves": 7, "min_child_samples": 20}, "trees": 20}
    model = results_move.fit(rows, year=2021, cols=["vol_63", "prev4_mean"], setting=setting)
    assert model.setting == setting and model.features == ["vol_63", "prev4_mean"]
    assert list(model.tried) == ["{'num_leaves': 7, 'min_child_samples': 20} 20"]
