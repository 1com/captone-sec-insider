"""The model report and the model card data (feature 008), generated from the records the approved
model notebooks write (`specs/008-model-report/contracts/report-record.md`).

Each notebook's last code cell calls `record`: one MLflow run named `report` in its experiment,
with the notebook's tables as one artifact `report.json`. `generate_report` reads the newest
record of each question that is not a trial, and the holdout records of feature 010 when they
exist, and writes `docs/report/model_report.md`, its figures and `docs/report/model_card.json`.
No number is typed in here: every number comes from a record, every definition from
`config/risk_params.yaml`. It fits nothing, and the same records give byte-identical files.
"""

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402

from sentinel import config  # noqa: E402
from sentinel.config import Paths  # noqa: E402

# question: experiment, feature, title, notebook (in the product's order, D62)
QUESTIONS = {
    "dilution": ("007-dilution", "007", "Dilution", "notebooks/007-dilution-model.ipynb"),
    "results_move": (
        "006-results-move",
        "006",
        "Results-day move",
        "notebooks/006-results-move-model.ipynb",
    ),
    "volatility": ("005-volatility", "005", "Volatility", "notebooks/005-volatility-model.ipynb"),
}
HOLDOUT_EXPERIMENT = "010-holdout"
COUNTS = ("rows", "releases", "inputs")  # count columns: summed when pooling, shown as integers


class MissingRecords(RuntimeError):
    """A question has no report record: its notebook has not been run (with its recording cell)."""


# --- writing a record (the notebooks) ---


def _plain(v):
    """A JSON value: numbers as numbers, missing as null, dates as ISO text."""
    if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and not np.isfinite(v)):
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if v == v.normalize() else v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v if isinstance(v, str) else str(v)


def _value(obj):
    """Tables as {"columns", "data"}; dicts and lists element by element."""
    if isinstance(obj, pd.Series):
        obj = obj.to_frame()
    if isinstance(obj, pd.DataFrame):
        # a named index (year, level, hypothesis) is a column; an unnamed one is row numbers
        named = isinstance(obj.index, pd.MultiIndex) or obj.index.name is not None
        frame = obj.reset_index() if named else obj.reset_index(drop=True)
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in frame.columns]
        return {
            "columns": cols,
            "data": [[_plain(v) for v in row] for row in frame.itertuples(index=False)],
        }
    if isinstance(obj, dict):
        return {str(k): _value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_value(v) for v in obj]
    return _plain(obj)


def record(question: str, tables: dict, tags: dict) -> str:
    """Write one report record: an MLflow run named `report` in the active experiment, tagged
    `report=true`, `question` and `tags` (`trial` defaults to False), with `tables` as the artifact
    `report.json`. Returns the run id."""
    if question not in QUESTIONS:
        raise ValueError(f"unknown question {question!r}")
    payload = {"question": question, **{k: _value(v) for k, v in tables.items()}}
    text = json.dumps(payload, indent=1, ensure_ascii=False, allow_nan=False)
    run_tags = {**{k: str(v) for k, v in tags.items()}, "report": "true", "question": question}
    run_tags["trial"] = str(tags.get("trial", "False"))
    with tempfile.TemporaryDirectory() as tmp, mlflow.start_run(run_name="report") as run:
        mlflow.set_tags(run_tags)
        path = Path(tmp) / "report.json"
        path.write_text(text, encoding="utf-8")
        mlflow.log_artifact(str(path))
        return run.info.run_id


# --- reading the records ---


