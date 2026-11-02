"""The `sentinel` command. Commands are added layer by layer (docs/architecture.md)."""

import sys
import time
from datetime import date

import duckdb
import typer

from sentinel import __version__

app = typer.Typer(name="sentinel", help="EDGAR-SENTINEL v2.", no_args_is_help=True)
OK, FAILED, USAGE, CONFIG = 0, 1, 2, 3


@app.callback()
def main() -> None:
    """EDGAR-SENTINEL v2: a market research platform for any US-traded stock."""


def _fail(message: str, code: int):
    typer.echo(message, err=True)
    raise typer.Exit(code)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


def _day(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"not a date (YYYY-MM-DD): {value!r}", USAGE)


@app.command()
def fetch(
    source: str = typer.Argument(..., help="sec-tickers, sec-daily, sec-bulk, form4, yahoo, "
                                 "tiingo, fred, cboe, finra, or all (every daily source)."),
    from_day: str = typer.Option(None, "--from", help="First filing or trading day, YYYY-MM-DD."),
    to_day: str = typer.Option(None, "--to", help="Last filing or trading day, YYYY-MM-DD."),
    full_missing: bool = typer.Option(False, "--full-missing",
                                      help="yahoo: also full histories of symbols never asked."),
    window_days: int = typer.Option(None, "--window-days", help="yahoo: days in the window."),
    quarterly: bool = typer.Option(False, "--quarterly",
                                   help="form4: the quarterly data sets instead."),
) -> None:  # fmt: skip
    """Download one source into data/raw/ (each file with a manifest line)."""
    from sentinel import config, raw
    from sentinel.raw.manifest import FetchLocked

    known = raw.fetchers()
    if source != "all" and source not in known:
        _fail(f"unknown source {source!r}; known: {', '.join([*known, 'all'])}", USAGE)
    options = {"from_day": _day(from_day), "to_day": _day(to_day), "full_missing": full_missing,
               "window_days": window_days, "quarterly": quarterly}  # fmt: skip
    options = {k: v for k, v in options.items() if v not in (None, False)}
    try:
        reports = raw.run(config.paths(), source, date.today(), typer.echo, **options)
    except config.ConfigError as e:
        _fail(f"fetch {source}: {e}", CONFIG)
    except FetchLocked as e:
        _fail(f"fetch {source}: {e}", FAILED)
    for report in reports:
        typer.echo(report.summary())
    if any(r.status == "failed" for r in reports):
        raise typer.Exit(FAILED)


