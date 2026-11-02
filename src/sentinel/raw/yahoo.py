"""Yahoo daily prices (port of v1's `ingest/yahoo.py`; specs/001-daily-data-refresh, research R6).

- `fetch_window`: the last `prices.yahoo_window_days` days of every symbol in the newest SEC
  ticker list plus the reference symbols (SPY, IWM), in batches of `prices.yahoo_daily_batch_size`,
  one long-format file per batch (`yahoo/daily/<date>/batch-<NNN>.parquet`, a `ticker` column).
- `fetch_history`: a symbol's full history from `prices.history_start`, one file per symbol
  (`yahoo/history/<date>/<T>.parquet`), for symbols never asked (`--full-missing`).

Values are stored as Yahoo gives them (`auto_adjust=False`: the close is split-adjusted, the
adjusted close also dividend-adjusted). Symbols without Yahoo data for a full history go to
`yahoo/history/failures.csv`; v1's failure lists count as asked too.
"""

import csv
import gc
import io
import json
import time
from datetime import date, timedelta

import pandas as pd

from sentinel.config import Paths, sources
from sentinel.raw import FetchReport
from sentinel.raw.manifest import Manifest, store_bytes
from sentinel.reference.build import normalise

SOURCE = "yahoo"
FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
ATTEMPTS = 3
MIN_BATCH_SHARE = 0.75
FAILURE_FILES = ("yahoo/failures.csv", "yahoo/panel/failures.csv", "yahoo/history/failures.csv")


def _signature(start: date) -> str:
    return f"yfinance.download(start={start}, auto_adjust=False, actions=True)"


def listed_symbols(p: Paths, book: Manifest) -> list[str]:
    """Every symbol of the newest stored SEC ticker list (written as Yahoo writes class shares:
    `BRK-B`), plus the reference symbols, sorted."""
    lists = sorted(book.originals("sec_company_tickers"), key=lambda e: e.key)
    if not lists:
        raise FileNotFoundError("no SEC ticker list stored: run `sentinel fetch sec-tickers`")
    doc = json.loads((p.raw / lists[-1].path).read_text(encoding="utf-8"))
    symbols = {t for row in doc["data"] if (t := normalise(row[2]))}
    return sorted(symbols | set(sources(p)["prices"]["reference_symbols"]))


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


def _download(fetch, batch: list[str], start: date, sleep, echo):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fetch(batch, start=str(start), auto_adjust=False, actions=True,
                         group_by="ticker", threads=True, progress=False, timeout=30)  # fmt: skip
        except Exception as e:  # network or rate limit: back off and retry
            echo(f"  yahoo: attempt {attempt} failed ({type(e).__name__}: {e})"[:200])
            if attempt < ATTEMPTS:
                sleep(5 * attempt)
    return None


