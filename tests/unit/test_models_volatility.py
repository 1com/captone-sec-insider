"""The approved volatility model (005, V2-58) on a small synthetic panel: its inputs, the cutoff of
each step, the range set on earlier years' out-of-sample errors (V2-10), the output the daily
scores read, the guard and determinism."""

import numpy as np
import pandas as pd
import pytest

from sentinel.models import volatility


@pytest.fixture(autouse=True)
def small_grid(monkeypatch):
    monkeypatch.setattr(volatility, "GRID", [{"num_leaves": 7, "min_child_samples": 20}])
    monkeypatch.setattr(volatility, "TREES", [20, 40])
    monkeypatch.setattr(volatility, "FIRST_YEAR", 2017)


def _raw(companies: int = 40, seed: int = 0) -> pd.DataFrame:
    """Month ends 2014-2021; a stock's next three months swing like its last three, drifting back
    toward normal."""
    rng = np.random.default_rng(seed)
    as_of = pd.date_range("2014-01-31", "2021-12-31", freq="ME")
    f = pd.DataFrame([(f"{c:04d}", d) for c in range(companies) for d in as_of],
                     columns=["cik", "as_of"])  # fmt: skip
    n, scale = len(f), np.repeat(np.exp(rng.normal(-1.0, 0.4, companies)), len(as_of))
    f["vol_63"] = scale * np.exp(rng.normal(0, 0.2, n))  # price: an input
    f["log_market_cap"] = rng.normal(20, 2, n)  # size: an input
    f["buy_value_12m"] = rng.normal(size=n)  # insider: an input
    f["vix"] = rng.normal(20, 5, n)  # macro: left out (V2-57)
    f["cum_split_after"] = 1.0  # look-ahead: left out
    f["sector"] = "Hlth"  # the current SIC: left out
    f["vol_63_future"] = np.exp(-0.3 + 0.75 * np.log(f["vol_63"]) + rng.normal(0, 0.25, n))
    f["window_end"] = f["as_of"] + pd.Timedelta(days=91)
    f["eligible_volatility"] = True
    return f


def test_the_inputs_leave_out_macro_look_ahead_and_sector():
    raw = _raw()
    assert volatility.features(raw) == ["vol_63", "log_market_cap", "buy_value_12m"]
    assert volatility.all_features(raw) == ["vol_63", "log_market_cap", "buy_value_12m", "vix"]


def test_learnable_drops_zero_answers_and_ineligible_rows():
    raw = _raw(companies=3).sample(frac=1, random_state=0)
    raw.loc[raw.index[0], "vol_63_future"] = 0.0  # no logarithm
    raw.loc[raw.index[1], "eligible_volatility"] = False
    rows = volatility.learnable(raw)
    assert len(rows) == len(raw) - 2
    assert rows[["cik", "as_of"]].equals(rows[["cik", "as_of"]].sort_values(["cik", "as_of"]))


def test_each_step_keeps_its_cutoff_and_the_range_uses_earlier_years():
    rows = volatility.learnable(_raw())
    model = volatility.fit(rows, year=2021)
    assert model.forecast.cutoff == pd.Timestamp("2020-01-01")  # answers known before 2020
    assert model.range.cutoff == model.bands.cutoff == pd.Timestamp("2021-01-01")
    assert model.trained_through < "2020-01-01" and model.setting["trees"] in (20, 40)
    assert model.history_years == [2017, 2018, 2019, 2020]
    past = volatility.history(rows, 2021)
    errors = past.loc[past["window_end"] < "2021-01-01", "error"]
    q10, q90 = np.quantile(errors, [0.1, 0.9])
    assert np.isclose(model.range.estimator.q10_, q10)
    assert np.isclose(model.range.estimator.q90_, q90)
    assert q10 < 0 < q90


def test_predict_gives_the_contract_and_refuses_earlier_rows():
    rows = volatility.learnable(_raw())
    model = volatility.fit(rows, year=2021)
    late = rows[rows["as_of"].dt.year == 2021].copy()
    late.loc[late.index[:5], "eligible_volatility"] = False
    out = volatility.predict(model, late)
    assert list(out.columns) == ["cik", "as_of", "eligible", "vol_forecast", "vol_low_80",
                                 "vol_high_80", "vol_band", "vol_band_name"]  # fmt: skip
    assert out.index.equals(late.index) and out["vol_forecast"].isna().sum() == 5
    scored = out[out["eligible"]]
    assert ((scored["vol_low_80"] < scored["vol_forecast"])
            & (scored["vol_forecast"] < scored["vol_high_80"])).all()  # fmt: skip
    assert scored["vol_band"].between(1, 5).all()
    assert set(scored["vol_band_name"]) <= set(volatility.BAND_NAMES.values())
    with pytest.raises(AssertionError, match="dated before"):  # 2020: the range's year
        volatility.predict(model, rows[rows["as_of"].dt.year == 2020])
    with pytest.raises(KeyError, match="log_market_cap"):
        volatility.predict(model, late.drop(columns=["log_market_cap"]))


def test_a_given_history_gives_the_same_model(tmp_path):
    rows = volatility.learnable(_raw())
    late = rows[rows["as_of"].dt.year == 2021]
    first = volatility.predict(volatility.fit(rows, year=2021), late)
    model = volatility.fit(rows, year=2021, past=volatility.history(rows, 2021))
    pd.testing.assert_frame_equal(first, volatility.predict(model, late))
    path = tmp_path / "volatility.joblib"
    volatility.save(model, path)
    pd.testing.assert_frame_equal(first, volatility.predict(volatility.load(path), late))


def test_a_given_setting_is_the_only_one_fitted():
    rows = volatility.learnable(_raw())
    setting = {"params": {"num_leaves": 7, "min_child_samples": 20}, "trees": 20}
    fit = volatility.fit_forecast(rows, 2021, cols=["log_market_cap"], setting=setting)
    assert fit["setting"] == setting and list(fit["tried"]) == [
        "{'num_leaves': 7, 'min_child_samples': 20} 20"]  # fmt: skip
    assert fit["model"].features == ["log_market_cap", "vol_63"]  # past volatility: the start