@app.command()
def build(
    layer: str = typer.Argument(
        ..., help="The layer to rebuild: staging, reference, core, features, labels."
    ),
    only: str = typer.Option(None, "--only", help="Comma list of steps (default: all)."),
) -> None:
    """Rebuild a layer of data/sentinel.duckdb from the layer below it."""
    from sentinel import build as builder
    from sentinel import config, db

    if layer not in builder.LAYERS:
        _fail(f"unknown layer {layer!r}; known: {', '.join(builder.LAYERS)}", USAGE)
    try:
        p = config.paths()
        con = db.connect(p)
    except config.ConfigError as e:
        _fail(str(e), CONFIG)
    except duckdb.IOException as e:
        _fail(f"cannot open {config.paths().build_db.name} (in use?): {e}", FAILED)
    started = time.monotonic()
    try:
        results = builder.run(con, p, layer, only.split(",") if only else None, typer.echo)
    except builder.UnknownStep as e:
        _fail(f"build {layer}: {e}", USAGE)
    except (FileNotFoundError, db.MissingInput) as e:
        _fail(f"build {layer}: {e}", CONFIG)
    except db.StepFailed as e:
        _fail(f"build {layer}: {e}", FAILED)
    finally:
        con.close()
    for step, counts in results.items():
        typer.echo(f"  {step}: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    typer.echo(f"build {layer}: done in {time.monotonic() - started:,.0f}s")


@app.command()
def update(
    scheduled: bool = typer.Option(False, "--scheduled", help="Started by the schedule."),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Use the stored files only."),
) -> None:
    """The daily update: fetch what is new, rebuild, publish, record the run. Started by the
    schedule, it runs itself again under the memory cap (`update.memory_max`)."""
    from sentinel import config
    from sentinel.update import run as updater
    from sentinel.update import schedule as task

    notes: list[str] = []
    try:
        if scheduled:
            code = task.rerun_capped(config.paths(), sys.argv, notes.append)
            if code is not None:
                raise typer.Exit(code)
            for note in notes:
                typer.echo(note)
        result = updater.update(config.paths(), scheduled=scheduled, fetch=not no_fetch,
                                echo=typer.echo, notes=notes)  # fmt: skip
    except config.ConfigError as e:
        _fail(f"update: {e}", CONFIG)
    except (updater.UpdateLocked, updater.DiskFull) as e:
        _fail(f"update: {e}", FAILED)
    except typer.Exit:
        raise
    except Exception as e:
        _fail(f"update failed: {type(e).__name__}: {e}", FAILED)
    if result["status"] in ("partial", "failed"):
        raise typer.Exit(FAILED)


@app.command()
def status(runs: int = typer.Option(5, "--runs", help="How many recent runs to show.")) -> None:
    """Recent update runs, each dataset's latest date, price coverage and the next scheduled run.
    Reads only; works while an update is running."""
    from sentinel import config
    from sentinel.update import status as state

    for line in state.lines(config.paths(), runs):
        typer.echo(line)


@app.command()
def schedule(
    action: str = typer.Argument(..., help="install, remove or show."),
    at: str = typer.Option(None, "--time", help="install: HH:MM local time "
                           "(default: update.schedule_time)."),
) -> None:  # fmt: skip
    """The weekday-evening update as a Windows scheduled task (runs `sentinel update --scheduled`
    through WSL; a start missed while the computer was off runs when it is back on)."""
    from sentinel import config
    from sentinel.update import schedule as task

    p = config.paths()
    try:
        if action == "install":
            typer.echo(f"schedule: installed, weekdays at {task.install(p, at)}")
        elif action == "remove":
            typer.echo("schedule: removed" if task.remove(p) else "schedule: not installed")
            return
        elif action != "show":
            _fail(f"unknown action {action!r}; known: install, remove, show", USAGE)
        info = task.show(p)
    except config.ConfigError as e:
        _fail(f"schedule: {e}", CONFIG)
    except ValueError as e:
        _fail(f"schedule: {e}", USAGE)
    except RuntimeError as e:
        _fail(f"schedule: {e}", FAILED)
    if info is None:
        typer.echo("schedule: not installed")
    for name, value in (info or {}).items():
        typer.echo(f"  {name}: {value}")


@app.command()
def verify(keep: bool = typer.Option(False, "--keep", help="Keep data/verify.duckdb.")) -> None:
    """Rebuild everything into a scratch database and compare it with the build database."""
    from sentinel import config
    from sentinel.update import verify as verifier

    differ = verifier.verify(config.paths(), keep=keep, echo=typer.echo)
    for line in differ:
        typer.echo(f"  {line}")
    typer.echo("verify: all tables identical" if not differ else
               f"verify: {len(differ)} tables differ")  # fmt: skip
    raise typer.Exit(OK if not differ else FAILED)


def _serving(name: str, run) -> None:
    from sentinel import config, db

    started = time.monotonic()
    try:
        counts = run(config.paths(), typer.echo)
    except config.ConfigError as e:
        _fail(str(e), CONFIG)
    except (FileNotFoundError, db.MissingInput) as e:
        _fail(f"{name}: {e}", CONFIG)
    except duckdb.IOException as e:
        _fail(f"{name}: a database is in use ({e})", FAILED)
    typer.echo(f"{name}: {len(counts)} tables in {time.monotonic() - started:,.0f}s")


@app.command()
def publish() -> None:
    """Write data/serving.duckdb, the tables the product reads."""
    from sentinel.serving import publish as serving

    _serving("publish", serving.publish)


@app.command()
def export() -> None:
    """Write the private Parquet snapshot to data/exports/."""
    from sentinel.serving import export as serving

    _serving("export", serving.export)


@app.command()
def train(
    question: str = typer.Argument(..., help="results_move, dilution, volatility, or all."),
    level: str = typer.Option(
        "lightgbm", "--level", help="lightgbm, xgboost, or hist_gradient_boosting."
    ),
) -> None:
    """Train and freeze forecasting model(s) into data/models/."""
    import pandas as pd

    from sentinel import config, eda
    from sentinel.models import dilution, results_move, volatility

    p = config.paths()
    p.models.mkdir(parents=True, exist_ok=True)
    known = ("results_move", "dilution", "volatility", "all")
    if question not in known:
        _fail(f"unknown question {question!r}; known: {', '.join(known)}", USAGE)

    targets = [question] if question != "all" else ["results_move", "dilution", "volatility"]

    for q in targets:
        typer.echo(f"Training {q} model (level: {level})...")
        started = time.monotonic()
        raw_df = eda.load(q)
        dev_df = raw_df[pd.to_datetime(raw_df["as_of"]) <= pd.Timestamp(eda.DEV_END)].copy()

        if q == "results_move":
            model = results_move.fit(dev_df, level=level)
            model_path = p.models / "results_move.joblib"
            results_move.save(model, model_path)
            typer.echo(
                f"  Saved {q} model to {model_path} ({len(model.features)} features) "
                f"in {time.monotonic() - started:.1f}s"
            )
        elif q == "dilution":
            lvl = "hist_gradient_boosting" if level == "hist_gradient_boosting" else level
            model = dilution.fit(dev_df, level=lvl)
            model_path = p.models / "dilution.joblib"
            dilution.save(model, model_path)
            typer.echo(
                f"  Saved {q} model to {model_path} ({len(model.features)} features) "
                f"in {time.monotonic() - started:.1f}s"
            )
        elif q == "volatility":
            model = volatility.fit(dev_df, level=level)
            model_path = p.models / "volatility.joblib"
            volatility.save(model, model_path)
            typer.echo(
                f"  Saved {q} model to {model_path} ({len(model.features)} features) "
                f"in {time.monotonic() - started:.1f}s"
            )


@app.command()
def score(
    question: str = typer.Argument(..., help="results_move, dilution, volatility, or all."),
    input_file: str = typer.Option(
        None, "--input", help="Parquet file to score (default: data/exports/latest.parquet)."
    ),
    output_file: str = typer.Option(
        None, "--output", help="Parquet file to save output predictions."
    ),
) -> None:
    """Score covered stocks using frozen model(s) from data/models/."""
    from pathlib import Path

    import pandas as pd

    from sentinel import config
    from sentinel.models import dilution, results_move, volatility

    p = config.paths()
    known = ("results_move", "dilution", "volatility", "all")
    if question not in known:
        _fail(f"unknown question {question!r}; known: {', '.join(known)}", USAGE)

    if input_file:
        in_path = Path(input_file)
    elif (p.exports / "ml" / "latest.parquet").exists():
        in_path = p.exports / "ml" / "latest.parquet"
    else:
        in_path = p.exports / "latest.parquet"
    if not in_path.exists():
        _fail(f"input file does not exist: {in_path}", FAILED)

    rows = pd.read_parquet(in_path)
    typer.echo(f"Loaded {len(rows):,} rows from {in_path.name}")

    targets = [question] if question != "all" else ["results_move", "dilution", "volatility"]
    preds = {}

    for q in targets:
        model_path = p.models / f"{q}.joblib"
        if not model_path.exists():
            _fail(f"model file not found: {model_path}. Run 'sentinel train {q}' first.", FAILED)

        if q == "results_move":
            m_res = results_move.load(model_path)
            res = results_move.predict(m_res, rows)
            preds[q] = res
            el = res[res["eligible"]]
            typer.echo(
                f"  results_move: scored {len(el):,} eligible rows "
                f"(median pred move: {el['pred_move'].median():.2%})"
            )
        elif q == "dilution":
            m_dil = dilution.load(model_path)
            res = dilution.predict(m_dil, rows)
            preds[q] = res
            el = res[res["eligible"]]
            typer.echo(
                f"  dilution: scored {len(el):,} eligible rows "
                f"(mean prob: {el['dilution_prob'].mean():.2%})"
            )
        elif q == "volatility":
            m_vol = volatility.load(model_path)
            res = volatility.predict(m_vol, rows)
            preds[q] = res
            el = res[res["eligible"]]
            typer.echo(
                f"  volatility: scored {len(el):,} eligible rows "
                f"(median vol forecast: {el['vol_forecast'].median():.2%})"
            )

    if output_file:
        out_p = Path(output_file)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if len(targets) == 1:
            preds[targets[0]].to_parquet(out_p, index=False)
        else:
            merged = rows[["cik", "as_of"]].copy()
            for _q, df_pred in preds.items():
                cols_to_add = [c for c in df_pred.columns if c not in ("cik", "as_of")]
                merged = merged.join(df_pred[cols_to_add])
            merged.to_parquet(out_p, index=False)
        typer.echo(f"Saved predictions to {output_file}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Host interface to bind to."),
    port: int = typer.Option(
        8080, "--port", help="Port number (default 8080, port 8000 is reserved)."
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development."),
) -> None:
    """Launch the EDGAR-SENTINEL web application and API."""
    import uvicorn

    if port == 8000:
        _fail(
            "Port 8000 is reserved for another application on this machine. "
            "Use port 8080 or another port.",
            USAGE,
        )
    typer.echo(f"Starting EDGAR-SENTINEL on http://localhost:{port} (binding to {host}:{port}) ...")
    uvicorn.run("sentinel.app.main:app", host=host, port=port, reload=reload)
