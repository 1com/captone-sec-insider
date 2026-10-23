"""Issuer → price-symbol mapping (plan Step 6) and the shared ticker helpers.

`normalise()` and the Tiingo matching moved here from `sentinel.provisional.tiingo_list` so that
production code can use them; the provisional module re-exports them. Tiingo's list is only ever
held in memory (constitution VI; Tiingo ToS §1.6(a)).
"""

import csv
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import duckdb
import httpx
import pyarrow as pa

from sentinel import __version__
from sentinel.ingest.sec_reference import load_snapshot
from sentinel.warehouse import scope

TiingoIndex = dict[str, list[tuple[date | None, date | None]]]
NO_TICKER = {"", "NONE", "NA", "NULL"}


def normalise(ticker: str | None) -> str | None:
    """Upper case, `.` and `/` become `-`, stray characters dropped; placeholders → None."""
    t = (ticker or "").strip().upper()
    if re.sub(r"[^A-Z0-9]", "", t) in NO_TICKER:
        return None
    t = re.sub(r"[^A-Z0-9./-]", "", t).replace(".", "-").replace("/", "-").strip("-")
    return t or None


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def parse_supported(zip_bytes: bytes, exchanges: Iterable[str]) -> TiingoIndex:
    allowed = set(exchanges)
    index: TiingoIndex = defaultdict(list)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                if (
                    row["assetType"] == "Stock"
                    and row["priceCurrency"] == "USD"
                    and row["exchange"] in allowed
                ):
                    ticker = normalise(row["ticker"])
                    if ticker:
                        index[ticker].append((_date(row["startDate"]), _date(row["endDate"])))
    return dict(index)


