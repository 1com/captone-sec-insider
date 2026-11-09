"""The approved dilution model (007, V2-52) on a small synthetic panel: its features, the cutoff of
each step, the output the daily scores read, the guard, determinism, and the split-like answers."""

import numpy as np
import pandas as pd
import pytest

from sentinel.models import dilution


@pytest.fixture(autouse=True)
def small_grid(monkeypatch):
    monkeypatch.setattr(dilution, "GRID", [{"num_leaves": 7, "min_child_samples": 20}])
    monkeypatch.setattr(dilution, "TREES", [20, 40])


def _raw(companies: int = 60, seed: int = 0) -> pd.DataFrame:
    """Month-end rows 2016-2021; an offering and a small market value raise the chance."""
    rng = np.random.default_rng(seed)
    as_of = pd.date_range("2016-01-31", "2021-12-31", freq="ME")
    f = pd.DataFrame([(f"{c:04d}", d) for c in range(companies) for d in as_of],
                     columns=["cik", "as_of"])  # fmt: skip
    n = len(f)
    f["n_offering_12m"] = rng.poisson(0.3, n).astype(float)
    f["log_market_cap"] = rng.normal(20, 2, n)
    f["buy_value_12m"] = rng.normal(size=n)  # insider: left out
    f["vix"] = rng.normal(20, 5, n)  # macro: left out
    f["cum_split_after"] = 1.0  # look-ahead: left out
    odds = -3 + 1.5 * (f["n_offering_12m"] > 0) - 0.3 * (f["log_market_cap"] - 20)
    f["dilution"] = (rng.random(n) < 1 / (1 + np.exp(-odds))).astype(float)
    f["window_end"] = f["as_of"] + pd.Timedelta(days=182)
    f["eligible_dilution"] = True
    return f


NONE = pd.DataFrame({"cik": pd.Series(dtype=str), "as_of": pd.Series(dtype="datetime64[ns]")})


def test_the_trees_leave_out_look_ahead_insider_and_macro():
    assert dilution.features(_raw()) == ["n_offering_12m", "log_market_cap"]


def test_each_step_keeps_its_cutoff():
    model = dilution.fit(dilution.learnable(_raw(), NONE), year=2021)
    assert model.trees.cutoff == pd.Timestamp("2020-01-01")  # answers known before 2020
    assert model.calibrator.cutoff == model.bands.cutoff == pd.Timestamp("2021-01-01")
    assert model.trained_through < "2020-01-01" and model.setting["trees"] in (20, 40)


def test_predict_gives_the_daily_scores_columns_and_refuses_earlier_rows():
    rows = dilution.learnable(_raw(), NONE)
    model = dilution.fit(rows, year=2021)
    late = rows[rows["as_of"].dt.year == 2021].copy()
    late.loc[late.index[:5], "eligible_dilution"] = False
    out = dilution.predict(model, late)
    assert list(out.columns) == ["cik", "as_of", "eligible", "dilution_prob", "dilution_band",
                                 "dilution_band_name"]  # fmt: skip
    assert out.index.equals(late.index) and out["dilution_prob"].isna().sum() == 5
    scored = out[out["eligible"]]
    assert scored["dilution_prob"].between(0, 1).all()
    assert scored["dilution_band"].between(1, 5).all()
    assert set(scored["dilution_band_name"]) <= set(dilution.BAND_NAMES.values())
    with pytest.raises(AssertionError, match="dated before"):  # 2020 rows: the calibration's year
        dilution.predict(model, rows[rows["as_of"].dt.year == 2020])


def test_two_fits_and_a_saved_model_give_identical_chances(tmp_path):
    rows = dilution.learnable(_raw(), NONE)
    late = rows[rows["as_of"].dt.year == 2021]
    first = dilution.predict(dilution.fit(rows, year=2021), late)
    model = dilution.fit(rows, year=2021)
    pd.testing.assert_frame_equal(first, dilution.predict(model, late))
    path = tmp_path / "dilution.joblib"
    dilution.save(model, path)
    pd.testing.assert_frame_equal(first, dilution.predict(dilution.load(path), late))


def test_learnable_rows_drop_split_like_answers_and_rows_without_answer_or_flag():
    raw = _raw(companies=3)
    raw.loc[0, "dilution"] = np.nan
    raw.loc[1, "eligible_dilution"] = False
    split_like = raw.loc[[2, 3], ["cik", "as_of"]]
    rows = dilution.learnable(raw, split_like)
    assert len(rows) == len(raw) - 4
    keys = rows.set_index(["cik", "as_of"]).index
    assert not keys.isin(split_like.set_index(["cik", "as_of"]).index).any()
