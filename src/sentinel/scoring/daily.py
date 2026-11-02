"""Daily scoring engine for EDGAR-SENTINEL (Feature 009).

Loads the latest active feature snapshot, applies frozen models from `src/sentinel/models/`,
and records forecasts into `score.daily` in DuckDB.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb
import numpy as np
import pandas as pd

from sentinel.config import Paths
from sentinel.models import dilution, results_move, volatility
from sentinel.scoring import schema


def _load_model(p: Paths, question: str):
    """Load a frozen model bundle, or fit on development data if not yet saved."""
    model_path = p.models / f"{question}.joblib"
    if model_path.exists():
        if question == "results_move":
            return results_move.load(model_path)
        if question == "dilution":
            return dilution.load(model_path)
        if question == "volatility":
            return volatility.load(model_path)

    # Train and save frozen model on development data
    from sentinel import eda

    p.models.mkdir(parents=True, exist_ok=True)
    raw_df = eda.load(question)
    dev_df = raw_df[raw_df["as_of"] <= eda.DEV_END].copy()

    if question == "results_move":
        model = results_move.fit(dev_df, level="lightgbm")
        results_move.save(model, model_path)
        return model
    if question == "dilution":
        model = dilution.fit(dev_df, level="lightgbm")
        dilution.save(model, model_path)
        return model
    if question == "volatility":
        model = volatility.fit(dev_df, level="lightgbm")
        volatility.save(model, model_path)
        return model

    raise ValueError(f"Unknown question: {question}")


def score_snapshot(
    con: duckdb.DuckDBPyConnection,
    p: Paths,
    echo: Callable[[str], None] = lambda _: None,
) -> dict[str, int]:
    """Score the latest active feature snapshot and record forecasts in score.daily."""
    schema.create_tables(con)

    # Load latest snapshot from DuckDB
    snap_df = con.execute("select * from feature.snapshot where latest order by cik").df()
    if snap_df.empty:
        echo("  scoring: no latest feature snapshot rows found")
        return {"results_move": 0, "dilution": 0, "volatility": 0}

    now_ts = datetime.now(UTC).replace(tzinfo=None)
    counts = {}

    # 1. Expected Volatility (Feature 005)
    model_vol = _load_model(p, "volatility")
    pred_vol_df = volatility.predict(model_vol, snap_df)
    vol_eligible = pred_vol_df[pred_vol_df["eligible"]].copy()

    if not vol_eligible.empty:
        # Determine volatility risk band based on annualized volatility
        # Standard financial volatility bands:
        # Band 1: < 20% (low vol)
        # Band 2: 20% - 30% (moderate vol)
        # Band 3: 30% - 45% (elevated vol)
        # Band 4: 45% - 70% (high vol)
        # Band 5: > 70% (extreme / speculative vol)
        vol_edges = [0.20, 0.30, 0.45, 0.70]
        v_bands = np.digitize(vol_eligible["vol_forecast"].to_numpy(), vol_edges) + 1

        extras = [
            json.dumps({"vol_low_80": float(low), "vol_high_80": float(hi)})
            for low, hi in zip(vol_eligible["vol_low_80"], vol_eligible["vol_high_80"], strict=True)
        ]
        sub_cov = snap_df.loc[vol_eligible.index, "coverage"].fillna("full").tolist()

        vol_records = pd.DataFrame(
            {
                "cik": vol_eligible["cik"].astype(str),
                "as_of": pd.to_datetime(vol_eligible["as_of"]).dt.date,
                "question": "volatility",
                "model_version": f"{model_vol.level}_v1",
                "forecast_val": vol_eligible["vol_forecast"].astype(float),
                "band": v_bands.astype(int),
                "coverage": sub_cov,
                "extra_json": extras,
                "scored_at": now_ts,
            }
        )
        con.register("tmp_vol_scores", vol_records)
        con.execute("""
            insert into score.daily
            select * from tmp_vol_scores
            on conflict (cik, as_of, question, model_version)
            do update set
                forecast_val = excluded.forecast_val,
                band = excluded.band,
                coverage = excluded.coverage,
                extra_json = excluded.extra_json,
                scored_at = excluded.scored_at
        """)
        con.unregister("tmp_vol_scores")
        counts["volatility"] = len(vol_records)
    else:
        counts["volatility"] = 0

    # 2. Dilution Risk (Feature 007)
    model_dil = _load_model(p, "dilution")
    pred_dil_df = dilution.predict(model_dil, snap_df)
    dil_eligible = pred_dil_df[pred_dil_df["eligible"]].copy()

    if not dil_eligible.empty:
        extras = [
            json.dumps({"band_name": str(name)}) for name in dil_eligible["dilution_band_name"]
        ]
        sub_cov = snap_df.loc[dil_eligible.index, "coverage"].fillna("full").tolist()

        dil_records = pd.DataFrame(
            {
                "cik": dil_eligible["cik"].astype(str),
                "as_of": pd.to_datetime(dil_eligible["as_of"]).dt.date,
                "question": "dilution",
                "model_version": f"{model_dil.level}_v1",
                "forecast_val": dil_eligible["dilution_prob"].astype(float),
                "band": dil_eligible["dilution_band"].astype(int),
                "coverage": sub_cov,
                "extra_json": extras,
                "scored_at": now_ts,
            }
        )
        con.register("tmp_dil_scores", dil_records)
        con.execute("""
            insert into score.daily
            select * from tmp_dil_scores
            on conflict (cik, as_of, question, model_version)
            do update set
                forecast_val = excluded.forecast_val,
                band = excluded.band,
                coverage = excluded.coverage,
                extra_json = excluded.extra_json,
                scored_at = excluded.scored_at
        """)
        con.unregister("tmp_dil_scores")
        counts["dilution"] = len(dil_records)
    else:
        counts["dilution"] = 0

    # 3. Results-Day Move (Feature 006)
    model_res = _load_model(p, "results_move")
    pred_res_df = results_move.predict(model_res, snap_df)
    res_eligible = pred_res_df[pred_res_df["eligible"]].copy()

    if not res_eligible.empty:
        extras = [
            json.dumps(
                {
                    "p_move_5": float(p5),
                    "p_move_10": float(p10),
                    "p_move_20": float(p20),
                    "band_median": float(med),
                }
            )
            for p5, p10, p20, med in zip(
                res_eligible["p_move_5"],
                res_eligible["p_move_10"],
                res_eligible["p_move_20"],
                res_eligible["band_median"],
                strict=True,
            )
        ]
        sub_cov = snap_df.loc[res_eligible.index, "coverage"].fillna("full").tolist()

        res_records = pd.DataFrame(
            {
                "cik": res_eligible["cik"].astype(str),
                "as_of": pd.to_datetime(res_eligible["as_of"]).dt.date,
                "question": "results_move",
                "model_version": f"{model_res.level}_v1",
                "forecast_val": res_eligible["pred_move"].astype(float),
                "band": res_eligible["band"].astype(int),
                "coverage": sub_cov,
                "extra_json": extras,
                "scored_at": now_ts,
            }
        )
        con.register("tmp_res_scores", res_records)
        con.execute("""
            insert into score.daily
            select * from tmp_res_scores
            on conflict (cik, as_of, question, model_version)
            do update set
                forecast_val = excluded.forecast_val,
                band = excluded.band,
                coverage = excluded.coverage,
                extra_json = excluded.extra_json,
                scored_at = excluded.scored_at
        """)
        con.unregister("tmp_res_scores")
        counts["results_move"] = len(res_records)
    else:
        counts["results_move"] = 0

    echo(
        f"  daily scores: {counts['volatility']:,} volatility, "
        f"{counts['dilution']:,} dilution, {counts['results_move']:,} results_move"
    )
    return counts