def _newest(client: MlflowClient, experiment: str, filter_string: str):
    exp = client.get_experiment_by_name(experiment)
    if exp is None:
        return None
    runs = client.search_runs(
        [exp.experiment_id],
        filter_string=filter_string,
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    return runs[0] if runs else None


def _artifact(run, name: str, uri: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = mlflow.artifacts.download_artifacts(
            run_id=run.info.run_id, artifact_path=name, dst_path=tmp, tracking_uri=uri
        )
        return json.loads(Path(path).read_text(encoding="utf-8"))


def load_records(tracking_uri: str) -> tuple[dict, dict]:
    """Per question the newest report record that is not a trial (its tables and its run), and the
    newest holdout record of feature 010 when one exists. A missing record raises
    `MissingRecords` naming the notebooks to run."""
    client = MlflowClient(tracking_uri=tracking_uri)
    records, holdouts, missing = {}, {}, []
    for q, (experiment, _, _, notebook) in QUESTIONS.items():
        run = _newest(
            client,
            experiment,
            "attributes.run_name = 'report' and tags.report = 'true' and tags.trial = 'False'",
        )
        if run is None:
            missing.append(f"{q} ({notebook})")
            continue
        records[q] = {"run": run, "tables": _artifact(run, "report.json", tracking_uri)}
        hold = _newest(
            client, HOLDOUT_EXPERIMENT, f"tags.holdout = 'true' and tags.question = '{q}'"
        )
        if hold is not None:
            holdouts[q] = {"run": hold, "tables": _artifact(hold, "holdout.json", tracking_uri)}
    if missing:
        raise MissingRecords(
            "no report record for " + ", ".join(missing) + ": run the notebook(s) "
            "start to finish first (specs/008-model-report/quickstart.md)"
        )
    return records, holdouts


# --- rendering ---


def _frame(table: dict) -> pd.DataFrame:
    return pd.DataFrame(table["data"], columns=table["columns"])


def _cell(v, column: str = "") -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int) or (isinstance(v, float) and column in COUNTS and float(v).is_integer()):
        return f"{int(v):,}" if column != "year" else str(int(v))
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v).replace("|", "\\|").replace("\n", " ")


