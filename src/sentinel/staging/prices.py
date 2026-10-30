"""Layer 2: every price file downloaded from Yahoo and Tiingo, per source, into schemas `stg_yahoo`
and `stg_tiingo`.

- `stg_yahoo.price`: one row per ticker and day: open, high, low, close (split-adjusted, as Yahoo
  gives it), adjusted close, volume, dividend, split ratio.
- `stg_tiingo.price`: the same from Tiingo, with its adjusted columns, dividend and split factor.
  Tiingo's `[]` answers (a ticker without prices) are counted and skipped.
- `stg_tiingo.meta`: Tiingo's description of each fetched ticker (company name, exchange, first and
  last date); a ticker Tiingo did not know has a row with no name.
- `stg_tiingo.listing`: Tiingo's whole ticker list (`supported_tickers.zip`), every asset type.
- `stg_tiingo.search`: each company-name search and its hits, in Tiingo's order.

**Newest file wins** (specs/001-daily-data-refresh, data-model.md): a price file is a `history`
(a ticker's full series: v1's downloads, and full series fetched again after a split or dividend,
when the provider rewrites past adjusted values) or a `window` (the last days of many tickers,
fetched daily). For each ticker, the files that count are its history files and the windows
fetched after its newest history file; each day's row comes from the newest of them. The files and
their fetch times come from the manifest, so staging is the same built at once or day by day.

A ticker is not a company: tickers are reused, so matching prices to securities, with the date and
name checks, happens in `core`. Every row keeps its `raw_file`, `file_kind` and `fetched_at`.
"""

import csv
import gzip
import io
import json
import zipfile
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import duckdb
import pyarrow as pa

from sentinel import db
from sentinel.config import Paths
from sentinel.raw import manifest

TIINGO_META_DIRS = ("meta", "panel_meta", "listed_meta")
YAHOO_WINDOWS, TIINGO_WINDOWS = "yahoo/daily/", "tiingo/daily/"
YAHOO_FIELDS = ('"Open" as open, "High" as high, "Low" as low, "Close" as close, '
                '"Adj Close" as adj_close, "Volume"::DOUBLE as volume, "Dividends" as dividend, '
                '"Stock Splits" as split_ratio')  # fmt: skip
NEWEST = """
    with tagged as (
        select r.*, f.kind as file_kind, f.fetched_at from ({rows}) r join _files f using (raw_file)
    ),
    newest_history as (
        select ticker, max(fetched_at) as fetched_at from tagged where file_kind = 'history'
        group by ticker
    )
    select t.* from tagged t left join newest_history n on n.ticker = t.ticker
    where t.file_kind = 'history' or n.fetched_at is null or t.fetched_at > n.fetched_at
    qualify row_number() over (partition by t.ticker, t.session
                               order by t.fetched_at desc, t.raw_file desc) = 1
"""


def stored_price_files(p: Paths, source: str, suffix: str, windows: str) -> list[tuple]:
    """(path under data/raw, kind, fetched_at) of each stored price file of `source`: `window`
    under the `windows` folder, `history` otherwise."""
    return sorted(
        (e.path, "window" if e.path.startswith(windows) else "history",
         datetime.fromisoformat(e.fetched_at.replace("Z", "+00:00")).replace(tzinfo=None))
        for e in manifest.read_all(p.manifest)
        if e.source == source and e.role == "original" and e.path.endswith(suffix)
    )  # fmt: skip


def _register_files(con: duckdb.DuckDBPyConnection, files: list[tuple]) -> None:
    con.register("_files", pa.table({
        "raw_file": pa.array([f[0] for f in files], pa.string()),
        "kind": pa.array([f[1] for f in files], pa.string()),
        "fetched_at": pa.array([f[2] for f in files], pa.timestamp("s")),
    }))  # fmt: skip


