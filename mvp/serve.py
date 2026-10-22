"""Serve the built dashboard locally (FastAPI static files)."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mvp.config import SITE


def create_app() -> FastAPI:
    if not (SITE / "index.html").exists():
        raise SystemExit("dashboard not built: run `uv run python -m mvp build` first")
    app = FastAPI(title="EDGAR-SENTINEL MVP", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/", StaticFiles(directory=SITE, html=True), name="site")
    return app
