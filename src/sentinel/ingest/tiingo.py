"""Tiingo end-of-day prices for delisted event companies, in the paid month only (research R3).

Tiingo files a delisted company's history under its final ticker, often a bankruptcy `Q` ticker on
an OTC venue, and reuses tickers, so each company's SEC tickers are resolved against the stored
ticker list and each series is later checked against the company (`identity`). Every file written
here is Tiingo data: it lives under `data/raw/tiingo/`, has a `source = tiingo` manifest line, and
is deleted when the paid plan ends (contracts/tiingo-register.md). Writes outside the paid window
raise `OutsidePaidWindow`.
"""

import csv
import gzip
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import duckdb
import httpx

from sentinel import __version__
from sentinel.config import Paths
from sentinel.core.symbols import normalise, split_symbols
from sentinel.core.tiingo_register import SOURCE, require_paid_window
from sentinel.ingest import manifest
from sentinel.ingest.http import RateLimiter, RetryPolicy, SecForbidden, request_with_retry

LIST_KEY = "supported_tickers"
LIST_FILE = "supported_tickers.zip"
NAME_STOPWORDS = {
    "inc", "corp", "corporation", "co", "company", "ltd", "limited", "holdings", "holding",
    "group", "the", "class", "plc", "lp", "llc", "sa", "nv", "new", "de", "and", "of",
}  # fmt: skip
Listing = dict[str, list[tuple[date | None, date | None, str]]]


class TiingoRejected(Exception):
    """Tiingo answered 403: the key is wrong or the plan is not active."""


@dataclass(frozen=True)
class Target:
    issuer_cik: str
    ticker: str  # the Tiingo ticker to fetch
    role: str  # primary | fill_in | fallback
    base_ticker: str  # the SEC ticker it was resolved from
    span_start: date  # the issuer's filings under the base ticker
    span_end: date
    exchange: str | None  # of the matched list interval
    list_end: date | None


@dataclass
class FetchReport:
    stored: int = 0
    cached: int = 0
    not_found: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def make_client(api_key: str, timeout: float) -> httpx.Client:
    """The token travels in a header, so it never appears in a URL or the manifest. A generic
    User-Agent: the SEC contact is not sent to Tiingo."""
    return httpx.Client(
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"edgar-sentinel/{__version__}",
        },
        timeout=timeout,
        follow_redirects=True,
    )


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def parse_listing(zip_bytes: bytes, exchanges) -> Listing:
    """Tiingo's list: US stocks in USD on the given venues, as (start, end, exchange) per ticker."""
    allowed = set(exchanges)
    listing: Listing = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf, zf.open(zf.namelist()[0]) as f:
        for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
            if (
                row["assetType"] == "Stock"
                and row["priceCurrency"] == "USD"
                and row["exchange"] in allowed
                and (ticker := normalise(row["ticker"]))
            ):
                interval = (_date(row["startDate"]), _date(row["endDate"]), row["exchange"])
                listing.setdefault(ticker, []).append(interval)
    return listing


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(paths: Paths, book: manifest.Manifest, rel: str, key: str, data: bytes, url: str):
    final = paths.data_raw / rel
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    part.write_bytes(data)
    os.replace(part, final)
    os.chmod(final, 0o444)
    book.add(
        manifest.ManifestEntry(
            path=rel,
            source=SOURCE,
            key=key,
            role="original",
            url=url,
            fetched_at=_now(),
            bytes=len(data),
            sha256=manifest.sha256_file(final),
            http_last_modified=None,
            http_etag=None,
            tool="sentinel",
        )
    )


def store_list(paths: Paths, params: dict, payload: bytes, url: str, today: date | None = None):
    """Store Tiingo's ticker list once (paid month only)."""
    require_paid_window(params, today)
    book = manifest.Manifest(paths.manifest)
    if book.find_original(SOURCE, LIST_KEY) is None:
        _write(paths, book, f"tiingo/{LIST_FILE}", LIST_KEY, payload, url)
    return paths.tiingo / LIST_FILE


def stored_listing(paths: Paths, params: dict) -> Listing:
    return parse_listing(
        (paths.tiingo / LIST_FILE).read_bytes(), params["provisional"]["tiingo_us_exchanges"]
    )


