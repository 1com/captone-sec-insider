"""FastAPI web application for EDGAR-SENTINEL (Feature 011/012).

Serves equity research views and REST API endpoints over data/serving.duckdb.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sentinel.app import db

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def to_json_filter(val: Any) -> str:
    """Safe JSON encoder handling date and numpy types."""

    def default_serializer(o: Any) -> Any:
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if hasattr(o, "item"):
            return o.item()
        return str(o)

    return json.dumps(val, default=default_serializer)


templates.env.filters["tojson"] = to_json_filter


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify database accessibility at startup
    con = db.get_db()
    con.execute("select 1").fetchone()
    con.close()
    yield


app = FastAPI(
    title="EDGAR-SENTINEL v2",
    description="Market Research & Forecasting Platform for US-Traded Stocks",
    version="2.0.0",
    lifespan=lifespan,
)


# Dependency: get read-only connection
def get_connection():
    return db.get_db()


# ---------------------------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1)) -> list[dict[str, Any]]:
    con = get_connection()
    try:
        return db.search_stocks(con, q)
    finally:
        con.close()


@app.get("/api/stock/{ticker_or_cik}")
def api_stock(ticker_or_cik: str) -> dict[str, Any]:
    con = get_connection()
    try:
        stock = db.get_stock_overview(con, ticker_or_cik)
        if not stock:
            raise HTTPException(status_code=404, detail="Stock not found")
        return stock
    finally:
        con.close()


@app.get("/api/prices/{ticker_or_cik}")
def api_prices(ticker_or_cik: str, limit: int = 252) -> list[dict[str, Any]]:
    con = get_connection()
    try:
        stock = db.get_stock_overview(con, ticker_or_cik)
        if not stock:
            raise HTTPException(status_code=404, detail="Stock not found")
        return db.get_price_history(con, stock["cik"], limit=limit)
    finally:
        con.close()


@app.get("/api/screener")
def api_screener(
    sector: str | None = None,
    vol_band: int | None = None,
    dil_band: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    con = get_connection()
    try:
        return db.get_screener(
            con, sector=sector, vol_band=vol_band, dil_band=dil_band, limit=limit
        )
    finally:
        con.close()


@app.get("/api/insiders")
def api_insiders(limit: int = 50) -> list[dict[str, Any]]:
    con = get_connection()
    try:
        return db.get_insider_feed(con, limit=limit)
    finally:
        con.close()


@app.get("/api/freshness")
def api_freshness() -> list[dict[str, Any]]:
    """Return latest observation dates for each data layer."""
    con = get_connection()
    try:
        return db.get_freshness(con)
    finally:
        con.close()


@app.get("/api/options/{ticker}")
def api_options(ticker: str) -> dict[str, Any]:
    """Return option chain and implied volatility benchmarks for a stock (Feature 023)."""
    con = get_connection()
    try:
        return db.get_options(con, ticker)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# HTML Web Views
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def view_index():
    return RedirectResponse(url="/stock/AAPL")


@app.get("/stock/{ticker_or_cik}", response_class=HTMLResponse)
def view_stock(request: Request, ticker_or_cik: str):
    con = get_connection()
    try:
        stock = db.get_stock_overview(con, ticker_or_cik)
        if not stock:
            # Fallback search
            results = db.search_stocks(con, ticker_or_cik, limit=1)
            if results:
                return RedirectResponse(url=f"/stock/{results[0]['ticker'] or results[0]['cik']}")
            raise HTTPException(status_code=404, detail="Stock not found")

        cik = stock["cik"]
        prices = db.get_price_history(con, cik, limit=126)  # 6 months
        filings = db.get_filings(con, cik, limit=15)
        financials = db.get_financials(con, cik)
        insiders = db.get_insider_activity(con, cik, limit=15)

        return templates.TemplateResponse(
            request=request,
            name="stock.html",
            context={
                "stock": stock,
                "prices": prices,
                "filings": filings,
                "financials": financials,
                "insiders": insiders,
            },
        )
    finally:
        con.close()


@app.get("/screener", response_class=HTMLResponse)
def view_screener(
    request: Request,
    sector: str = "all",
    vol_band: int | None = None,
    dil_band: int | None = None,
):
    con = get_connection()
    try:
        stocks = db.get_screener(
            con,
            sector=sector if sector != "all" else None,
            vol_band=vol_band,
            dil_band=dil_band,
            limit=100,
        )
        return templates.TemplateResponse(
            request=request,
            name="screener.html",
            context={
                "stocks": stocks,
                "sector": sector,
                "vol_band": vol_band,
                "dil_band": dil_band,
            },
        )
    finally:
        con.close()


@app.get("/insiders", response_class=HTMLResponse)
def view_insiders(request: Request):
    con = get_connection()
    try:
        feed = db.get_insider_feed(con, limit=60)
        return templates.TemplateResponse(
            request=request,
            name="insiders.html",
            context={
                "feed": feed,
            },
        )
    finally:
        con.close()


@app.get("/model-card", response_class=HTMLResponse)
def view_model_card(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="model_card.html",
        context={},
    )
