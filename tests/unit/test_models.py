"""Unit tests for production models (005 Volatility, 006 Results Move, 007 Dilution)."""

import numpy as np
import pandas as pd
import pytest

from sentinel.models import dilution, results_move, volatility


@pytest.fixture
def mock_results_df() -> pd.DataFrame:
    np.random.seed(42)
    n = 120
    dates = pd.date_range("2018-01-01", periods=n, freq="30D")
    return pd.DataFrame(
        {
            "cik": [f"000000000{i % 5}" for i in range(n)],
            "as_of": dates,
            "close_after": dates + pd.Timedelta(days=2),
            "move": np.random.uniform(0.01, 0.25, size=n),
            "sector": np.random.choice(["Technology", "Healthcare", "Financials"], size=n),
            "eligible": [True] * n,
            "ret_21d": np.random.normal(0, 0.05, size=n),
            "vol_21d": np.random.uniform(0.15, 0.40, size=n),
            "prev4_mean": np.random.uniform(0.02, 0.20, size=n),
            "n_prev": np.random.choice([0, 1, 2, 3, 4], size=n),
        }
    )


@pytest.fixture
def mock_dilution_df() -> pd.DataFrame:
    np.random.seed(42)
    n = 150
    dates = pd.date_range("2018-01-01", periods=n, freq="25D")
    return pd.DataFrame(
        {
            "cik": [f"000000000{i % 6}" for i in range(n)],
            "as_of": dates,
            "window_end": dates + pd.Timedelta(days=180),
            "dilution": np.random.choice([0, 1], p=[0.85, 0.15], size=n),
            "eligible_dilution": [True] * n,
            "shares_cagr_3y": np.random.normal(0.05, 0.10, size=n),
            "vol_63d": np.random.uniform(0.15, 0.50, size=n),
            "ret_63d": np.random.normal(0.02, 0.10, size=n),
        }
    )


@pytest.fixture
def mock_volatility_df() -> pd.DataFrame:
    np.random.seed(42)
    n = 150
    dates = pd.date_range("2018-01-01", periods=n, freq="25D")
    return pd.DataFrame(
        {
            "cik": [f"000000000{i % 6}" for i in range(n)],
            "as_of": dates,
            "window_end": dates + pd.Timedelta(days=63),
            "vol_63_future": np.random.uniform(0.10, 0.60, size=n),
            "eligible_volatility": [True] * n,
            "vol_21d": np.random.uniform(0.12, 0.55, size=n),
            "vol_63d": np.random.uniform(0.15, 0.50, size=n),
            "ret_63d": np.random.normal(0.01, 0.08, size=n),
        }
    )


def test_results_move_model_train_predict(mock_results_df, tmp_path):
    feature_cols = ["ret_21d", "vol_21d", "prev4_mean", "n_prev"]
    val_year = 2022
    val_dates = pd.date_range("2022-01-10", periods=20, freq="15D")
    mock_results_df.loc[100:119, "as_of"] = val_dates
    mock_results_df.loc[100:119, "close_after"] = val_dates + pd.Timedelta(days=2)

    model = results_move.fit(
        mock_results_df,
        level="lightgbm",
        val_year=val_year,
        feature_cols=feature_cols,
        seed=42,
    )

    assert model.question == "results_move"
    assert len(model.band_edges) == 4

    # Test prediction
    preds = results_move.predict(model, mock_results_df.iloc[:20])
    assert len(preds) == 20
    assert (preds["p_move_5"] >= preds["p_move_10"]).all()
    assert (preds["p_move_10"] >= preds["p_move_20"]).all()
    assert preds["band"].between(1, 5).all()
    assert (preds["pred_move"] > 0).all()

    # Test serialization round-trip
    save_path = tmp_path / "results_move.joblib"
    results_move.save(model, save_path)
    loaded = results_move.load(save_path)
    preds_loaded = results_move.predict(loaded, mock_results_df.iloc[:20])
    pd.testing.assert_frame_equal(preds, preds_loaded)