def _spans(con: duckdb.DuckDBPyConnection, issuers: list[str]) -> dict[str, dict[str, list]]:
    """Each issuer's SEC tickers with the span of its filings under them: the symbol map's ranges
    (an open range ends at date.max), plus the Form 4 symbol history."""
    spans: dict[str, dict[str, list]] = {cik: {} for cik in issuers}
    if not issuers:
        return spans

    def widen(cik, ticker, start, end):
        span = spans[cik].setdefault(ticker, [start, end])
        span[0], span[1] = min(span[0], start), max(span[1], end)

    con.execute("create or replace temp table _issuers (issuer_cik VARCHAR)")
    con.executemany("insert into _issuers values (?)", [(c,) for c in issuers])
    for cik, ticker, start, end in con.execute(
        "select issuer_cik, ticker, valid_from, valid_to from core.symbol_map "
        "where issuer_cik in (select issuer_cik from _issuers)"
    ).fetchall():
        widen(cik, ticker, start, end or date.max)
    for cik, raw, start, end in con.execute(
        """
        select issuer_cik, symbol_raw, min(filing_date), max(filing_date) from core.filing
        where symbol_raw is not null and issuer_cik in (select issuer_cik from _issuers)
        group by all
        """
    ).fetchall():
        for ticker in split_symbols(raw):
            widen(cik, ticker, start, end)
    con.execute("drop table _issuers")
    return spans


def resolve(
    con: duckdb.DuckDBPyConnection, listing: Listing, params: dict, fallback_issuers=()
) -> list[Target]:
    """Tiingo tickers to fetch: for every Tiingo-mapped issuer with a preliminary event from
    `rules.final_detection_start`, and every Yahoo fallback issuer, each SEC ticker is tried as it
    is and with a `Q` suffix. A match needs a list interval overlapping the issuer's filings under
    the ticker. The match whose interval ends last is primary (`fallback` for Yahoo issuers), as
    Tiingo files the whole history under the final ticker; other matched tickers fill in earlier
    dates."""
    mapped = [
        r[0]
        for r in con.execute(
            """
            select distinct issuer_cik from core.symbol_map
            where price_source = 'tiingo' and issuer_cik in (
                select issuer_cik from evt.prelim_event where signal_date >= cast(? as DATE))
            order by 1
            """,
            [str(params["rules"]["final_detection_start"])],
        ).fetchall()
    ]
    fallback = sorted(set(fallback_issuers) - set(mapped))
    spans = _spans(con, mapped + fallback)
    targets = []
    for cik in mapped + fallback:
        best: dict[str, tuple] = {}  # Tiingo ticker → (list end, interval, base ticker, span)
        for base, (start, end) in sorted(spans[cik].items()):
            for candidate in (base, f"{base}Q"):
                for list_start, list_end, exchange in listing.get(candidate, []):
                    overlaps = (list_start is None or list_start <= end) and (
                        list_end is None or list_end >= start
                    )
                    key = list_end or date.max
                    if overlaps and (candidate not in best or key > best[candidate][0]):
                        best[candidate] = (key, (list_end, exchange), base, (start, end))
        if not best:
            continue
        primary = max(best, key=lambda t: (best[t][0], t))
        for ticker in sorted(best, key=lambda t: (t != primary, t)):
            _, (list_end, exchange), base, (start, end) = best[ticker]
            role = (
                ("fallback" if cik in fallback else "primary") if ticker == primary else "fill_in"
            )
            targets.append(Target(cik, ticker, role, base, start, end, exchange, list_end))
    return targets


def crosscheck_targets(con: duckdb.DuckDBPyConnection) -> list[Target]:
    """Tiingo tickers to fetch only to check Yahoo: the ticker of every chosen Yahoo series, as
    Yahoo writes it. They never become price series (`audit.price_crosscheck` compares them)."""
    return [
        Target(cik, ticker, "crosscheck", ticker, first, last, None, None)
        for cik, ticker, first, last in con.execute(
            "select issuer_cik, ticker, first_session, last_session from core.price_series "
            "where price_source = 'yahoo' and chosen order by ticker"
        ).fetchall()
    ]


