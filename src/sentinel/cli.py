"""The `sentinel` command. Commands are added layer by layer (docs/architecture.md)."""

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
