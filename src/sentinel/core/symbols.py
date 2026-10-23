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

import httpx

from sentinel import __version__

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