def _words(name: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(w) > 1} - (
        NAME_STOPWORDS
    )


def identity(meta: dict | None, sec_names: list[str], span: tuple[date, date]) -> str:
    """`ok`, or why a Tiingo series is not this company's: `no_data` (no prices), `dates` (its
    history does not overlap the company's filings under the ticker) or `name` (no significant word
    shared with any of the company's SEC names)."""
    if not meta or not meta.get("startDate"):
        return "no_data"
    start, end = _date(meta["startDate"]), _date(meta.get("endDate"))
    if start > span[1] or (end is not None and end < span[0]):
        return "dates"
    if not _words(meta.get("name")) & set().union(*(_words(n) for n in sec_names)):
        return "name"
    return "ok"


def read_meta(paths: Paths, ticker: str) -> dict | None:
    path = paths.tiingo / "meta" / f"{ticker}.json.gz"
    if not path.exists():
        return None
    meta = json.loads(gzip.decompress(path.read_bytes()))
    return meta if isinstance(meta, dict) and meta.get("ticker") else None


def fetch(
    paths: Paths,
    params: dict,
    client: httpx.Client,
    *,
    targets: list[Target],
    limiter: RateLimiter,
    policy: RetryPolicy,
    limit: int | None = None,
    today: date | None = None,
    echo=print,
) -> FetchReport:
    """Meta, then prices from `rules.price_history_start`, for each target ticker not yet stored.
    Both are stored gzip-compressed with manifest lines; a ticker Tiingo does not know keeps its
    meta answer, so a rerun does not ask again."""
    require_paid_window(params, today)
    base = params["ops"]["tiingo_api_base"]
    start = str(params["rules"]["price_history_start"])
    book = manifest.Manifest(paths.manifest)
    report = FetchReport()
    tickers = list(dict.fromkeys(t.ticker for t in targets))  # primaries first, no repeats
    todo = [t for t in tickers if book.find_original(SOURCE, f"prices/{t}") is None]
    todo = [
        t for t in todo if not (book.find_original(SOURCE, f"meta/{t}") and not _known(paths, t))
    ]
    report.cached = len(tickers) - len(todo)
    if limit is not None:
        todo = todo[:limit]
    echo(f"tiingo: {report.cached:,} done, {len(todo):,} to fetch")
    for i, ticker in enumerate(todo, 1):
        try:
            if book.find_original(SOURCE, f"meta/{ticker}") is None:
                url = f"{base}/{ticker}"
                resp = _get(client, url, limiter, policy)
                if resp.status_code not in (200, 404):
                    report.failed.append((ticker, f"HTTP {resp.status_code}"))
                    continue
                data = gzip.compress(resp.content, mtime=0)
                _write(paths, book, f"tiingo/meta/{ticker}.json.gz", f"meta/{ticker}", data, url)
            meta = read_meta(paths, ticker)
            if not meta or not meta.get("startDate"):
                report.not_found.append(ticker)
                continue
            url = f"{base}/{ticker}/prices?startDate={start}&format=csv&resampleFreq=daily"
            resp = _get(client, url, limiter, policy)
            if resp.status_code != 200:
                report.failed.append((ticker, f"HTTP {resp.status_code}"))
                continue
            data = gzip.compress(resp.content, mtime=0)
            _write(paths, book, f"tiingo/prices/{ticker}.csv.gz", f"prices/{ticker}", data, url)
            report.stored += 1
        except SecForbidden as e:
            raise TiingoRejected("Tiingo answered 403: check TIINGO_API and the plan") from e
        if i % 250 == 0 or i == len(todo):
            echo(f"  {i:,}/{len(todo):,} done; {len(report.not_found):,} not in Tiingo, "
                 f"{len(report.failed):,} failed")  # fmt: skip
    return report


def _known(paths: Paths, ticker: str) -> bool:
    meta = read_meta(paths, ticker)
    return bool(meta and meta.get("startDate"))


def _get(client, url, limiter, policy) -> httpx.Response:
    return request_with_retry(client, "GET", url, limiter, policy)
