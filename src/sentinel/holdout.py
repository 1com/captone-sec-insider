"""The holdout test (feature 010): the one test of the three approved models on the answers from
2023 on, sealed until now (constitution IV, D60; `specs/010-holdout-test/`).

- `freeze_levels` (once, before the test): the simpler levels of each question (V2-60) are re-run
  on the test years from the kept export the frozen models were built on (V2-59; research R1) and
  must reproduce the notebook's recorded numbers; then they are made for 2023 exactly as for a
  test year and recorded in MLflow (`frozen-levels`).
- `check` (any time): the guard and the 2023+ feature rows; no answer is computed.
- `run` (once, 16 November): the guard; the 2023+ answers in memory, by the development label
  functions with the end date moved to the newest session; every level and the frozen model scored
  per calendar year and over all; the records for the model report (008 contract) and one log
  entry. A second run is refused.
"""

import hashlib
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import joblib
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient

from sentinel import config, db, eda
from sentinel.config import Paths
from sentinel.labels import lock
from sentinel.labels import risk as labels
from sentinel.models import dilution, levels, report, results_move, volatility

KEPT = "2026-11-09"  # the export the frozen models were built on (V2-59, research R1)
TARGET = eda.DEV_END.year + 1  # 2023: the holdout's first year
START = pd.Timestamp(TARGET, 1, 1)
EXPERIMENT = report.HOLDOUT_EXPERIMENT
DECIDING = {"dilution": "log_loss", "results_move": "log_loss_mean", "volatility": "mae_log"}
TOLERANCE = 1e-9  # the packaged levels must reproduce the notebooks' records to this


class Refused(RuntimeError):
    """The guard refused: the reason says what is missing or what already happened."""


def kept(p: Paths) -> Path:
    """The kept export (research R1)."""
    return p.exports.parent / "frozen" / KEPT / "ml"


def log_path(p: Paths) -> Path:
    """The append-only log of holdout runs: one entry is the proof of the single run."""
    return p.exports.parent / "holdout" / "log.jsonl"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _uri(p: Paths) -> str:
    return f"sqlite:///{p.mlflow_db}"


def _commit(p: Paths) -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=p.root, capture_output=True, text=True)
    return out.stdout.strip()


