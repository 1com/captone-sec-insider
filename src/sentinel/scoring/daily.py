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

CURRENT_DAYS = 7  # a company is scored while its last snapshot row is this close to the newest


def _load_model(p: Paths, question: str):
    """The frozen model bundle saved by `sentinel train`. Missing is an error: a model is trained
    only by that command, never inside the daily update."""
    model_path = p.models / f"{question}.joblib"
    if not model_path.exists():
        raise FileNotFoundError(f"no frozen {question} model at {model_path}: `sentinel train`")
    module = {"results_move": results_move, "dilution": dilution, "volatility": volatility}
    return module[question].load(model_path)


def score_snapshot(
    con: duckdb.DuckDBPyConnection,
    p: Paths,
    echo: Callable[[str], None] = lambda _: None,
) -> dict[str, int]:
    """Score the companies still trading (their last snapshot row within `CURRENT_DAYS` of the
    newest) and record forecasts in score.daily. A company that stopped trading keeps a `latest`
    row from its last day (some from 2010); it gets no forecast."""
    schema.create_tables(con)

    snap_df = con.execute(
        "select * from feature.snapshot where latest and as_of >= "
        "(select max(as_of) from feature.snapshot where latest) - ?::integer order by cik",
        [CURRENT_DAYS],
    ).df()
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

    # 3. Results-Day Move (Feature 006, approved V2-55): the chances of a move above 5%, 10% and
    # 20%, in five bands by the chance above 10% (V2-53), which is the forecast value. A company's
    # earlier moves after 2022 are sealed until the holdout test (010), so its history is missing
    # here unless the rows carry it.
    model_res = _load_model(p, "results_move")
    history = {c: snap_df.get(c, np.nan) for c in results_move.HISTORY}
    pred_res_df = results_move.predict(model_res, snap_df.assign(**history))
    res_eligible = pred_res_df[pred_res_df["eligible"]].copy()

    if not res_eligible.empty:
        extras = [
            json.dumps(
                {
                    "p_move_5": float(p5),
                    "p_move_10": float(p10),
                    "p_move_20": float(p20),
                    "band_name": str(name),
                }
            )
            for p5, p10, p20, name in zip(
                res_eligible["p_move_5"],
                res_eligible["p_move_10"],
                res_eligible["p_move_20"],
                res_eligible["move_band_name"],
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
                "forecast_val": res_eligible["p_move_10"].astype(float),
                "band": res_eligible["move_band"].astype(int),
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
