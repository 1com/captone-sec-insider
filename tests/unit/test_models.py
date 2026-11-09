"""Unit tests for the volatility model (005) and the model commands; the approved results-move
(006) and dilution (007) models have their own test files."""

import numpy as np
import pandas as pd
import pytest

from sentinel.models import volatility


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
