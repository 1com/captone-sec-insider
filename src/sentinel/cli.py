"""The `sentinel` command. Commands are added layer by layer (docs/architecture.md)."""

import typer

from sentinel import __version__

app = typer.Typer(name="sentinel", help="EDGAR-SENTINEL v2.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """EDGAR-SENTINEL v2: a market research platform for any US-traded stock."""


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)