def _download(run, name: str, uri: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = mlflow.artifacts.download_artifacts(
            run_id=run.info.run_id, artifact_path=name, dst_path=tmp, tracking_uri=uri
        )
        return joblib.load(path)


# --- the frozen models and levels --------------------------------------------------------------


def frozen_models(p: Paths) -> dict:
    """Per question the frozen model of V2-59: the newest `frozen-…` run tagged approved from the
    same notebook execution (git commit) as the report record the model report shows."""
    uri, out = _uri(p), {}
    client = MlflowClient(tracking_uri=uri)
    records, _ = report.load_records(uri)
    for q, rec in records.items():
        commit = rec["run"].data.tags.get("git_commit", "")
        exp = client.get_experiment_by_name(report.QUESTIONS[q][0])
        runs = client.search_runs(
            [exp.experiment_id],
            filter_string=f"attributes.run_name LIKE 'frozen-%' and tags.git_commit = '{commit}'",
            order_by=["attributes.start_time DESC"],
        )
        runs = [r for r in runs if r.data.tags.get("frozen", "").startswith("approved")]
        if not runs:
            raise Refused(f"no approved frozen model for {q} from commit {commit[:7]} (V2-59)")
        run = runs[0]
        name = next(
            a.path for a in client.list_artifacts(run.info.run_id) if a.path.endswith(".joblib")
        )
        out[q] = {
            "model": _download(run, name, uri),
            "run": run,
            "commit": commit,
            "data_hash": run.data.tags.get("data_hash", ""),
            "export_date": run.data.tags.get("export_date", ""),
        }
    return out


def frozen_levels(p: Paths, models: dict) -> dict:
    """Per question the simpler levels of V2-60: the newest `frozen-levels` run, checked against
    the notebook's records, from the same data as the frozen model."""
    uri, out = _uri(p), {}
    client = MlflowClient(tracking_uri=uri)
    for q, m in models.items():
        exp = client.get_experiment_by_name(report.QUESTIONS[q][0])
        runs = client.search_runs(
            [exp.experiment_id],
            filter_string="attributes.run_name = 'frozen-levels' and tags.verified = 'true' "
            f"and tags.data_hash = '{m['data_hash']}'",
            order_by=["attributes.start_time DESC"],
            max_results=1,
        )
        if not runs:
            raise Refused(f"no frozen levels for {q}: run `sentinel holdout --freeze-levels` first")
        out[q] = {"levels": _download(runs[0], "levels.joblib", uri), "run": runs[0]}
    return out


# --- the guard -----------------------------------------------------------------------------------


def guard(p: Paths) -> None:
    """Refuse unless the registration lock holds and no holdout run exists (records or log)."""
    reason = lock.problem(p)
    if reason is not None:
        raise Refused(f"the registration lock does not hold: {reason}")
    if log_path(p).exists() and log_path(p).read_text().strip():
        raise Refused(f"the holdout test has already run ({log_path(p)}): a second run is refused")
    client = MlflowClient(tracking_uri=_uri(p))
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp is not None and client.search_runs([exp.experiment_id], max_results=1):
        raise Refused(f"experiment {EXPERIMENT} already holds a run: a second run is refused")


# --- freezing the simpler levels (once, before the test) ---------------------------------------


def _split_like(p: Paths) -> pd.DataFrame:
    """Dilution's split-like answers of the development rows (V2-39/40), kept beside the export."""
    path = kept(p).parent / "split_like.parquet"
    if path.exists():
        return pd.read_parquet(path)
    with duckdb.connect(
        str(p.build_db), read_only=True, config={"memory_limit": db.MEMORY_LIMIT}
    ) as con:
        split = dilution.split_like_answers(con)
    split.to_parquet(path, index=False)
    return split


def _compare(walk: pd.DataFrame, recorded: dict, q: str) -> float:
    """The largest difference between the packaged levels and the notebook's record; raises if any
    measure differs by more than `TOLERANCE`."""
    rec = pd.DataFrame(recorded["data"], columns=recorded["columns"])
    worst = 0.0
    for row in walk.itertuples(index=False):
        r = rec[(rec["level"] == row.level) & (rec["year"] == row.year)]
        if len(r) != 1:
            raise Refused(f"{q}: no recorded result for {row.level} {row.year}")
        for c in walk.columns.drop(["level", "year"]):
            a, b = getattr(row, c), r[c].iloc[0]
            if (a is None or pd.isna(a)) and (b is None or pd.isna(b)):
                continue
            diff = abs(float(a) - float(b))
            worst = max(worst, diff)
            if diff > TOLERANCE:
                raise Refused(
                    f"{q}: {row.level} {row.year} {c} is {a} here and {b} in the "
                    "notebook's record: the packaged level is not the notebook's"
                )
    return worst


def freeze_levels(p: Paths, echo=print) -> dict:
    """Prove the packaged simpler levels reproduce each notebook's recorded test years on the kept
    export, then make them for 2023 and record them (module docstring)."""
    guard(p)
    models = frozen_models(p)
    records, _ = report.load_records(_uri(p))
    folder, out = kept(p), {}
    for q in ("dilution", "results_move", "volatility"):
        path = folder / f"{q}.parquet"
        if not path.exists() or _hash(path) != models[q]["data_hash"]:
            raise Refused(
                f"{path} is missing or is not the export the frozen {q} model was built "
                f"on (data hash {models[q]['data_hash']})"
            )
        raw = eda.load(q, folder=folder)
        if q == "dilution":
            rows = dilution.learnable(raw, _split_like(p))
            expected = records[q]["tables"]["data"]["rows"]
            if len(rows) != expected:
                raise Refused(
                    f"dilution: {len(rows):,} learnable rows, the record has {expected:,}"
                )
            walk = levels.dilution_walk(rows, eda.TEST_YEARS)
            frozen = levels.dilution_fit(rows, TARGET, levels.dilution_linear(rows))
        elif q == "results_move":
            rows = levels.move_rows(raw)
            walk = levels.move_walk(rows, eda.TEST_YEARS)
            frozen = levels.move_fit(rows, TARGET, levels.move_linear(rows))
        else:
            rows = levels.vol_rows(raw)
            walk, frozen = levels.vol_walk_and_fit(rows, eda.TEST_YEARS, TARGET)
        worst = _compare(walk, records[q]["tables"]["results"], q)
        mlflow.set_tracking_uri(_uri(p))
        mlflow.set_experiment(report.QUESTIONS[q][0])
        with (
            tempfile.TemporaryDirectory() as tmp,
            mlflow.start_run(run_name="frozen-levels") as run,
        ):
            target = Path(tmp) / "levels.joblib"
            joblib.dump(frozen, target)
            mlflow.set_tags(
                {
                    "frozen": "levels (V2-60)",
                    "verified": "true",
                    "data_hash": models[q]["data_hash"],
                    "export_date": models[q]["export_date"],
                    "model_commit": models[q]["commit"],
                    "git_commit": _commit(p),
                    "levels": ",".join(frozen),
                    "largest_difference": f"{worst:.2e}",
                }
            )
            mlflow.log_artifact(str(target))
        out[q] = {"levels": list(frozen), "largest_difference": worst, "run": run.info.run_id}
        echo(
            f"  {q}: {len(walk)} level-years equal the notebook's record (largest difference "
            f"{worst:.1e}); levels {', '.join(frozen)} frozen for {TARGET}"
        )
        del raw, rows
    return out


# --- the 2023+ rows ------------------------------------------------------------------------------


def _feature_counts(con) -> dict:
    """The eligible 2023+ feature rows per question (no answer)."""
    sql = (
        "select count(*) filter (where month_end and eligible_volatility), "
        "count(*) filter (where month_end and eligible_dilution), "
        "count(*) filter (where release_eve and eligible) "
        f"from feature.snapshot where as_of >= DATE '{START.date()}'"
    )
    vol, dil, move = con.execute(sql).fetchone()
    return {"volatility": vol, "dilution": dil, "results_move": move}


def check(p: Paths, echo=print) -> dict:
    """Everything but the answers: the guard, the frozen models and levels, the 2023+ rows."""
    guard(p)
    models = frozen_models(p)
    lv = frozen_levels(p, models)
    try:
        with duckdb.connect(
            str(p.build_db), read_only=True, config={"memory_limit": db.MEMORY_LIMIT}
        ) as con:
            counts = _feature_counts(con)
            newest = con.execute(
                "select max(session) from stg_yahoo.price where ticker = 'SPY'"
            ).fetchone()[0]
    except duckdb.IOException as e:
        raise Refused(f"the build database is busy (the daily update?): {e}") from e
    for q, m in models.items():
        echo(
            f"  {q}: frozen model from commit {m['commit'][:7]}, data {m['data_hash']} (export "
            f"{m['export_date']}); levels {lv[q]['run'].data.tags.get('levels')}; "
            f"{counts[q]:,} eligible 2023+ feature rows"
        )
    echo(f"  the registration lock holds; no holdout run yet; data current to {newest}")
    return {"counts": counts, "newest": str(newest)}


def answers(con, rules: dict, echo=print) -> tuple[pd.DataFrame, pd.DataFrame, object]:
    """The 2023+ answers, in memory: the development label functions with the end date moved to
    the newest session (research R3). Returns the month-end answers, the results moves and the end
    date."""
    last_end = con.execute(
        "select max(session) from stg_yahoo.price where ticker = 'SPY' and adj_close > 0"
    ).fetchone()[0]
    gap = int(rules["labels"]["results_move"]["max_report_gap_days"])
    calendar = labels._days(
        con.execute("select session from ref.calendar order by 1").df()["session"]
    )
    spy = con.execute(
        "select session, adj_close from stg_yahoo.price where ticker = 'SPY' "
        "and adj_close > 0 order by 1"
    ).df()
    ciks = [
        r[0]
        for r in con.execute(
            "select distinct cik from feature.row where month_end or release_eve order by 1"
        ).fetchall()
    ]
    months, moves = [], []
    for i in range(0, len(ciks), labels.CHUNK):
        args = [ciks[i : i + labels.CHUNK]]
        within = "cik in (select unnest(?::VARCHAR[]))"
        daily = con.execute(
            "select cik, session, adj_close, cum_split_after from core.price_daily "
            f"where not glitch and adj_close > 0 and close > 0 and {within}",
            args,
        ).df()
        rows = con.execute(
            f"select cik, as_of from feature.row where month_end and {within} "
            f"and as_of >= DATE '{START.date()}'",
            args,
        ).df()
        shares = con.execute(
            "select cik, as_of as period_end, shares as value, filed "
            f"from core.shares_outstanding where {within}",
            args,
        ).df()
        for c in ("period_end", "filed"):
            shares[c] = pd.to_datetime(shares[c])
        releases = con.execute(
            f"select cik, filing_date, report_date from core.results_release where {within}", args
        ).df()
        months.append(
            labels.month_labels(daily, rows, calendar, labels.share_steps(shares), rules, last_end)
        )
        m = labels.results_moves(daily, releases, calendar, spy, last_end, gap)
        moves.append(m[pd.to_datetime(m["as_of"]) >= START])
        done = min(i + labels.CHUNK, len(ciks))
        if done % 4000 < labels.CHUNK or done == len(ciks):
            echo(f"  answers: {done:,}/{len(ciks):,} companies")
    return pd.concat(months), pd.concat(moves), last_end


# --- scoring --------------------------------------------------------------------------------------


def _by_year(rows: pd.DataFrame, out: dict, score) -> list[dict]:
    """The measures per calendar year and over all years."""
    result = []
    years = rows["as_of"].dt.year.to_numpy()
    for year in [*sorted(set(years)), "all"]:
        mask = np.ones(len(rows), bool) if year == "all" else years == year
        part = {
            k: (v[mask] if not isinstance(v, dict) else {e: a[mask] for e, a in v.items()})
            for k, v in out.items()
        }
        result.append({"year": str(year), **score(rows[mask], part)})
    return result


def _score_question(q: str, rows: pd.DataFrame, model, frozen: dict) -> dict:
    """Every level and the frozen model on the question's 2023+ rows: the results table and the
    chosen model's bands."""
    results, bands = [], []
    if q == "dilution":
        pred = dilution.predict(model, rows)
        chosen = {"p": pred["dilution_prob"].to_numpy()}
        outs = {name: levels.dilution_predict(lv, rows) for name, lv in frozen.items()}
        score = levels.dilution_scores
        band = pred["dilution_band"].astype(int).to_numpy()
        b = pd.DataFrame(
            {
                "year": rows["as_of"].dt.year.to_numpy(),
                "band": band,
                "forecast": chosen["p"],
                "real": rows[q].to_numpy(dtype=float),
            }
        )
        agg = {
            "rows": ("real", "size"),
            "forecast": ("forecast", "mean"),
            "real_rate": ("real", "mean"),
        }
    elif q == "results_move":
        score_ = model.chances(rows.assign(as_of=pd.to_datetime(rows["as_of"])))
        chosen = {"p": score_[1], "size": np.exp(score_[0])}
        outs = {name: levels.move_predict(lv, rows) for name, lv in frozen.items()}
        score = levels.move_scores
        band = results_move.predict(model, rows)["move_band"].astype(int).to_numpy()
        b = pd.DataFrame(
            {
                "year": rows["as_of"].dt.year.to_numpy(),
                "band": band,
                "forecast_10": chosen["p"][0.10],
                "real_5": (rows["move"] > 0.05).to_numpy(dtype=float),
                "real_10": (rows["move"] > 0.10).to_numpy(dtype=float),
                "real_20": (rows["move"] > 0.20).to_numpy(dtype=float),
                "move": rows["move"].to_numpy(),
            }
        )
        agg = {
            "releases": ("move", "size"),
            "forecast_10": ("forecast_10", "mean"),
            "real_5": ("real_5", "mean"),
            "real_10": ("real_10", "mean"),
            "real_20": ("real_20", "mean"),
            "median_move": ("move", "median"),
        }
    else:
        pred = volatility.predict(model, rows)
        chosen = {
            "forecast": np.log(pred["vol_forecast"].to_numpy(dtype=float)),
            "low": np.log(pred["vol_low_80"].to_numpy(dtype=float)),
            "high": np.log(pred["vol_high_80"].to_numpy(dtype=float)),
        }
        outs = {name: levels.vol_predict(lv, rows) for name, lv in frozen.items()}
        score = levels.vol_scores
        band = pred["vol_band"].astype(int).to_numpy()
        y = np.log(rows[volatility.ANSWER].to_numpy(dtype=float))
        b = pd.DataFrame(
            {
                "year": rows["as_of"].dt.year.to_numpy(),
                "band": band,
                "forecast": np.exp(chosen["forecast"]),
                "real": np.exp(y),
                "inside": ((y >= chosen["low"]) & (y <= chosen["high"])).astype(float),
            }
        )
        agg = {
            "rows": ("real", "size"),
            "median_forecast": ("forecast", "median"),
            "median_real": ("real", "median"),
            "coverage": ("inside", "mean"),
        }
    for name, out in [*outs.items(), (f"{getattr(model, 'level', 'model')} (chosen)", chosen)]:
        for r in _by_year(rows, out, score):
            results.append({"level": name, **r})
    for year, g in [*b.groupby("year", sort=True), ("all", b)]:
        t = g.groupby("band").agg(**agg).reset_index()
        bands.append(t.assign(year=str(year)))
    out = {"results": pd.DataFrame(results), "bands": pd.concat(bands)}
    if q == "volatility":  # the 80% range as the notebook's record shows it (008 contract)
        r, res = model.range.estimator, out["results"]
        mine = res[res["level"] == f"{model.level} (chosen)"]
        out["coverage"] = pd.DataFrame(
            {
                "year": mine["year"].to_numpy(),
                "low multiplier": np.exp(-r.q90_),
                "high multiplier": np.exp(-r.q10_),
                "history years": f"{model.history_years[0]}-{model.history_years[-1]}",
                "coverage": mine["coverage_80"].to_numpy(),
                "coverage, price-only": mine["coverage_price_only"].to_numpy(),
            }
        )
    return out


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].fillna(False).astype(bool)


