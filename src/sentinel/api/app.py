"""The stock lookup web app (feature 005; plan §8.6 page 2; contracts/http.md).

Server-rendered pages (Jinja2, with HTMX for search-as-you-type and paging) and two JSON endpoints,
over `data/lookup.duckdb` opened read-only. Every page and JSON body states the data-as-of date
(rule P6); every transaction code is shown with its plain-English label (rule P7). Nothing here
reads market prices: the lookup file holds none.
"""

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from sentinel.api import glossary, queries
from sentinel.config import Paths

HERE = Path(__file__).parent
MAX_PAGE_SIZE = 500


def _fmt_date(value) -> str:
    return value.strftime("%-d %b %Y") if isinstance(value, date) else "not reported"


def _fmt_number(value, decimals: int = 0) -> str:
    if value is None:
        return "not reported"
    if decimals == 0 and float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.{decimals or 2}f}".rstrip("0").rstrip(".")


def _fmt_money(value) -> str:
    if value is None:
        return "not reported"
    return f"${value:,.2f}" if abs(value) >= 1 else f"${value:,.4f}".rstrip("0").rstrip(".")


def _dataset_label(dataset: str | None) -> str:
    return f"{dataset[:4]} Q{dataset[-1]}" if dataset and len(dataset) == 6 else str(dataset)


def _years(first, last) -> str:
    if first is None:
        return "current"
    return str(first) if first == last else f"{first}–{last}"


def _tickers_label(tickers: list[dict]) -> str:
    return ", ".join(f"{t['ticker']} ({_years(t['first_year'], t['last_year'])})" for t in tickers)


def _holding_label(holding: str | None) -> str:
    return glossary.label(glossary.HOLDINGS, {"direct": "D", "indirect": "I"}.get(holding or ""))


def as_of(meta: dict) -> dict:
    """The `data_as_of` member of every JSON body."""
    return {"date": meta["date"].isoformat(), "dataset": meta["dataset"]}