def test_results_move_missing_declared_history(mock_results_df):
    feature_cols = ["ret_21d", "vol_21d", "prev4_mean", "n_prev"]
    val_dates = pd.date_range("2022-01-10", periods=20, freq="15D")
    mock_results_df.loc[100:119, "as_of"] = val_dates
    mock_results_df.loc[100:119, "close_after"] = val_dates + pd.Timedelta(days=2)

    model = results_move.fit(
        mock_results_df,
        level="lightgbm",
        val_year=2022,
        feature_cols=feature_cols,
        seed=42,
    )

    # Row without prev4_mean and n_prev (like latest.parquet)
    no_history_df = mock_results_df.iloc[:10].drop(columns=["prev4_mean", "n_prev"])
    preds = results_move.predict(model, no_history_df)
    assert not preds["pred_move"].isna().any()
    assert preds["band"].between(1, 5).all()


def test_dilution_model_train_predict(mock_dilution_df, tmp_path):
    feature_cols = ["shares_cagr_3y", "vol_63d", "ret_63d"]
    val_dates = pd.date_range("2022-01-15", periods=30, freq="10D")
    mock_dilution_df.loc[120:149, "as_of"] = val_dates
    mock_dilution_df.loc[120:149, "window_end"] = val_dates + pd.Timedelta(days=180)

    model = dilution.fit(
        mock_dilution_df,
        level="hist_gradient_boosting",
        val_year=2022,
        feature_cols=feature_cols,
        exclude_split_cases=False,
        seed=42,
    )

    assert model.question == "dilution"
    preds = dilution.predict(model, mock_dilution_df.iloc[:25])
    assert len(preds) == 25
    assert preds["dilution_prob"].between(0.0, 1.0).all()
    assert preds["dilution_band"].between(1, 5).all()
    assert not preds["dilution_band_name"].isna().any()

    # Serialization test
    save_path = tmp_path / "dilution.joblib"
    dilution.save(model, save_path)
    loaded = dilution.load(save_path)
    preds_loaded = dilution.predict(loaded, mock_dilution_df.iloc[:25])
    pd.testing.assert_frame_equal(preds, preds_loaded)


def test_volatility_model_train_predict(mock_volatility_df, tmp_path):
    feature_cols = ["vol_21d", "vol_63d", "ret_63d"]
    val_dates = pd.date_range("2022-01-15", periods=30, freq="10D")
    mock_volatility_df.loc[120:149, "as_of"] = val_dates
    mock_volatility_df.loc[120:149, "window_end"] = val_dates + pd.Timedelta(days=63)

    model = volatility.fit(
        mock_volatility_df,
        level="lightgbm",
        val_year=2022,
        feature_cols=feature_cols,
        seed=42,
    )

    assert model.question == "volatility"
    preds = volatility.predict(model, mock_volatility_df.iloc[:25])
    assert len(preds) == 25
    assert (preds["vol_forecast"] > 0).all()
    assert (preds["vol_low_80"] <= preds["vol_high_80"]).all()

    # Serialization test
    save_path = tmp_path / "volatility.joblib"
    volatility.save(model, save_path)
    loaded = volatility.load(save_path)
    preds_loaded = volatility.predict(loaded, mock_volatility_df.iloc[:25])
    pd.testing.assert_frame_equal(preds, preds_loaded)


def test_cli_models_validation():
    from typer.testing import CliRunner

    from sentinel.cli import app

    runner = CliRunner()
    res_train = runner.invoke(app, ["train", "nonexistent"])
    assert res_train.exit_code == 2
    assert "unknown question 'nonexistent'" in res_train.stderr

    res_score = runner.invoke(app, ["score", "nonexistent"])
    assert res_score.exit_code == 2
    assert "unknown question 'nonexistent'" in res_score.stderr

    res_score_file = runner.invoke(
        app, ["score", "results_move", "--input", "no_such_file.parquet"]
    )
    assert res_score_file.exit_code == 1
    assert "input file does not exist" in res_score_file.stderr