def _question_rows(
    q: str, snap: pd.DataFrame, months: pd.DataFrame, moves: pd.DataFrame, split_like: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """The question's 2023+ rows, joined as the export joins the training files, with its
    development rules (eligibility, answers above 0, split-like answers dropped); and the counts of
    the rows left out (FR-005)."""
    month = snap[snap["month_end"]]
    if q == "results_move":
        eligible = int((snap["release_eve"] & _flag(snap, results_move.ELIGIBILITY)).sum())
        rows = results_move.learnable(snap.merge(moves, on=["cik", "as_of"]))
        return rows, {
            "eligible release eves": eligible,
            "no move (window open or closes missing)": eligible - len(rows),
            "scored": len(rows),
        }
    mod = volatility if q == "volatility" else dilution
    value, end = (mod.ANSWER, "vol_window_end" if q == "volatility" else "dilution_window_end")
    lab = months[months[end].notna()][["cik", "as_of", value, end]]
    raw = month.merge(lab.rename(columns={end: "window_end"}), on=["cik", "as_of"])
    answered = int((_flag(raw, mod.ELIGIBILITY) & raw[value].notna()).sum())
    eligible = int(_flag(month, mod.ELIGIBILITY).sum())
    rows = volatility.learnable(raw) if q == "volatility" else dilution.learnable(raw, split_like)
    dropped = "an answer of 0" if q == "volatility" else "a split-like answer"
    return rows, {
        "eligible month-ends": eligible,
        "no answer (window open or data missing)": eligible - answered,
        f"left out ({dropped})": answered - len(rows),
        "scored": len(rows),
    }


def run(p: Paths, echo=print) -> dict:
    """The one holdout test (module docstring)."""
    guard(p)
    models = frozen_models(p)
    frozen = frozen_levels(p, models)
    rules = config.risk_params(p)
    started = datetime.now(UTC).replace(microsecond=0)
    try:
        con = duckdb.connect(
            str(p.build_db), read_only=True, config={"memory_limit": db.MEMORY_LIMIT}
        )
    except duckdb.IOException as e:
        raise Refused(f"the build database is busy (the daily update?): {e}") from e
    with con:
        months, moves, last_end = answers(con, rules, echo)
        for c in ("as_of", "vol_window_end", "dilution_window_end"):
            months[c] = pd.to_datetime(months[c])
        for c in ("as_of", "filing_date", "report_date", "close_after"):
            moves[c] = pd.to_datetime(moves[c])
        yes = months[(months["dilution"] == 1) & months["dilution_window_end"].notna()]
        yes = yes[["cik", "as_of", "dilution_window_end"]].rename(
            columns={"dilution_window_end": "window_end"}
        )
        split_like = dilution.split_like_answers(con, yes)  # the development rule (V2-39/40)
        snap = con.execute(
            f"select * from feature.snapshot where as_of >= DATE '{START.date()}'"
        ).df()
    for c in eda.DATES:
        if c in snap:
            snap[c] = pd.to_datetime(snap[c])
    mlflow.set_tracking_uri(_uri(p))
    mlflow.set_experiment(EXPERIMENT)
    entry = {
        "run_date": started.isoformat(),
        "git_commit": _commit(p),
        "data_date": str(last_end),
        "questions": {},
    }
    # every question is scored first; the records and the log are written only when all three
    # are done, so a failure before that leaves nothing behind (and no result has been seen)
    scored = {}
    for q in ("dilution", "results_move", "volatility"):
        rows, counts = _question_rows(q, snap, months, moves, split_like)
        scored[q] = (rows, _score_question(q, rows, models[q]["model"], frozen[q]["levels"]))
        scored[q][1]["row_counts"] = counts
    texts = {}  # every record is written out before the first is stored
    for q, (rows, tables) in scored.items():
        holdout = {
            "question": q,
            "date": started.date().isoformat(),
            "data_date": str(last_end),
            "rows": len(rows),
            "first_row": str(rows["as_of"].min().date()),
            "last_row": str(rows["as_of"].max().date()),
            **{name: report._value(t) for name, t in tables.items()},
        }
        texts[q] = json.dumps(holdout, indent=1, ensure_ascii=False, allow_nan=False)
    summary = {}
    for q, (rows, tables) in scored.items():
        with tempfile.TemporaryDirectory() as tmp, mlflow.start_run(run_name=f"holdout-{q}") as r:
            path = Path(tmp) / "holdout.json"
            path.write_text(texts[q], encoding="utf-8")
            mlflow.set_tags(
                {
                    "holdout": "true",
                    "question": q,
                    "git_commit": entry["git_commit"],
                    "model_run": models[q]["run"].info.run_id,
                    "model_commit": models[q]["commit"],
                    "model_data_hash": models[q]["data_hash"],
                    "levels_run": frozen[q]["run"].info.run_id,
                    "data_date": str(last_end),
                }
            )
            mlflow.log_artifact(str(path))
        entry["questions"][q] = {
            "rows": len(rows),
            "record": r.info.run_id,
            "model_run": models[q]["run"].info.run_id,
        }
        res = tables["results"]
        summary[q] = res[res["year"] == "all"].set_index("level")[DECIDING[q]].to_dict()
    log_path(p).parent.mkdir(parents=True, exist_ok=True)
    with log_path(p).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    for q, s in summary.items():
        counts = scored[q][1]["row_counts"]
        echo(f"  {q}: " + "; ".join(f"{k}: {v:,}" for k, v in counts.items()))
        echo(f"  {q} ({DECIDING[q]}, 2023 on): " + "; ".join(f"{k} {v:.4f}" for k, v in s.items()))
    echo(
        f"  recorded in MLflow ({EXPERIMENT}) and logged in {log_path(p)}; "
        "run `sentinel report` to add the results to the model report"
    )
    return entry
