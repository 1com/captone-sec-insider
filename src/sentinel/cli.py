"""The `sentinel` command. Commands are added layer by layer (docs/architecture.md)."""

import time

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


@app.command()
def build(
    layer: str = typer.Argument(..., help="The layer to rebuild: staging, reference."),
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
    except (KeyError, FileNotFoundError, db.MissingInput) as e:
        _fail(f"build {layer}: {e}", CONFIG)
    except builder.StepFailed as e:
        _fail(f"build {layer}: {e}", FAILED)
    finally:
        con.close()
    for step, counts in results.items():
        typer.echo(f"  {step}: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    typer.echo(f"build {layer}: done in {time.monotonic() - started:,.0f}s")
