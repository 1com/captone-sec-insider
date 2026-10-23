"""Yahoo Finance daily prices: cached download and loading (research R2).

With auto_adjust=False, Yahoo's Open/High/Low/Close and Volume are split-adjusted, Adj Close is also
dividend-adjusted, and Stock Splits gives each split ratio. As-traded prices (for the $2 floor) are
rebuilt by undoing later splits. Yahoo data is for personal use: the dashboard shows only derived
results, never these prices.
"""

import hashlib
import logging
import os
import time
import warnings
from datetime import UTC, datetime

import pandas as pd

from mvp.config import MANIFEST, RAW, YAHOO
from sentinel.ingest.manifest import ManifestEntry, append, read_all

log = logging.getLogger(__name__)
FAILURES = RAW / "yahoo_failures.csv"
COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "splits",
}


def cache_path(ticker: str):
    return YAHOO / f"{ticker.replace('/', '-')}.parquet"


def _extract(df: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    if isinstance(df.columns, pd.MultiIndex):
        if ticker not in df.columns.get_level_values(0):
            return None
        sub = df[ticker]
    else:
        sub = df
    sub = sub.rename(columns=COLUMNS)
    sub = sub[[c for c in COLUMNS.values() if c in sub.columns]].dropna(subset=["close"])
    if sub.empty:
        return None
    sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
    sub.index.name = "date"
    return sub


def _store(ticker: str, frame: pd.DataFrame) -> None:
    final = cache_path(ticker)
    part = final.with_name(final.name + ".part")
    frame.to_parquet(part)
    os.replace(part, final)
    data = final.read_bytes()
    append(
        MANIFEST,
        ManifestEntry(
            path=final.relative_to(RAW).as_posix(),
            source="yahoo",
            key=ticker,
            role="original",
            url="yfinance.download(auto_adjust=False, actions=True)",
            fetched_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            http_last_modified=None,
            http_etag=None,
            tool="mvp",
        ),
    )


def download(
    tickers: list[str], *, start: str, batch_size: int, retries: int, pause: float, echo=print
) -> dict:
    """Fetch every ticker not already cached. Returns counts; failures go to yahoo_failures.csv."""
    import yfinance as yf

    YAHOO.mkdir(parents=True, exist_ok=True)
    recorded = {e.key for e in read_all(MANIFEST) if e.source == "yahoo"}
    todo = [t for t in tickers if t not in recorded or not cache_path(t).exists()]
    failed: list[str] = []
    echo(f"yahoo: {len(tickers) - len(todo)} cached, {len(todo)} to download")
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        frame = None
        for attempt in range(1, retries + 1):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    frame = yf.download(
                        batch,
                        start=start,
                        auto_adjust=False,
                        actions=True,
                        group_by="ticker",
                        threads=True,
                        progress=False,
                        timeout=30,
                    )
                break
            except Exception as e:  # network or rate limit: back off and retry
                echo(f"  batch {i // batch_size + 1}: attempt {attempt} failed ({e}); retrying")
                time.sleep(5 * attempt)
        for t in batch:
            sub = _extract(frame, t) if frame is not None else None
            if sub is None:
                failed.append(t)
            else:
                _store(t, sub)
        echo(f"  {min(i + batch_size, len(todo))}/{len(todo)} done, {len(failed)} failed so far")
        time.sleep(pause)
    if failed:
        pd.DataFrame({"ticker": failed}).to_csv(FAILURES, index=False)
    return {"requested": len(tickers), "downloaded": len(todo) - len(failed), "failed": len(failed)}


def load(ticker: str) -> pd.DataFrame | None:
    """Prices with an `unadj_close` column (as-traded close, later splits undone)."""
    path = cache_path(ticker)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    splits = df["splits"].fillna(0.0).replace(0.0, 1.0) if "splits" in df else 1.0
    future = splits[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    df["unadj_close"] = df["close"] * future
    return df


def load_many(tickers) -> dict[str, pd.DataFrame]:
    out = {}
    for t in tickers:
        df = load(t)
        if df is not None:
            out[t] = df
    return out