def fetch_list(url: str, timeout: float) -> tuple[bytes, str | None, str]:
    """Download into memory. A generic User-Agent is used: the SEC contact is not sent to Tiingo."""
    resp = httpx.get(
        url,
        headers={"User-Agent": f"edgar-sentinel/{__version__}"},
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Last-Modified"), hashlib.sha256(resp.content).hexdigest()


def match(
    index: TiingoIndex | None, tickers: Iterable[str], span_start: date, span_end: date
) -> tuple[str, str | None]:
    """matched / ticker_only / unmatched / not_checked, plus the Tiingo ticker that matched.

    Tiingo files a delisted company's history under its final ticker, often the bankruptcy form
    with a `Q` suffix on an OTC venue, so `XYZQ` is tried after `XYZ`.
    """
    if index is None:
        return "not_checked", None
    seen_ticker = False
    for raw in tickers:
        ticker = normalise(raw)
        if not ticker:
            continue
        for candidate in (ticker, f"{ticker}Q"):
            if candidate not in index:
                continue
            seen_ticker = True
            for start, end in index[candidate]:
                if (start is None or start <= span_end) and (end is None or end >= span_start):
                    return "matched", candidate
    return ("ticker_only" if seen_ticker else "unmatched"), None


# --- Symbol map (feature 002, Step 6; research.md R7) -----------------------------------------

FUND_LIKE = re.compile(r"\b(fund|trust|income)\b", re.IGNORECASE)
OTC_EXCHANGES = {None, "OTC"}


def split_symbols(raw: str | None) -> list[str]:
    """Normalised tickers in a filing's `ISSUERTRADINGSYMBOL`, which may list classes ("XA, XB")."""
    return [t for part in re.split(r"[,;]", raw or "") if (t := normalise(part))]


def build_symbol_map(
    con: duckdb.DuckDBPyConnection, snapshot_path: Path, params: dict, cutoff=None
) -> tuple[int, int]:
    """`core.symbol_map` and `core.symbol_unmatched` for every issuer in `core.filing`.

    Listed (in the SEC snapshot): each current ticker, priced from Yahoo from the issuer's first
    filing, `sec_current_otc` when the snapshot gives OTC or no exchange. Not listed: each ticker
    the issuer's filings reported, from its first to its last filing date, priced from Tiingo.
    Neither: unmatched, `fund_like` when the name suggests a fund. SEC-derived tickers only (W11).
    """
    where, args = scope(cutoff, None)
    issuers = con.execute(
        f"""
        select issuer_cik, min(filing_date),
               arg_max(issuer_name, strftime(filing_date, '%Y-%m-%d') || accession)
        from core.filing f
        where issuer_cik is not null and filing_date is not null and {where}
        group by 1
        """,
        args,
    ).fetchall()
    history: dict[str, dict[str, list[date]]] = defaultdict(dict)
    for cik, raw, first, last in con.execute(
        f"""
        select issuer_cik, symbol_raw, min(filing_date), max(filing_date)
        from core.filing f
        where issuer_cik is not null and filing_date is not null and symbol_raw is not null
          and {where}
        group by all
        """,
        args,
    ).fetchall():
        for ticker in split_symbols(raw):
            span = history[cik].setdefault(ticker, [first, last])
            span[0], span[1] = min(span[0], first), max(span[1], last)

    listed = load_snapshot(snapshot_path)
    mapped, unmatched = [], []
    for cik, first, name in issuers:
        if cik in listed:
            for raw, exchange in listed[cik]:
                if ticker := normalise(raw):
                    quality = "sec_current_otc" if exchange in OTC_EXCHANGES else "sec_current"
                    mapped.append((cik, ticker, first, None, "yahoo", quality))
        elif history.get(cik):
            for ticker, (start, end) in sorted(history[cik].items()):
                mapped.append((cik, ticker, start, end, "tiingo", "form4_history"))
        else:
            reason = "fund_like" if FUND_LIKE.search(name or "") else "no_ticker"
            unmatched.append((cik, name, reason))

    names = ["issuer_cik", "ticker", "valid_from", "valid_to", "price_source", "match_quality"]
    types = [pa.string(), pa.string(), pa.date32(), pa.date32(), pa.string(), pa.string()]
    columns = list(zip(*mapped, strict=True)) if mapped else [[] for _ in names]
    con.register(
        "_map",
        pa.table({n: pa.array(c, t) for n, c, t in zip(names, columns, types, strict=True)}),
    )
    columns = list(zip(*unmatched, strict=True)) if unmatched else [[], [], []]
    con.register(
        "_unmatched",
        pa.table(
            {
                n: pa.array(c, pa.string())
                for n, c in zip(["issuer_cik", "issuer_name", "reason"], columns, strict=True)
            }
        ),
    )
    try:
        con.execute("begin transaction")
        try:
            con.execute("create or replace table core.symbol_map as select * from _map")
            con.execute("create or replace table core.symbol_unmatched as select * from _unmatched")
        except BaseException:
            con.execute("rollback")
            raise
        con.execute("commit")
    finally:
        con.unregister("_map")
        con.unregister("_unmatched")
    return len(mapped), len(unmatched)


def check_events_covered(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W10: issuers with a preliminary event but no symbol-map or unmatched row."""
    return [
        cik
        for (cik,) in con.execute(
            """
            select distinct issuer_cik from evt.prelim_event
            where issuer_cik not in (select issuer_cik from core.symbol_map)
              and issuer_cik not in (select issuer_cik from core.symbol_unmatched)
            order by 1
            """
        ).fetchall()
    ]


def check_sec_only(con: duckdb.DuckDBPyConnection, snapshot_path: Path) -> list[tuple[str, str]]:
    """W11: (issuer, ticker) rows of the map that neither the SEC snapshot nor the issuer's
    own filings gave it."""
    allowed: dict[str, set[str]] = defaultdict(set)
    for cik, pairs in load_snapshot(snapshot_path).items():
        allowed[cik].update(t for raw, _ in pairs if (t := normalise(raw)))
    for cik, raw in con.execute(
        "select distinct issuer_cik, symbol_raw from core.filing where symbol_raw is not null"
    ).fetchall():
        allowed[cik].update(split_symbols(raw))
    return [
        (cik, ticker)
        for cik, ticker in con.execute(
            "select issuer_cik, ticker from core.symbol_map order by all"
        ).fetchall()
        if ticker not in allowed[cik]
    ]


def coverage(con: duckdb.DuckDBPyConnection) -> dict:
    """Event companies by how they will be priced (SC-006)."""
    mapped, yahoo, tiingo, total = con.execute(
        """
        with ev as (select distinct issuer_cik from evt.prelim_event),
        src as (
            select issuer_cik, bool_or(price_source = 'yahoo') as yahoo
            from core.symbol_map group by 1
        )
        select count(s.issuer_cik), count(*) filter (where s.yahoo),
               count(*) filter (where not s.yahoo), count(*)
        from ev left join src s using (issuer_cik)
        """
    ).fetchone()
    unmatched = dict(
        con.execute(
            """
            select reason, count(*) from core.symbol_unmatched
            where issuer_cik in (select issuer_cik from evt.prelim_event)
            group by 1 order by 1
            """
        ).fetchall()
    )
    return {
        "event_companies": total,
        "mapped": mapped,
        "yahoo": yahoo,
        "tiingo": tiingo,
        "unmatched": unmatched,
    }


def tiingo_coverage(con: duckdb.DuckDBPyConnection, params: dict) -> dict[str, int]:
    """How many delisted event companies Tiingo's public list resolves, held in memory only.

    Each company's SEC tickers are tried as they are and with a `Q` suffix, over the span of its
    events. Nothing is stored (constitution VI); feature 003 stores tickers in the paid month.
    """
    payload, _, _ = fetch_list(
        params["ops"]["tiingo_supported_tickers_url"], params["ops"]["http_timeout_seconds"]
    )
    # The US venue list feature 001 validated against Tiingo's filing of delisted histories.
    index = parse_supported(payload, params["provisional"]["tiingo_us_exchanges"])
    rows = con.execute(
        """
        with delisted as (
            select issuer_cik, list(ticker order by valid_from, ticker) as tickers
            from core.symbol_map group by 1 having bool_and(price_source = 'tiingo')
        )
        select d.issuer_cik, d.tickers, min(e.signal_date), max(e.signal_date)
        from delisted d join evt.prelim_event e using (issuer_cik)
        group by all order by 1
        """
    ).fetchall()
    counts = {"companies": len(rows), "matched": 0, "q_suffix": 0, "ticker_only": 0, "unmatched": 0}
    for _, tickers, start, end in rows:
        status, found = match(index, tickers, start, end)
        counts[status] += 1
        if found and found not in tickers:
            counts["q_suffix"] += 1
    return counts
