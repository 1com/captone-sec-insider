"""`uv run python -m mvp <command>`: build | serve | check | prices."""

import logging
import time

import typer

app = typer.Typer(
    name="mvp",
    no_args_is_help=True,
    add_completion=False,
    help="EDGAR-SENTINEL MVP prototype (pilot sample 2006–2011, survivors only).",
)


def _timed(label: str):
    class _T:
        def __enter__(self):
            self.t = time.perf_counter()
            typer.echo(f"▶ {label}")
            return self

        def __exit__(self, *exc):
            if exc[0] is None:
                typer.echo(f"  ✓ {label} ({time.perf_counter() - self.t:.1f}s)")

    return _T()


@app.command()
def prices():
    """Download (or reuse cached) Yahoo prices for the MVP universe."""
    from mvp.config import WORK, ensure_dirs, load_settings
    from mvp.pipeline import prices as px
    from mvp.pipeline.universe import build_universe, tickers_to_price

    s = load_settings()
    ensure_dirs()
    with _timed("universe"):
        events, companies = build_universe(s)
        events.to_parquet(WORK / "universe_events.parquet")
        companies.to_parquet(WORK / "companies.parquet")
    y = s.mvp["yahoo"]
    with _timed("yahoo prices"):
        result = px.download(
            tickers_to_price(events),
            start=str(y["start"]),
            batch_size=y["batch_size"],
            retries=y["retries"],
            pause=y["pause_seconds"],
            echo=typer.echo,
        )
    typer.echo(f"  {result}")


@app.command()
def build(skip_prices: bool = typer.Option(False, "--skip-prices", help="Use cached prices only.")):
    """Build all MVP data and render the dashboard (local and Artifact versions)."""
    from mvp.build import run

    run(skip_prices=skip_prices, echo=typer.echo, timed=_timed)


@app.command()
def serve(
    port: int = typer.Option(8765, help="Local port."),
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
):
    """Serve the built dashboard at http://127.0.0.1:8765."""
    import uvicorn

    from mvp.serve import create_app

    typer.echo(f"EDGAR-SENTINEL MVP → http://{host}:{port}/  (Ctrl-C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command()
def check():
    """Run the constitution guards (pilot-only outcomes, containment, labels)."""
    from mvp.checks import run_checks

    problems = run_checks()
    for p in problems:
        typer.echo(f"FAIL  {p}")
    typer.echo("all MVP guards pass" if not problems else f"{len(problems)} problem(s)")
    raise typer.Exit(1 if problems else 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    app()
