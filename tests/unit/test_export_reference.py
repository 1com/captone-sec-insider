"""Unit tests for private reference datasets export (Feature 002)."""

import pandas as pd
import pytest

from sentinel import config


def test_reference_datasets_exist_and_match_ml_development():
    p = config.paths()
    ref_dir = p.exports / "reference"
    ml_dir = p.exports / "ml"

    if not (ref_dir / "volatility.parquet").exists():
        pytest.skip("Reference datasets not yet exported")

    for q in ["volatility", "dilution", "results_move"]:
        ref_file = ref_dir / f"{q}.parquet"
        ml_file = ml_dir / f"{q}.parquet"

        assert ref_file.exists(), f"Missing reference file: {ref_file}"
        assert ml_file.exists(), f"Missing ml file: {ml_file}"

        df_ref = pd.read_parquet(ref_file)
        df_ml = pd.read_parquet(ml_file)

        # 1. Check period column
        assert "period" in df_ref.columns
        periods = set(df_ref["period"].unique())
        assert periods == {"development", "gap", "holdout"}

        # 2. Check column count (training columns + period)
        assert len(df_ref.columns) == len(df_ml.columns) + 1

        # 3. Check development rows match ml training rows exactly
        dev_ref = df_ref[df_ref["period"] == "development"]
        msg = f"Dev count mismatch for {q}: {len(dev_ref)} vs {len(df_ml)}"
        assert len(dev_ref) == len(df_ml), msg
