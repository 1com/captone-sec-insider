"""Yahoo Finance daily prices for listed event companies, SPY and IWM (feature 004, research R2).

With `auto_adjust=False`, Yahoo's Open, High, Low, Close and Volume are split-adjusted, Adj Close is
also dividend-adjusted, and Stock Splits gives each split's ratio on its date. Each ticker's frame
is stored as received, one Parquet file per ticker, with a manifest line. Yahoo data is for
personal use: no committed or published file holds these prices (constitution VI).
"""

import csv
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb

from sentinel.config import Paths
from sentinel.ingest import manifest

SOURCE = "yahoo"
FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
ATTEMPTS = 3


@dataclass
class DownloadReport:
    requested: int = 0
    cached: int = 0
    skipped_failed: int = 0
    stored: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def call_signature(start: str) -> str:
    return f"yfinance.download(start={start}, auto_adjust=False, actions=True)"


def universe_tickers(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """Yahoo-mapped tickers of issuers with a preliminary event from `rules.final_detection_start`,
    plus the reference symbols (SPY, IWM)."""
    rows = con.execute(
        """
        select distinct m.ticker from core.symbol_map m
        where m.price_source = 'yahoo' and m.issuer_cik in (
            select issuer_cik from evt.prelim_event where signal_date >= cast(? as DATE))
        """,
        [str(params["rules"]["final_detection_start"])],
    ).fetchall()
    return sorted({r[0] for r in rows} | set(params["ops"]["reference_symbols"]))


def primary_tickers(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Each Yahoo-mapped issuer's primary ticker: the current ticker most often reported in its own
    Form 4 filings, ties broken alphabetically (research R2)."""
    from sentinel.core.symbols import split_symbols

    current: dict[str, list[str]] = {}
    for cik, ticker in con.execute(
        "select issuer_cik, ticker from core.symbol_map where price_source = 'yahoo' order by 1, 2"
    ).fetchall():
        current.setdefault(cik, []).append(ticker)
    reported: dict[str, Counter] = {cik: Counter() for cik in current}
    for cik, raw, n in con.execute(
        """
        select issuer_cik, symbol_raw, count(*) from core.filing
        where symbol_raw is not null
          and issuer_cik in (select issuer_cik from core.symbol_map where price_source = 'yahoo')
        group by 1, 2
        """
    ).fetchall():
        for ticker in split_symbols(raw):
            reported[cik][ticker] += n
    return {
        cik: min(tickers, key=lambda t: (-reported[cik][t], t)) for cik, tickers in current.items()
    }


def cache_path(paths: Paths, ticker: str):
    return paths.yahoo / f"{ticker}.parquet"


def _failures(paths: Paths) -> dict[str, str]:
    path = paths.yahoo / "failures.csv"
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["ticker"]: r["reason"] for r in csv.DictReader(f)}


def _write_failures(paths: Paths, failures: dict[str, str]) -> None:
    path = paths.yahoo / "failures.csv"
    if not failures:
        path.unlink(missing_ok=True)
        return
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "reason"])
        writer.writerows(sorted(failures.items()))


def _extract(frame, ticker: str):
    """One ticker's rows from a `group_by="ticker"` frame, Yahoo's columns kept; None if empty."""
    if frame is None or frame.empty or ticker not in frame.columns.get_level_values(0):
        return None
    sub = frame[ticker][[c for c in FIELDS if c in frame[ticker].columns]]
    sub = sub.dropna(subset=["Close"])
    if sub.empty:
        return None
    sub.index = sub.index.tz_localize(None) if sub.index.tz is not None else sub.index
    sub.index.name = "Date"
    return sub


def _store(paths: Paths, book: manifest.Manifest, ticker: str, frame, start: str) -> None:
    final = cache_path(paths, ticker)
    part = final.with_name(final.name + ".part")
    frame.to_parquet(part)
    os.replace(part, final)
    os.chmod(final, 0o444)
    book.add(
        manifest.ManifestEntry(
            path=final.relative_to(paths.data_raw).as_posix(),
            source=SOURCE,
            key=ticker,
            role="original",
            url=call_signature(start),
            fetched_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            bytes=final.stat().st_size,
            sha256=manifest.sha256_file(final),
            http_last_modified=None,
            http_etag=None,
            tool="sentinel",
        )
    )


def download(
    paths: Paths,
    params: dict,
    tickers: list[str],
    *,
    limit: int | None = None,
    retry_failures: bool = False,
    fetch=None,
    sleep=time.sleep,
    echo=print,
) -> DownloadReport:
    """Fetch every ticker not yet stored, in batches; failures go to `data/raw/yahoo/failures.csv`.

    `fetch` defaults to `yfinance.download`; tests pass a stand-in.
    """
    if fetch is None:
        import yfinance

        fetch = yfinance.download
    ops = params["ops"]
    start = str(params["rules"]["price_history_start"])
    paths.yahoo.mkdir(parents=True, exist_ok=True)
    book = manifest.Manifest(paths.manifest)
    failures = _failures(paths)
    report = DownloadReport(requested=len(tickers))
    todo = []
    for t in tickers:
        if book.find_original(SOURCE, t) and cache_path(paths, t).exists():
            report.cached += 1
        elif t in failures and not retry_failures:
            report.skipped_failed += 1
        else:
            todo.append(t)
    if limit is not None:
        todo = todo[:limit]
    echo(f"yahoo: {report.cached:,} stored, {report.skipped_failed:,} earlier failures skipped, "
         f"{len(todo):,} to download")  # fmt: skip
    size = ops["yahoo_batch_size"]
    for i in range(0, len(todo), size):
        batch, frame = todo[i : i + size], None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                frame = fetch(
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
                echo(f"  batch {i // size + 1}: attempt {attempt} failed ({e})")
                if attempt < ATTEMPTS:
                    sleep(5 * attempt)
        for t in batch:
            sub = _extract(frame, t) if frame is not None else None
            if sub is None:
                failures[t] = "download_error" if frame is None else "no_data"
                report.failed.append((t, failures[t]))
            else:
                _store(paths, book, t, sub, start)
                failures.pop(t, None)
                report.stored += 1
        done = min(i + size, len(todo))
        if done % 250 < size or done == len(todo):
            echo(f"  {done:,}/{len(todo):,} done, {len(report.failed):,} failed")
        if done < len(todo):
            sleep(ops["yahoo_pause_seconds"])
    _write_failures(paths, failures)
    return report