def _md(frame: pd.DataFrame) -> str:
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame.itertuples(index=False):
        cells = [
            _cell(v.item() if hasattr(v, "item") else v, c) for v, c in zip(row, cols, strict=True)
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _pivot(results: pd.DataFrame, measure: str, levels: list) -> pd.DataFrame:
    """Level × test year for one measure, with the mean of the years."""
    t = results.pivot(index="level", columns="year", values=measure)
    t = t.reindex([lv for lv in levels if lv in t.index])
    t.columns = [str(int(c)) for c in t.columns]
    t["mean"] = t.mean(axis=1)
    return t.reset_index()


def _pooled(bands: pd.DataFrame) -> pd.DataFrame:
    """The bands over all test years: counts summed, shares and means weighted by the rows;
    medians are kept per year only (they do not pool)."""
    count = next(c for c in bands.columns if c in COUNTS)
    keep = [c for c in bands.columns if c not in ("year", "band", count) and "median" not in c]
    out = []
    for band, g in bands.groupby("band", sort=True):
        w = g[count].astype(float)
        row = {"band": int(band), count: int(w.sum())}
        for c in keep:
            row[c] = float(np.average(g[c].astype(float), weights=w))
        out.append(row)
    return pd.DataFrame(out)


def _figure(path: Path) -> None:
    plt.tight_layout()
    plt.savefig(path, dpi=110, metadata={"Software": None})
    plt.close("all")


def _figures(q: str, t: dict, out: Path) -> list[str]:
    """The deciding measure by level and year, and the calibration (or forecast against real)."""
    names = []
    res, measure = _frame(t["results"]), t["deciding"]["measure"]
    plt.figure(figsize=(7, 4))
    for level in t.get("reference", []) + t["levels"]:
        g = res[res["level"] == level].sort_values("year")
        style = "--" if level in t.get("reference", []) else "-"
        plt.plot(g["year"].astype(int), g[measure], style, marker="o", label=level)
    plt.xticks(sorted(res["year"].astype(int).unique()))
    plt.ylabel(t["deciding"]["label"])
    plt.title(f"{QUESTIONS[q][2]}: {t['deciding']['label']} per test year (lower is better)")
    plt.legend()
    names.append(f"figures/{q}_results.png")
    _figure(out / names[-1])
    cal = _frame(t["calibration"])
    events = list(pd.unique(cal["event"])) if "event" in cal.columns else [None]  # as recorded
    fig, axes = plt.subplots(1, len(events), figsize=(5 * len(events), 4.4), squeeze=False)
    for ax, event in zip(axes[0], events, strict=True):
        c = cal if event is None else cal[cal["event"] == event]
        top = float(max(c["forecast"].max(), c["real"].max()))
        ax.plot([0, top], [0, top], color="grey", lw=1, ls="--")
        for year, g in c.groupby("year", sort=True):
            ax.plot(g["forecast"], g["real"], marker="o", ms=3, label=str(int(year)))
        ax.set_xlabel("forecast (ten groups)")
        ax.set_ylabel("real")
        if event is not None:
            ax.set_title(str(event))
        ax.legend(fontsize=8)
    fig.suptitle(f"{QUESTIONS[q][2]}: {t.get('calibration_title', 'calibration')}")
    names.append(f"figures/{q}_calibration.png")
    _figure(out / names[-1])
    return names


def _source(run) -> dict:
    tags = run.data.tags
    return {
        "experiment": tags.get("mlflow.experimentName", ""),
        "run": run.info.run_id,
        "git_commit": tags.get("git_commit", ""),
        "export_date": tags.get("export_date", ""),
        "data_hash": tags.get("data_hash", ""),
    }


def _section(n: int, q: str, rec: dict, hold: dict | None, labels: dict, out: Path) -> str:
    t, run = rec["tables"], rec["run"]
    experiment, feature, title, notebook = QUESTIONS[q]
    src = _source(run)
    src["experiment"] = experiment
    res, levels = _frame(t["results"]), t["levels"]
    shown = t.get("reference", []) + levels  # reference rows (the base rates) shown as the floor
    measure, label = t["deciding"]["measure"], t["deciding"]["label"]
    lines = [
        f"## {n}. {title} ({feature})",
        "",
        f"*Record: experiment `{experiment}`, run `{src['run']}`, "
        f"commit `{src['git_commit'][:7]}`, export of {src['export_date']}, "
        f"data hash `{src['data_hash']}`; from `{notebook}`. "
        f"Approved: {t.get('approved', '–')}.*",
        "",
        f"**The question.** {t.get('question_text', '')}",
        "",
        "**The answer, as pre-registered** (`config/risk_params.yaml`, labels):",
        "",
    ]
    lines += [f"- `{k}`: {v}" for k, v in labels.items()]
    lines += ["", "### The data", ""]
    lines += [
        f"- {k}: {_cell(v.item() if hasattr(v, 'item') else v, k)}"
        for k, v in t.get("data", {}).items()
    ]
    lines += [
        "",
        "### The method",
        "",
        "Four levels, simplest first: " + ", ".join(f"`{lv}`" for lv in levels) + ". Each "
        "learns only from rows whose answers were known before the year it is judged on "
        "(walk-forward test years, purged; every fitted step a `Dated`, V2-49); settings, "
        "calibration and band edges come from the year before; the simplest level within one "
        "standard error of the yearly gaps to the best is chosen (V2-50).",
        "",
        "Rows per test year:",
        "",
        _md(_frame(t["folds"])),
    ]
    if t.get("decisions"):
        lines += ["", "### The decisions that shaped the model", ""]
        lines += [f"- {d}" for d in t["decisions"]]
    lines += [
        "",
        f"### Results: {label} (deciding; lower is better)",
        "",
        _md(_pivot(res, measure, shown)),
    ]
    others = [
        c
        for c in res.columns
        if c not in ("level", "year", measure) and pd.api.types.is_numeric_dtype(res[c])
    ]
    for c in others:
        lines += ["", f"**{c}**", "", _md(_pivot(res, c, shown))]
    figs = _figures(q, t, out)
    lines += [
        "",
        f"![{title}: results per test year]({figs[0]})",
        "",
        "### The choice",
        "",
        _md(_frame(t["choice"])),
        "",
        f"Chosen: **`{t['chosen']}`** (V2-50). For reference, the textbook rule (one standard "
        f"error of the best level's own yearly scores) would choose `{t['textbook']}`.",
        "",
        f"### {t.get('calibration_title', 'Calibration').capitalize()}",
        "",
        f"![{title}: calibration]({figs[1]})",
        "",
        "### The bands",
        "",
        _md(_frame(t["bands"])),
        "",
        "Over the test years (counts summed, shares weighted by rows; medians per year only):",
        "",
        _md(_pooled(_frame(t["bands"]))),
    ]
    if "coverage" in t:
        lines += ["", "### The 80% range", "", _md(_frame(t["coverage"]))]
    lines += ["", "### The hypotheses (`docs/hypotheses.md`)", "", _md(_frame(t["hypotheses"]))]
    if "family_checks" in t:
        lines += [
            "",
            "Family checks (change in the deciding measure without the family, per test year):",
            "",
            _md(_frame(t["family_checks"])),
        ]
    for name, table in t.get("checks", {}).items():
        lines += ["", f"### Check: {name}", "", _md(_frame(table))]
    lines += ["", "### The frozen model", ""]
    lines += [f"- {k}: {v}" for k, v in t.get("frozen", {}).items()]
    lines += ["", "### The holdout test (010)", ""]
    if hold is None:
        lines += [
            "Not run yet: the guarded command of feature 010 runs it once (16 November 2026); "
            "its results will appear here as they came out."
        ]
    else:
        h = hold["tables"]
        lines += [
            f"*Run on {h.get('date', '–')} (experiment `{HOLDOUT_EXPERIMENT}`, run "
            f"`{hold['run'].info.run_id}`); {_cell(h.get('rows'))} rows; shown unedited.*",
            "",
        ]
        if "row_counts" in h:
            counts = "; ".join(f"{k}: {_cell(v)}" for k, v in h["row_counts"].items())
            lines += [f"Rows: {counts}", ""]
        for name in ("results", "bands", "coverage"):
            if name in h:
                lines += [f"**{name}**", "", _md(_frame(h[name])), ""]
    return "\n".join(lines)


def _card(q: str, rec: dict, hold: dict | None) -> dict:
    t = rec["tables"]
    res = _frame(t["results"])
    measure = t["deciding"]["measure"]
    simpler = t["levels"][: t["levels"].index(t["chosen"]) + 1]
    years = {
        str(int(y)): {
            lv: _plain(g.loc[g["level"] == lv, measure].iloc[0])
            for lv in simpler
            if (g["level"] == lv).any()
        }
        for y, g in res.groupby("year", sort=True)
    }
    bands = _frame(t["bands"])
    return {
        "title": QUESTIONS[q][2],
        "feature": QUESTIONS[q][1],
        "approved": t.get("approved"),
        "chosen": t["chosen"],
        "measure": {"name": measure, **{k: v for k, v in t["deciding"].items() if k != "measure"}},
        "test_years": years,
        "bands": _value(bands),
        "bands_pooled": _value(_pooled(bands)),
        "coverage": t.get("coverage"),
        "holdout": None if hold is None else hold["tables"],
        "source": {**_source(rec["run"]), "experiment": QUESTIONS[q][0]},
    }


def generate_report(
    p: Paths, tracking_uri: str | None = None, out: Path | None = None, echo=print
) -> Path:
    """Write the model report, its figures and the model card data from the records (module
    docstring). Returns the report's path."""
    uri = tracking_uri or f"sqlite:///{p.mlflow_db}"
    if tracking_uri is None and not p.mlflow_db.exists():
        raise MissingRecords(
            f"no MLflow store at {p.mlflow_db}: run the model notebooks first "
            "(specs/008-model-report/quickstart.md)"
        )
    records, holdouts = load_records(uri)
    out = out or p.root / "docs" / "report"
    (out / "figures").mkdir(parents=True, exist_ok=True)
    labels = config.risk_params(p)["labels"]
    summary = []
    for q, rec in records.items():
        t = rec["tables"]
        res = _frame(t["results"])
        m = res.groupby("level")[t["deciding"]["measure"]].mean()
        summary.append(
            {
                "question": f"{QUESTIONS[q][2]} ({QUESTIONS[q][1]})",
                "chosen": t["chosen"],
                "deciding measure (lower is better)": t["deciding"]["label"],
                "chosen, mean of the test years": float(m[t["chosen"]]),
                "simplest level": t["levels"][0],
                "simplest, mean": float(m[t["levels"][0]]),
                "approved": t.get("approved", "–"),
                "holdout": "run" if q in holdouts else "not run yet",
            }
        )
    head = [
        "# EDGAR-SENTINEL · Model report",
        "",
        "*Generated by `sentinel report` (feature 008) from the records the approved model "
        "notebooks wrote in MLflow; never edited by hand. Regenerate it with the commands of "
        "`specs/008-model-report/quickstart.md`. Every number below is an aggregate over many "
        "companies.*",
        "",
        "## Summary",
        "",
    ]
    head += [_md(pd.DataFrame(summary)), ""]
    body = [
        _section(i, q, rec, holdouts.get(q), labels[q], out)
        for i, (q, rec) in enumerate(records.items(), start=1)
    ]
    report = out / "model_report.md"
    report.write_text("\n".join(head) + "\n" + "\n\n".join(body) + "\n", encoding="utf-8")
    card = {q: _card(q, rec, holdouts.get(q)) for q, rec in records.items()}
    (out / "model_card.json").write_text(
        json.dumps(card, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    echo(
        f"Report saved to {report} (figures in {out / 'figures'}; model card data in "
        f"{out / 'model_card.json'})"
    )
    return report
