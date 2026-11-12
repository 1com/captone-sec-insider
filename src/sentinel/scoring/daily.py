"""The daily dilution forecasts (009, dilution only; 026 FR-005, T018; decision V2-72).

Every weekday the daily update scores the companies still trading (their latest feature row within
`CURRENT_DAYS` of the newest) with the approved dilution model (V2-52): the frozen object the
holdout test scored (V2-59), loaded from MLflow by `holdout.frozen_models`, never a file from
`data/models/` (that folder holds Gemini's unapproved models of 2 Nov). Each forecast goes into
`score.daily`, a log with one row per company, day and model: the chance, the band and, in
`extra_json`, the band's name and every input with its value and contribution, largest first (the
reasons the app shows). A contribution is LightGBM's `pred_contrib`: how much the input moved the
company's chance up or down from the average, in the trees' log-odds. The model is registered as
approved in `model.registry`, and `sentinel publish` serves only approved models' forecasts.
Volatility and the results-day move are not scored (V2-61: the app shows neither).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb
import numpy as np
import pandas as pd

from sentinel.config import Paths
from sentinel.models import dilution
from sentinel.scoring import schema

QUESTION = "dilution"
CURRENT_DAYS = 7  # a company is scored while its last snapshot row is this close to the newest
ALGORITHM = "LightGBM (gradient-boosted trees), Platt-calibrated, five bands"
COLUMNS = ["cik", "as_of", "chance", "band", "band_name", "factors"]


def approved(p: Paths) -> dict:
    """The approved dilution model as `holdout.frozen_models` gives it: the model, its MLflow run,
    the commit, the data hash and the export date. Refuses if there is none (V2-59)."""
    from sentinel import holdout  # MLflow is imported only when scoring

    return holdout.frozen_models(p, (QUESTION,))[QUESTION]


def version(frozen: dict) -> str:
    """The model version stored with each forecast: the model's level and its frozen MLflow run."""
    return f"{frozen['model'].level}-{frozen['run'].info.run_id}"


def _value(v: float) -> float | None:
    return float(v) if np.isfinite(v) else None


def forecasts(model: dilution.DilutionModel, rows: pd.DataFrame) -> pd.DataFrame:
    """One row per eligible row of `rows` (same index): cik, as_of, the chance, the band and its
    name, and `factors`: every input as (feature, value, contribution), the largest contribution
    first (a missing value is None)."""
    pred = dilution.predict(model, rows)
    ok = pred["eligible"].to_numpy()
    if not ok.any():
        return pd.DataFrame(columns=COLUMNS)
    names = model.trees.features
    values = rows.loc[ok, names].astype(float).to_numpy()
    boost = model.trees.estimator
    contrib = boost.model_.booster_.predict(
        rows.loc[ok, names].astype(float), pred_contrib=True, num_iteration=boost.trees_
    )[:, : len(names)]  # the last column is the average, not an input
    factors = []
    for v, c in zip(values, contrib, strict=True):
        order = np.argsort(-np.abs(c), kind="stable")
        factors.append([(names[j], _value(v[j]), float(c[j])) for j in order])
    p = pred.loc[ok]
    return pd.DataFrame(
        {
            "cik": p["cik"],
            "as_of": p["as_of"],
            "chance": p["dilution_prob"].astype(float),
            "band": p["dilution_band"].astype(int),
            "band_name": p["dilution_band_name"].astype(str),
            "factors": factors,
        },
        index=p.index,
    )


def current_rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """The latest feature row of every company still trading. A company that stopped trading
    keeps a `latest` row from its last day (some from 2010); it gets no forecast."""
    rows = con.execute(
        "select * from feature.snapshot where latest and as_of >= "
        "(select max(as_of) from feature.snapshot where latest) - ?::integer order by cik",
        [CURRENT_DAYS],
    ).df()
    rows["as_of"] = pd.to_datetime(rows["as_of"])
    return rows


def score_snapshot(
    con: duckdb.DuckDBPyConnection,
    p: Paths,
    echo: Callable[[str], None] = lambda _: None,
    frozen: dict | None = None,
) -> dict[str, int]:
    """Score the companies still trading with the approved dilution model (`frozen`, else loaded
    from MLflow) and record the forecasts in score.daily; scoring the same day again replaces that
    day's rows, never duplicates them."""
    schema.create_tables(con)
    rows = current_rows(con)
    if rows.empty:
        echo("  dilution forecasts: no current feature rows")
        return {QUESTION: 0}
    frozen = frozen or approved(p)
    model, v = frozen["model"], version(frozen)
    f = forecasts(model, rows)
    now = datetime.now(UTC).replace(tzinfo=None)
    con.execute(
        "insert into model.registry values (?, ?, ?, ?::date, ?, 'approved', ?) "
        "on conflict do nothing",
        [QUESTION, v, ALGORITHM, model.trained_through, len(model.features), now],
    )
    records = pd.DataFrame(
        {
            "cik": f["cik"].astype(str),
            "as_of": pd.to_datetime(f["as_of"]).dt.date,
            "question": QUESTION,
            "model_version": v,
            "forecast_val": f["chance"].astype(float),
            "band": f["band"].astype(int),
            "coverage": rows.loc[f.index, "coverage"].fillna("full").astype(str),
            "extra_json": [
                json.dumps({"band_name": n, "factors": fs})
                for n, fs in zip(f["band_name"], f["factors"], strict=True)
            ],
            "scored_at": now,
        }
    )
    con.register("_dilution_scores", records)
    con.execute("""
        insert into score.daily
        select * from _dilution_scores
        on conflict (cik, as_of, question, model_version)
        do update set
            forecast_val = excluded.forecast_val,
            band = excluded.band,
            coverage = excluded.coverage,
            extra_json = excluded.extra_json,
            scored_at = excluded.scored_at
    """)
    con.unregister("_dilution_scores")
    echo(
        f"  dilution forecasts: {len(records):,} of {len(rows):,} companies still trading "
        f"(the others outside the question), model {v}"
    )
    return {QUESTION: len(records)}