def _parquet(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    return buf.getvalue()


def _yfinance():
    import yfinance

    return yfinance.download


def _key_day(e) -> date:
    """The day a file was fetched for: the date in its key (`daily/<date>/…`,
    `history/<T>/<date>`), else its fetch time (v1's files)."""
    parts = e.key.split("/")
    if parts[0] == "daily":
        return date.fromisoformat(parts[1])
    if parts[0] == "history":
        return date.fromisoformat(parts[2])
    return date.fromisoformat(e.fetched_at[:10])


def newest_history_day(book: Manifest) -> dict[str, date]:
    """Each symbol's newest full-history download day (v1's files and later ones)."""
    out: dict[str, date] = {}
    for e in book.originals(SOURCE):
        if not e.key.startswith("daily/"):
            t = e.key.removeprefix("panel/").removeprefix("history/").split("/")[0]
            out[t] = max(out.get(t, _key_day(e)), _key_day(e))
    return out


def _stored_batch(p: Paths, book: Manifest, base_key: str) -> tuple[set[str], int]:
    """Tickers already stored for `base_key` (including `-rN` retry files) and the file count."""
    entries = [
        e for e in book.originals(SOURCE) if e.key == base_key or e.key.startswith(f"{base_key}/r")
    ]
    have: set[str] = set()
    for e in entries:
        have.update(pd.read_parquet(p.raw / e.path, columns=["ticker"])["ticker"].unique())
    return have, len(entries)


def _batch_complete(got: set[str], expected: list[str], refs: set[str]) -> bool:
    return (refs & set(expected)) <= got and len(got) >= int(MIN_BATCH_SHARE * len(expected))


def _collect_parts(frame, symbols: list[str], parts: dict[str, pd.DataFrame],
                   events: dict[str, date]) -> None:  # fmt: skip
    if frame is None:
        return
    for t in symbols:
        sub = _extract(frame, t)
        if sub is not None:
            parts[t] = sub.reset_index().assign(ticker=t)
            actions = [c for c in ("Dividends", "Stock Splits") if c in sub]
            moved = sub[(sub[actions].fillna(0) != 0).any(axis=1)] if actions else sub[:0]
            if len(moved):
                events[t] = moved.index.max().date()


def fetch_window(p: Paths, today: date, echo=print, con=None, window_days=None, full_missing=False,
                 fetch=None, sleep=time.sleep, **_) -> FetchReport:  # fmt: skip
    """Today's window for every listed symbol (and, with `full_missing`, full histories first).
    The window reaches back to three days before the last one, so missed days are caught up; a
    symbol whose window shows a split or a dividend after its newest full history gets its full
    history again (Yahoo rewrites the past after both; research R6, spec FR-019)."""
    fetch = fetch or _yfinance()
    report = FetchReport("yahoo")
    settings = sources(p)["prices"]
    book = Manifest(p.manifest)
    symbols = listed_symbols(p, book)
    if full_missing:
        fetch_history(p, today, missing_histories(p, book, symbols), fetch, sleep, echo, report,
                      book)  # fmt: skip
    start = today - timedelta(days=window_days or settings["yahoo_window_days"])
    windows = [_key_day(e) for e in book.originals(SOURCE) if e.key.startswith("daily/")]
    if windows and not window_days:
        start = min(start, max(windows) - timedelta(days=3))
    size, sub_size = settings["yahoo_daily_batch_size"], settings["yahoo_batch_size"]
    failed, refs = _failures(p), set(settings["reference_symbols"])
    events: dict[str, date] = {}
    for n, i in enumerate(range(0, len(symbols), size)):
        base_key = f"daily/{today}/{n:03d}"
        batch = symbols[i : i + size]
        expected = [t for t in batch if t not in failed] or batch
        have, n_files = _stored_batch(p, book, base_key)
        if n_files and _batch_complete(have, expected, refs):
            continue
        todo = [t for t in expected if t not in have] if n_files else batch
        report.requests += 1
        frame = _download(fetch, todo, start, sleep, echo)
        parts: dict[str, pd.DataFrame] = {}
        _collect_parts(frame, todo, parts, events)
        del frame
        for retry in range(1, ATTEMPTS):
            if _batch_complete(have | set(parts), expected, refs):
                break
            missing = [t for t in expected if t not in have and t not in parts]
            if not missing:
                break
            sleep(5 * retry)
            for j in range(0, len(missing), sub_size):
                chunk = missing[j : j + sub_size]
                report.requests += 1
                sub_frame = _download(fetch, chunk, start, sleep, echo)
                _collect_parts(sub_frame, chunk, parts, events)
                del sub_frame
                if j + sub_size < len(missing):
                    sleep(settings["yahoo_pause_seconds"])
        if not parts and not n_files:
            report.errors.append(f"batch {n:03d}: download failed")
            continue
        if parts:
            suffix = "" if n_files == 0 else f"-r{n_files}"
            rel = f"yahoo/daily/{today}/batch-{n:03d}{suffix}.parquet"
            key = base_key if n_files == 0 else f"{base_key}/r{n_files}"
            rows = pd.concat(list(parts.values()), ignore_index=True)[["ticker", "Date", *FIELDS]]
            store_bytes(p, book, SOURCE, rel, key, _parquet(rows), _signature(start))
            report.stored((p.raw / rel).stat().st_size)
            latest = rows["Date"].max().date()
            report.latest_date = max(report.latest_date or latest, latest)
            del rows
        del parts
        gc.collect()
        if i + size < len(symbols):
            sleep(settings["yahoo_pause_seconds"])
    newest = newest_history_day(book)
    stale = sorted(t for t, day in events.items() if newest.get(t, date.min) <= day)
    if stale:
        echo(f"  yahoo: {len(stale):,} symbols with a split or dividend: full histories again")
        fetch_history(p, today, stale, fetch, sleep, echo, report, book)
    echo(f"  yahoo: {len(symbols):,} symbols in {report.files_stored:,} files")
    return report


def _failures(p: Paths) -> set[str]:
    out = set()
    for rel in FAILURE_FILES:
        path = p.raw / rel
        if path.exists():
            with open(path, newline="") as f:
                out |= {r["ticker"] for r in csv.DictReader(f)}
    return out


def _add_failures(p: Paths, tickers: list[str]) -> None:
    path = p.raw / "yahoo/history/failures.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    known = _failures(p)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["ticker", "reason"])
        writer.writerows([t, "no_data"] for t in tickers if t not in known)


def missing_histories(p: Paths, book: Manifest, symbols: list[str]) -> list[str]:
    """Symbols with no stored Yahoo history (v1's files or a later one) and no recorded failure."""
    have = set()
    for e in book.originals(SOURCE):
        if not e.key.startswith("daily/"):
            have.add(e.key.removeprefix("panel/").removeprefix("history/").split("/")[0])
    failed = _failures(p)
    return [s for s in symbols if s not in have and s not in failed]


def fetch_history(p: Paths, today: date, symbols: list[str], fetch, sleep, echo,
                  report: FetchReport, book: Manifest) -> None:  # fmt: skip
    """Full histories from `prices.history_start`, one file per symbol, in batches of v1's size."""
    settings = sources(p)["prices"]
    start, size = settings["history_start"], settings["yahoo_batch_size"]
    todo = [s for s in symbols if not book.find_original(SOURCE, f"history/{s}/{today}")]
    echo(f"  yahoo: {len(todo):,} full histories to fetch")
    for i in range(0, len(todo), size):
        batch = todo[i : i + size]
        report.requests += 1
        frame = _download(fetch, batch, start, sleep, echo)
        if frame is None:
            report.errors.append(f"histories {i // size:03d}: download failed")
            continue
        none = []
        for t in batch:
            sub = _extract(frame, t)
            if sub is None:
                none.append(t)
                continue
            rel = f"yahoo/history/{today}/{t}.parquet"
            store_bytes(p, book, SOURCE, rel, f"history/{t}/{today}", _parquet(sub.reset_index()),
                        _signature(start))  # fmt: skip
            report.stored((p.raw / rel).stat().st_size)
        _add_failures(p, none)
        del frame
        gc.collect()
        if i + size < len(todo):
            sleep(settings["yahoo_pause_seconds"])