def stage_yahoo(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    files = stored_price_files(p, "yahoo", ".parquet", YAHOO_WINDOWS)
    raw = p.raw.as_posix() + "/"
    args = {"history": [raw + f for f, kind, _ in files if kind == "history"],
            "window": [raw + f for f, kind, _ in files if kind == "window"]}  # fmt: skip
    parts = {
        "history": f"""select regexp_extract(filename, '([^/]+)\\.parquet$', 1) as ticker,
                              "Date"::DATE as session, {YAHOO_FIELDS},
                              replace(filename, '{raw}', '') as raw_file
                       from read_parquet($history, union_by_name = true, filename = true)
                       where "Date" is not null""",
        "window": f"""select ticker, "Date"::DATE as session, {YAHOO_FIELDS},
                             replace(filename, '{raw}', '') as raw_file
                      from read_parquet($window, union_by_name = true, filename = true)
                      where "Date" is not null""",
    }  # fmt: skip
    used = [k for k in parts if args[k]]
    if not used:
        raise FileNotFoundError("no Yahoo price files in the manifest: run `sentinel fetch yahoo`")
    _register_files(con, files)
    try:
        with db.transaction(con):
            con.execute(
                "create or replace table stg_yahoo.price as "
                + NEWEST.format(rows=" union all ".join(parts[k] for k in used)),
                {k: args[k] for k in used},
            )
    finally:
        con.unregister("_files")
    n = db.count(con, "stg_yahoo.price")
    counts = {"history_files": len(args["history"]), "window_files": len(args["window"]),
              "price": n}  # fmt: skip
    echo(f"  yahoo: {counts}")
    return counts


def _is_price_csv(path) -> bool:
    """Whether a stored Tiingo answer is a price table: for a ticker without prices Tiingo answers
    `[]`, which is stored as received."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.readline().startswith("date,")


def stage_tiingo(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    stored = stored_price_files(p, "tiingo", ".csv.gz", TIINGO_WINDOWS)
    files = [f for f in stored if _is_price_csv(p.raw / f[0])]
    raw = p.raw.as_posix() + "/"
    numeric = ["close", "high", "low", "open", "volume", "adjClose", "adjHigh", "adjLow", "adjOpen",
               "adjVolume", "divCash", "splitFactor"]  # fmt: skip
    types = {"date": "VARCHAR", **{c: "DOUBLE" for c in numeric}}
    rows = f"""
        select regexp_extract(filename, '([^/]+)\\.csv\\.gz$', 1) as ticker,
               try_cast(left("date", 10) as DATE) as session, open, high, low, close, volume,
               "adjOpen" as adj_open, "adjHigh" as adj_high, "adjLow" as adj_low,
               "adjClose" as adj_close, "adjVolume" as adj_volume, "divCash" as dividend,
               "splitFactor" as split_factor, replace(filename, '{raw}', '') as raw_file
        from read_csv($files, header = true, columns = $types, filename = true,
                      union_by_name = true)
        where try_cast(left("date", 10) as DATE) is not null
    """
    if not files:
        raise FileNotFoundError("no Tiingo price files in the manifest: `sentinel fetch tiingo`")
    _register_files(con, files)
    try:
        with db.transaction(con):
            con.execute(
                "create or replace table stg_tiingo.price as " + NEWEST.format(rows=rows),
                {"files": [raw + f[0] for f in files], "types": types},
            )
    finally:
        con.unregister("_files")
    n = db.count(con, "stg_tiingo.price")
    meta = _tiingo_meta(con, p)
    listing = _tiingo_listing(con, p)
    search = _tiingo_search(con, p)
    empty = len(stored) - len(files)
    window = sum(1 for f in files if f[1] == "window")
    echo(f"  tiingo: {len(files):,} price files ({window:,} daily, {empty:,} without prices), "
         f"{n:,} rows; {meta:,} meta, {listing:,} listed, {search:,} search hits")  # fmt: skip
    return {"files": len(files), "window_files": window, "no_prices": empty, "price": n,
            "meta": meta, "listing": listing, "search": search}  # fmt: skip


def _tiingo_meta(con, p: Paths) -> int:
    rows = []
    for d in TIINGO_META_DIRS:
        for f in sorted((p.tiingo / d).glob("*.json.gz")):
            doc = json.loads(gzip.decompress(f.read_bytes()))
            known = isinstance(doc, dict) and bool(doc.get("ticker"))
            rows.append((
                f.name.removesuffix(".json.gz"), doc.get("name") if known else None,
                doc.get("exchangeCode") if known else None,
                (doc.get("startDate") or None) if known else None,
                (doc.get("endDate") or None) if known else None,
                f.relative_to(p.raw).as_posix(),
            ))  # fmt: skip
    with db.transaction(con):
        con.execute(
            "create or replace table stg_tiingo.meta (ticker VARCHAR, name VARCHAR, "
            "exchange VARCHAR, start_date DATE, end_date DATE, raw_file VARCHAR)"
        )
        if rows:
            con.executemany("insert into stg_tiingo.meta values (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def _tiingo_listing(con, p: Paths) -> int:
    path = p.tiingo / "supported_tickers.zip"
    rows = []
    if path.exists():
        with zipfile.ZipFile(path) as zf, zf.open(zf.namelist()[0]) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                rows.append((r["ticker"], r["exchange"] or None, r["assetType"] or None,
                             r["priceCurrency"] or None, r["startDate"] or None,
                             r["endDate"] or None))  # fmt: skip
    with db.transaction(con):
        con.execute(
            "create or replace table stg_tiingo.listing (ticker VARCHAR, exchange VARCHAR, "
            "asset_type VARCHAR, currency VARCHAR, start_date DATE, end_date DATE)"
        )
        if rows:
            con.executemany("insert into stg_tiingo.listing values (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def _tiingo_search(con, p: Paths) -> int:
    rows = []
    for e in manifest.read_all(p.manifest):
        if e.source != "tiingo" or "search/" not in e.key or e.role != "original":
            continue
        query = (parse_qs(urlparse(e.url).query).get("query") or [""])[0]
        hits = json.loads(gzip.decompress((p.raw / e.path).read_bytes()))
        for rank, h in enumerate(hits if isinstance(hits, list) else []):
            rows.append((query, rank, h.get("ticker"), h.get("name"), h.get("assetType"),
                         h.get("isActive"), h.get("countryCode"), e.path))  # fmt: skip
    with db.transaction(con):
        con.execute(
            "create or replace table stg_tiingo.search (query VARCHAR, hit_rank INTEGER, "
            "ticker VARCHAR, name VARCHAR, asset_type VARCHAR, is_active BOOLEAN, "
            "country VARCHAR, raw_file VARCHAR)"
        )
        if rows:
            con.executemany("insert into stg_tiingo.search values (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)