def create_app(paths: Paths) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.con = queries.open_lookup(paths)
        app.state.meta = queries.meta(queries.cursor(app.state.con))
        yield
        app.state.con.close()

    app = FastAPI(
        title="EDGAR-SENTINEL stock lookup", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(
        fmt_date=_fmt_date, fmt_number=_fmt_number, fmt_money=_fmt_money,
        dataset_label=_dataset_label, describe_code=glossary.describe_code, label=glossary.label,
        glossary=glossary, tickers_label=_tickers_label, holding_label=_holding_label,
        edgar_url=queries.edgar_url,
    )  # fmt: skip

    def cursor(request: Request):
        cur = queries.cursor(request.app.state.con)
        try:
            yield cur
        finally:
            cur.close()

    Cursor = Annotated[duckdb.DuckDBPyConnection, Depends(cursor)]

    def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
        context = {"meta": request.app.state.meta, **context}
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", exc.status_code, message=exc.detail)

    @app.exception_handler(RequestValidationError)
    async def bad_parameter(request: Request, exc: RequestValidationError):
        names = ", ".join(str(e["loc"][-1]) for e in exc.errors())
        return await http_error(request, StarletteHTTPException(400, f"Bad parameter: {names}"))

    def fragment(request: Request) -> bool:
        return request.headers.get("HX-Request") == "true"

    def company_or_404(cur: duckdb.DuckDBPyConnection, cik: str) -> dict:
        found = queries.issuer(cur, cik.lstrip("0") or cik)
        if found is None:
            raise StarletteHTTPException(404, f"No company with CIK {cik} in the SEC data")
        return found

    # --- Pages (user story 1) ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request):
        return render(request, "search.html", q="")

    @app.get("/search", response_class=HTMLResponse, include_in_schema=False)
    def search(request: Request, cur: Cursor, q: str = ""):
        results = queries.search(cur, q) if len(q.strip()) >= queries.MIN_QUERY else None
        name = "_results.html" if fragment(request) else "search.html"
        return render(request, name, q=q, results=results)

    @app.get("/company/{cik}", response_class=HTMLResponse, include_in_schema=False)
    def company(request: Request, cur: Cursor, cik: str):
        found = company_or_404(cur, cik)
        rows, total = queries.transactions_page(cur, found["issuer_cik"])
        return render(request, "company.html", company=found, rows=rows, total=total, page=1,
                      page_size=queries.PAGE_SIZE,
                      insiders=queries.insiders(cur, found["issuer_cik"]),
                      events=queries.events(cur, found["issuer_cik"]))  # fmt: skip

    @app.get("/company/{cik}/transactions", response_class=HTMLResponse, include_in_schema=False)
    def transactions(request: Request, cur: Cursor, cik: str, page: int = 1):
        found = company_or_404(cur, cik)
        if page < 1:
            raise StarletteHTTPException(400, "Bad parameter: page")
        rows, total = queries.transactions_page(cur, found["issuer_cik"], page)
        name = "_transactions.html" if fragment(request) else "transactions.html"
        return render(request, name, company=found, rows=rows, total=total, page=page,
                      page_size=queries.PAGE_SIZE)  # fmt: skip

    @app.get(
        "/company/{cik}/insider/{owner_cik}", response_class=HTMLResponse, include_in_schema=False
    )
    def insider(request: Request, cur: Cursor, cik: str, owner_cik: str):
        found = company_or_404(cur, cik)
        owner = queries.insiders(cur, found["issuer_cik"], owner_cik.lstrip("0") or owner_cik)
        if not owner:
            raise StarletteHTTPException(404, f"No insider with CIK {owner_cik} at {found['name']}")
        rows = queries.holdings(cur, found["issuer_cik"], owner[0]["owner_cik"])
        name = "_holdings.html" if fragment(request) else "insider.html"
        return render(request, name, company=found, insider=owner[0], rows=rows)

    @app.get("/filing/{accession}/footnotes", response_class=HTMLResponse, include_in_schema=False)
    def filing_footnotes(request: Request, cur: Cursor, accession: str, ids: str = ""):
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        notes = queries.footnotes(cur, accession, wanted)
        name = "_footnotes.html" if fragment(request) else "footnotes.html"
        return render(request, name, accession=accession, notes=notes)

    @app.get("/glossary", response_class=HTMLResponse, include_in_schema=False)
    def glossary_page(request: Request):
        return render(request, "glossary.html")

    # --- JSON (contracts/http.md) --------------------------------------------------------------

    @app.get("/api/issuers/search")
    def api_search(request: Request, cur: Cursor, q: str = ""):
        """Companies matching a ticker (current or past), part of a filed name, or a CIK.

        At most 25 results: an exact CIK or ticker first, then names starting with `q`, then other
        names containing it; ties by number of transactions. `q` must have 2 characters or more.
        Each result: `cik`, `name`, `tickers` (`ticker`, `first_year`, `last_year`; years are
        null for a current ticker not seen on any filing), `n_transactions`, `first_filing`,
        `last_filing`. Every body has `data_as_of` (`date`, `dataset`).
        """
        if len(q.strip()) < queries.MIN_QUERY:
            raise StarletteHTTPException(400, "query too short")
        results = [
            {"cik": r["issuer_cik"], "name": r["name"], "tickers": r["tickers"],
             "n_transactions": r["n_transactions"], "first_filing": r["first_filing"],
             "last_filing": r["last_filing"]}
            for r in queries.search(cur, q)
        ]  # fmt: skip
        return {"data_as_of": as_of(request.app.state.meta), "query": q, "results": results}

    @app.get("/api/issuers/{cik}/transactions")
    def api_transactions(request: Request, cur: Cursor, cik: str, page: int = 1,
                         page_size: int = queries.PAGE_SIZE):  # fmt: skip
        """A company's insider transactions (every Form 3, 4 and 5 line), newest filing first.

        `page_size` 1–500 (default 100). Each transaction has the fields the company page shows:
        `accession`, `line_sk`, `filing_date`, `trade_date`, `form`, `form_description`, `code`,
        `code_description` (always present), `acquired_disposed`, `security_title`, `shares`,
        `price` and `value_usd` (as reported by the filer), `shares_after`, `holding` (`direct` or
        `indirect`), `holder`, `owners` (`cik`, `name`, `role` at the filing date, `title`),
        `footnote_ids`, `edgar_url`. Every body has `data_as_of` (`date`, `dataset`).
        """
        if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise StarletteHTTPException(400, f"page must be ≥ 1, page_size 1–{MAX_PAGE_SIZE}")
        found = company_or_404(cur, cik)
        rows, total = queries.transactions_page(cur, found["issuer_cik"], page, page_size)
        return {
            "data_as_of": as_of(request.app.state.meta),
            "issuer": {"cik": found["issuer_cik"], "name": found["name"]},
            "page": page, "page_size": page_size, "total": total, "transactions": rows,
        }  # fmt: skip

    return app
