"""`sentinel build <layer>`: rebuild a layer of the build database from the layer below it
(docs/architecture.md). Each step replaces its tables whole, so a rerun gives the same result."""

from collections.abc import Callable

import duckdb

from sentinel.config import Paths
from sentinel.core import filings as core_filings
from sentinel.core import prices as core_prices
from sentinel.reference import build as ref
from sentinel.staging import market, prices, sec_filings, sec_form4, sec_headers, sec_xbrl

Step = Callable[[duckdb.DuckDBPyConnection, Paths, Callable[[str], None]], dict]


class UnknownStep(Exception):
    """A layer or step name that does not exist (CLI exit code 2)."""


class StepFailed(Exception):
    """A step finished but its own checks failed (for example row counts against the files)."""


def _sec_form4(con, p: Paths, echo) -> dict:
    archives = sec_form4.stored_archives(p)
    if not archives:
        raise FileNotFoundError("no Form 4 archives in the manifest: run `sentinel fetch form4`")
    report = sec_form4.stage_all(con, archives, on_progress=lambda q: echo(f"  form 4: {q}"))
    if report.mismatches:
        raise StepFailed(f"rows loaded differ from the files: {report.mismatches[:5]}")
    issues = sum(report.issues_by_column.values())
    return {"quarters": len(archives), "rows": report.total_rows, "conversion_issues": issues}


STAGING: dict[str, Step] = {
    "sec_form4": _sec_form4,
    "sec_filings": sec_filings.stage,
    "sec_xbrl": sec_xbrl.stage,
    "sec_headers": sec_headers.stage_headers,
    "sec_tickers": sec_headers.stage_tickers,
    "yahoo": prices.stage_yahoo,
    "tiingo": prices.stage_tiingo,
    "market": market.stage,
}
REFERENCE: dict[str, Step] = {
    "company": ref.build_company,
    "ticker_history": ref.build_ticker_history,
    "calendar": ref.build_calendar,
    "sector": ref.build_sector,
}
CORE: dict[str, Step] = {
    "price_candidates": core_prices.build_candidates,
    "price_choice": core_prices.build_choice,
    "price_daily": core_prices.build_daily,
    "price_check": core_prices.build_check,
    "security": core_prices.build_security,
    "filing": core_filings.build_filing,
    "financial_fact": core_filings.build_financial_fact,
    "shares": core_filings.build_shares,
    "results_release": core_filings.build_results_release,
}
LAYERS: dict[str, dict[str, Step]] = {"staging": STAGING, "reference": REFERENCE, "core": CORE}


def run(con, p: Paths, layer: str, only: list[str] | None = None, echo=print) -> dict:
    steps = LAYERS[layer]
    unknown = [s for s in only or [] if s not in steps]
    if unknown:
        raise UnknownStep(
            f"unknown {layer} step(s): {', '.join(unknown)}; known: {', '.join(steps)}"
        )
    results = {}
    for name, step in steps.items():
        if only and name not in only:
            continue
        echo(f"{layer}: {name}")
        results[name] = step(con, p, echo)
    return results
