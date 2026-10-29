"""`sentinel build <layer>`: rebuild a layer of the build database from the layer below it
(docs/architecture.md). Each step replaces its tables whole, so a rerun gives the same result."""

from collections.abc import Callable

import duckdb

from sentinel.config import Paths
from sentinel.core import filings as core_filings
from sentinel.core import insider as core_insider
from sentinel.core import market as core_market
from sentinel.core import prices as core_prices
from sentinel.db import StepFailed
from sentinel.features import events as feat_events
from sentinel.features import fundamentals as feat_fundamentals
from sentinel.features import insider as feat_insider
from sentinel.features import market as feat_market
from sentinel.features import price as feat_price
from sentinel.features import rows as feat_rows
from sentinel.features import snapshot as feat_snapshot
from sentinel.labels import risk as risk_labels
from sentinel.raw import manifest
from sentinel.reference import build as ref
from sentinel.staging import market, prices, sec_filings, sec_form4, sec_headers, sec_xbrl
from sentinel.update import record

Step = Callable[[duckdb.DuckDBPyConnection, Paths, Callable[[str], None]], dict]


class UnknownStep(Exception):
    """A layer or step name that does not exist (CLI exit code 2)."""


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
# The manifest sources each staging step reads: the update re-runs a step when one of them has a
# stored file the step has not applied (`ops.staged_file`).
STAGING_SOURCES: dict[str, tuple[str, ...]] = {
    "sec_form4": ("sec_insider_bulk",),
    "sec_filings": ("sec_company", "sec_submissions_cik", "sec_index"),
    "sec_xbrl": ("sec_company", "sec_companyfacts_cik"),
    "sec_headers": ("sec_filing_header",),
    "sec_tickers": ("sec_company_tickers",),
    "yahoo": ("yahoo",),
    "tiingo": ("tiingo",),
    "market": ("fred", "cboe", "finra_short", "french"),
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
    "price_coverage": core_prices.build_coverage,
    "filing": core_filings.build_filing,
    "financial_fact": core_filings.build_financial_fact,
    "shares": core_filings.build_shares,
    "results_release": core_filings.build_results_release,
    "insider_filing": core_insider.build_insider_filing,
    "insider_entities": core_insider.build_insider_entities,
    "insider_trade": core_insider.build_insider_trade,
    "insider_activity": core_insider.build_insider_activity,
    "insider_cluster": core_insider.build_insider_cluster,
    "macro": core_market.build_macro,
    "ticker_span": core_market.build_ticker_span,
    "short_volume": core_market.build_short_volume,
}
FEATURES: dict[str, Step] = {
    "rows": feat_rows.build_rows,
    "price": feat_price.build_price,
    "fundamentals": feat_fundamentals.build_fundamentals,
    "events": feat_events.build_events,
    "insider": feat_insider.build_insider,
    "short": feat_market.build_short,
    "macro": feat_market.build_macro,
    "snapshot": feat_snapshot.build_snapshot,
}
LABELS: dict[str, Step] = {"risk": risk_labels.build_labels}
LAYERS: dict[str, dict[str, Step]] = {"staging": STAGING, "reference": REFERENCE, "core": CORE,
                                      "features": FEATURES, "labels": LABELS}  # fmt: skip


def run(con, p: Paths, layer: str, only: list[str] | None = None, echo=print) -> dict:
    steps = LAYERS[layer]
    unknown = [s for s in only or [] if s not in steps]
    if unknown:
        raise UnknownStep(
            f"unknown {layer} step(s): {', '.join(unknown)}; known: {', '.join(steps)}"
        )
    entries = None
    results = {}
    for name, step in steps.items():
        if only and name not in only:
            continue
        echo(f"{layer}: {name}")
        results[name] = step(con, p, echo)
        if layer == "staging":
            entries = entries or [e for e in manifest.read_all(p.manifest) if e.role == "original"]
            sources = STAGING_SOURCES.get(name, ())
            record.record_staged(con, name, [e for e in entries if e.source in sources])
    return results
