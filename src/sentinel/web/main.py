"""The stock research app (026, V2-61): one page per company, dilution risk first.

`sentinel web` serves it on a port checked to be free, on this machine only by default. It reads
only the serving copy, read-only; every number comes from it (or, for the dilution forecast, from
the approved frozen model applied to it). No volatility or results-day forecast is shown."""

from __future__ import annotations

import base64
import hmac
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sentinel import config
from sentinel.web import data, glossary
from sentinel.web.forecast import Forecasts, share_count_doubt

HERE = Path(__file__).parent
app = FastAPI(title="EDGAR-SENTINEL", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
PATHS = config.paths()
FORECASTS = Forecasts(PATHS)
# with WEB_PASSWORD in .env every request needs it (HTTP Basic, any user name): the app may then be
# reached by a public link, since only people with the password see it (researcher, 10 Nov: A)
PASSWORD = config.secrets(PATHS).web_password


def _allowed(header: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        given = base64.b64decode(header[6:]).decode("utf-8").partition(":")[2]
    except ValueError:
        return False
    return hmac.compare_digest(given.encode(), PASSWORD.encode())


@app.middleware("http")
async def _password(request: Request, call_next):
    if PASSWORD is None or _allowed(request.headers.get("authorization", "")):
        return await call_next(request)
    return Response(
        "Password required.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="EDGAR-SENTINEL", charset="UTF-8"'},
    )


@app.exception_handler(data.NoData)
def _no_data(request: Request, exc: data.NoData) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=503)


def _fresh(con) -> dict:
    return data.freshness(con)


def _asset_version() -> str:
    """Changes whenever the page's script or style changes, so a browser fetches the new files."""
    stamp = max((HERE / "static" / name).stat().st_mtime_ns for name in ("app.css", "app.js"))
    return format(stamp // 1_000_000, "x")


@app.get("/", response_class=HTMLResponse)
def page(request: Request) -> HTMLResponse:
    error, fresh = None, {}
    try:
        with data.connect(PATHS.serving_db) as con:
            fresh = _fresh(con)
    except data.NoData as e:
        error = str(e)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "fresh": fresh,
            "error": error,
            "kinds": list(glossary.KINDS.items()),
            "v": _asset_version(),
        },
    )


@app.get("/api/search")
def api_search(q: str = Query("", max_length=80)) -> list[dict]:
    with data.connect(PATHS.serving_db) as con:
        return data.search(con, q)


@app.get("/api/summary")
def api_summary() -> dict:
    """The first page's figures: how many companies have a forecast, and the forecasts' date. The
    first page lists no companies (the researcher, 17 Nov: no list of the highest risks, V2-77)."""
    with data.connect(PATHS.serving_db) as con:
        FORECASTS.refresh(con)
        return {"as_of": FORECASTS.as_of, "covered": len(FORECASTS.by_cik)}


@app.get("/api/company/{cik}")
def api_company(cik: str) -> JSONResponse:
    with data.connect(PATHS.serving_db) as con:
        c = data.company(con, cik)
        if c is None:
            return JSONResponse({"error": f"no company with CIK {cik}"}, status_code=404)
        FORECASTS.refresh(con)
        listed = any(t["listed"] for t in c["tickers"])
        c["dilution"] = FORECASTS.for_company(cik, c["card"], listed, c["facts"])
        # V2-75: the trading rules out the reported share count; the page marks the values on it
        c["share_count_doubt"] = share_count_doubt(c["card"])
        c["shares"] = data.shares(con, cik)
        c["freshness"] = _fresh(con)
        c["diagnostics"] = data.diagnostics(con, cik)
        c["model"] = {**FORECASTS.info, "card": FORECASTS.card}
        return JSONResponse(c)


@app.get("/api/prices/{cik}")
def api_prices(cik: str) -> dict:
    with data.connect(PATHS.serving_db) as con:
        out = data.prices(con, cik)
        out["offerings"] = data.offerings(con, cik)
        return out


@app.get("/api/financials/{cik}")
def api_financials(cik: str) -> dict:
    with data.connect(PATHS.serving_db) as con:
        return data.financials(con, cik)


@app.get("/api/insiders/{cik}")
def api_insiders(cik: str) -> dict:
    with data.connect(PATHS.serving_db) as con:
        return data.insiders(con, cik)


@app.get("/api/filings/{cik}")
def api_filings(cik: str, kind: str | None = None, limit: int = Query(200, le=2000)) -> dict:
    with data.connect(PATHS.serving_db) as con:
        return data.filings(con, cik, kind if kind in glossary.KINDS else None, limit)
