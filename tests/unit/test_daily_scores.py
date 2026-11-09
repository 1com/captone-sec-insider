"""Unit tests for daily scoring and live outcomes (Feature 009)."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import duckdb
import numpy as np
import pandas as pd
import pytest

from sentinel.config import Paths
from sentinel.scoring import daily, outcomes, schema


@pytest.fixture
def mock_paths(tmp_path: Path) -> Paths:
    models_dir = tmp_path / "data" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return Paths(
        root=tmp_path,
        data=tmp_path / "data",
        raw=tmp_path / "data" / "raw",
        manifest=tmp_path / "data" / "raw" / "manifest.jsonl",
        lock=tmp_path / "data" / "raw" / ".lock",
        sec_insider=tmp_path / "data" / "raw" / "sec" / "insider",
        sec_company=tmp_path / "data" / "raw" / "sec" / "company",
        sec_headers=tmp_path / "data" / "raw" / "sec" / "headers",
        sec_reference=tmp_path / "data" / "raw" / "sec" / "reference",
        sec_index=tmp_path / "data" / "raw" / "sec" / "index",
        sec_form4=tmp_path / "data" / "raw" / "sec" / "form4",
        sec_companyfacts=tmp_path / "data" / "raw" / "sec" / "companyfacts",
        sec_submissions=tmp_path / "data" / "raw" / "sec" / "submissions",
        yahoo=tmp_path / "data" / "raw" / "yahoo",
        tiingo=tmp_path / "data" / "raw" / "tiingo",
        fred=tmp_path / "data" / "raw" / "fred",
        cboe=tmp_path / "data" / "raw" / "cboe",
        finra=tmp_path / "data" / "raw" / "finra",
        french=tmp_path / "data" / "raw" / "french",
        build_db=tmp_path / "data" / "sentinel.duckdb",
        serving_db=tmp_path / "data" / "serving.duckdb",
        serving_prev=tmp_path / "data" / "serving.prev.duckdb",
        verify_db=tmp_path / "data" / "verify.duckdb",
        exports=tmp_path / "data" / "exports",
        models=models_dir,
        logs=tmp_path / "data" / "logs",
        update_lock=tmp_path / "data" / ".update.lock",
        mlflow_db=tmp_path / "data" / "mlflow.db",
        reports=tmp_path / "reports",
        sources_file=tmp_path / "config" / "sources.yaml",
        risk_params_file=tmp_path / "config" / "risk_params.yaml",
        tracker_file=tmp_path / "config" / "tracker.yaml",
        env_file=tmp_path / ".env",
    )


@pytest.fixture
def mock_db_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    schema.create_tables(con)
    con.execute("create schema if not exists feature")
    con.execute("create schema if not exists label")

    # Create synthetic feature.snapshot
    con.execute("""
        create table feature.snapshot (
            cik varchar,
            as_of date,
            latest boolean,
            coverage varchar,
            eligible boolean,
            eligible_volatility boolean,
            eligible_dilution boolean,
            sector varchar,
            vol_21d double,
            vol_63d double,
            ret_21d double,
            ret_63d double,
            shares_cagr_3y double
        )
    """)

    # Populate 3 active stocks:
    # 1. Standard US filer (full coverage, eligible for all 3 questions)
    # 2. Price-only stock (eligible_volatility only)
    # 3. Foreign filer (eligible for volatility and results_move, ineligible for dilution)
    today = date(2026, 10, 30)
    con.execute(f"""
        insert into feature.snapshot values
        ('0000000001', date '{today}', true, 'full', true, true, true,
         'Technology', 0.25, 0.28, 0.02, 0.05, 0.03),
        ('0000000002', date '{today}', true, 'price_only', false, true, false,
         'Unknown', 0.35, 0.38, -0.01, -0.03, null),
        ('0000000003', date '{today}', true, 'foreign', true, true, false,
         'Consumer', 0.18, 0.20, 0.01, 0.02, null),
        ('0000000004', date '2015-06-30', true, 'full', true, true, true,
         'Technology', 0.30, 0.31, 0.00, 0.01, 0.02)
    """)  # the fourth stopped trading in 2015: its latest row gets no forecast

    # Create synthetic label tables for outcome tracking
    con.execute("""
        create table label.volatility (
            cik varchar,
            as_of date,
            vol_63_future double,
            window_end date
        )
    """)
    con.execute("""
        create table label.dilution (
            cik varchar,
            as_of date,
            dilution integer,
            window_end date
        )
    """)
    con.execute("""
        create table label.results_move (
            cik varchar,
            as_of date,
            move double,
            close_after date
        )
    """)
    return con


def test_schema_creation():
    con = duckdb.connect(":memory:")
    schema.create_tables(con)
    tables = {r[0] for r in con.execute("select table_name from duckdb_tables()").fetchall()}
    assert "daily" in tables
    assert "outcome" in tables
    assert "registry" in tables
    con.close()


def test_daily_scoring_and_idempotence(mock_db_con, mock_paths):
    # Mock model predict calls to return deterministic predictions
    class DummyModel:
        level = "dummy_lgbm"
        eligibility_col = "eligible"

    def mock_vol_predict(m, rows):
        sub = rows[rows["eligible_volatility"]].copy()
        return pd.DataFrame(
            {
                "cik": sub["cik"],
                "as_of": sub["as_of"],
                "eligible": True,
                "vol_forecast": 0.285,
                "vol_low_80": 0.220,
                "vol_high_80": 0.350,
                "vol_band": 2,
                "vol_band_name": "2 · Low risk",
            }
        )

    def mock_dil_predict(m, rows):
        sub = rows[rows["eligible_dilution"]].copy()
        return pd.DataFrame(
            {
                "cik": sub["cik"],
                "as_of": sub["as_of"],
                "eligible": True,
                "dilution_prob": 0.042,
                "dilution_band": 2,
                "dilution_band_name": "2 · Low risk",
            }
        )

    def mock_res_predict(m, rows):
        assert {"prev4_mean", "n_prev"} <= set(rows.columns)  # history given, missing if sealed
        sub = rows[rows["eligible"]].copy()
        return pd.DataFrame(
            {
                "cik": sub["cik"],
                "as_of": sub["as_of"],
                "eligible": True,
                "p_move_5": 0.60,
                "p_move_10": 0.25,
                "p_move_20": 0.05,
                "move_band": 3,
                "move_band_name": "3 · Moderate risk",
            }
        )

    with (
        patch("sentinel.scoring.daily._load_model", return_value=DummyModel()),
        patch("sentinel.models.volatility.predict", side_effect=mock_vol_predict),
        patch("sentinel.models.dilution.predict", side_effect=mock_dil_predict),
        patch("sentinel.models.results_move.predict", side_effect=mock_res_predict),
    ):
        # First scoring run
        counts = daily.score_snapshot(mock_db_con, mock_paths)
        assert counts["volatility"] == 3  # All 3 stocks eligible for volatility
        assert counts["dilution"] == 1  # Only 0000000001 eligible for dilution (US filer)
        assert counts["results_move"] == 2  # Stocks 0000000001 and 0000000003 eligible

        total_rows = mock_db_con.execute("select count(*) from score.daily").fetchone()[0]
        assert total_rows == 6
        res = mock_db_con.execute(
            "select forecast_val, band, extra_json from score.daily where question = 'results_move'"
        ).fetchall()
        assert {(v, b) for v, b, _ in res} == {(0.25, 3)}  # the chance above 10% (V2-53)
        assert all('"band_name": "3' in extra and '"p_move_20": 0.05' in extra
                   for _, _, extra in res)  # fmt: skip

        # Second scoring run on the same date (Idempotence check)
        counts_second = daily.score_snapshot(mock_db_con, mock_paths)
        total_rows_second = mock_db_con.execute("select count(*) from score.daily").fetchone()[0]
        assert total_rows_second == 6  # No duplicate rows inserted!
        assert counts_second == counts


def test_a_missing_model_is_an_error_never_trained_in_the_update(mock_paths):
    with pytest.raises(FileNotFoundError, match="sentinel train"):
        daily._load_model(mock_paths, "volatility")
    assert list(mock_paths.models.iterdir()) == []


def test_outcome_tracking(mock_db_con):
    # Insert prior daily scores
    past_date = date(2022, 5, 1)
    extra_vol = '{"vol_low_80": 0.20, "vol_high_80": 0.32}'
    extra_dil = '{"band_name": "4 · Elevated risk"}'
    extra_res = '{"p_move_5": 0.7}'
    mock_db_con.execute(f"""
        insert into score.daily values
        ('0000000001', date '{past_date}', 'volatility', 'lgbm_v1', 0.25, 2, 'full',
         '{extra_vol}', timestamp '2022-05-01 16:00:00'),
        ('0000000001', date '{past_date}', 'dilution', 'lgbm_v1', 0.15, 4, 'full',
         '{extra_dil}', timestamp '2022-05-01 16:00:00'),
        ('0000000001', date '{past_date}', 'results_move', 'lgbm_v1', 0.35, 3, 'full',
         '{extra_res}', timestamp '2022-05-01 16:00:00')
    """)

    # Insert matching realized outcomes in labels
    mock_db_con.execute(f"""
        insert into label.volatility values
        ('0000000001', date '{past_date}', 0.265, date '2022-08-01')
    """)
    mock_db_con.execute(f"""
        insert into label.dilution values
        ('0000000001', date '{past_date}', 1, date '2022-11-01')
    """)
    mock_db_con.execute(f"""
        insert into label.results_move values
        ('0000000001', date '{past_date}', 0.12, date '2022-05-03')
    """)

    # Evaluate outcomes
    counts = outcomes.evaluate_outcomes(mock_db_con)
    assert counts["volatility"] == 1
    assert counts["dilution"] == 1
    assert counts["results_move"] == 1

    outcomes_df = mock_db_con.execute("select * from score.outcome order by question").df()
    assert len(outcomes_df) == 3

    # Check volatility outcome: 0.265 is between 0.20 and 0.32 -> is_hit is True
    vol_row = outcomes_df[outcomes_df["question"] == "volatility"].iloc[0]
    assert vol_row["is_hit"] is True or vol_row["is_hit"] == 1
    assert np.isclose(vol_row["error"], 0.25 - 0.265)

    # Check dilution outcome: forecast 0.15 (>= 0.10) and actual dilution == 1 -> is_hit is True
    dil_row = outcomes_df[outcomes_df["question"] == "dilution"].iloc[0]
    assert dil_row["is_hit"] is True or dil_row["is_hit"] == 1

    # Check results_move outcome: a 35% chance of a move above 10%, and the move was 12%: the
    # event happened (actual 1), so it counts in its band's real rate (D47)
    res_row = outcomes_df[outcomes_df["question"] == "results_move"].iloc[0]
    assert res_row["actual_val"] == 1.0 and np.isclose(res_row["error"], 0.35 - 1.0)
    assert res_row["is_hit"] is True or res_row["is_hit"] == 1
