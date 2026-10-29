"""Layer 2: every price file downloaded from Yahoo and Tiingo, complete per source, into schemas
`stg_yahoo` and `stg_tiingo`.

- `stg_yahoo.price`: one row per ticker and day from every Yahoo file (`data/raw/yahoo/*.parquet`,
  `data/raw/yahoo/panel/*.parquet`): as-traded open, high, low, close, adjusted close, volume,
  dividend, split ratio.
- `stg_tiingo.price`: the same from every Tiingo price file (`prices/`, `panel_prices/`,
  `listed_prices/`), with Tiingo's adjusted columns, dividend and split factor. Tiingo's `[]`
  answers (a ticker without prices) are counted and skipped.
- `stg_tiingo.meta`: Tiingo's description of each fetched ticker (company name, exchange, first and
  last date); a ticker Tiingo did not know has a row with no name.
- `stg_tiingo.listing`: Tiingo's whole ticker list (`supported_tickers.zip`), every asset type.
- `stg_tiingo.search`: each company-name search and its hits, in Tiingo's order.

A ticker is not a company: tickers are reused, so matching prices to securities, with the date and
name checks, happens in `core`. The same ticker can appear in several files (two folders); every
row keeps its `raw_file`.
"""

import csv
import gzip
import io
import json
import zipfile
from urllib.parse import parse_qs, urlparse

import duckdb

from sentinel import db
from sentinel.config import Paths
from sentinel.raw import manifest

TIINGO_PRICE_DIRS = ("prices", "panel_prices", "listed_prices")
TIINGO_META_DIRS = ("meta", "panel_meta", "listed_meta")


def stage_yahoo(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    files = [f.as_posix() for f in sorted(p.yahoo.glob("*.parquet"))]
    files += [f.as_posix() for f in sorted((p.yahoo / "panel").glob("*.parquet"))]
    raw = p.raw.as_posix() + "/"
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table stg_yahoo.price as
            select regexp_extract(filename, '([^/]+)\\.parquet$', 1) as ticker,
                   "Date"::DATE as session, "Open" as open, "High" as high, "Low" as low,
                   "Close" as close, "Adj Close" as adj_close, "Volume"::DOUBLE as volume,
                   "Dividends" as dividend, "Stock Splits" as split_ratio,
                   replace(filename, '{raw}', '') as raw_file
            from read_parquet($files, union_by_name = true, filename = true)
            where "Date" is not null
            """,
            {"files": files},
        )
    n = db.count(con, "stg_yahoo.price")
    echo(f"  yahoo: {len(files):,} files, {n:,} rows")
    return {"files": len(files), "price": n}


def _is_price_csv(path) -> bool:
    """Whether a stored Tiingo answer is a price table: for a ticker without prices Tiingo answers
    `[]`, which is stored as received."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.readline().startswith("date,")


def stage_tiingo(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    stored = [f for d in TIINGO_PRICE_DIRS for f in sorted((p.tiingo / d).glob("*.csv.gz"))]
    files = [f.as_posix() for f in stored if _is_price_csv(f)]
    raw = p.raw.as_posix() + "/"
    numeric = ["close", "high", "low", "open", "volume", "adjClose", "adjHigh", "adjLow", "adjOpen",
               "adjVolume", "divCash", "splitFactor"]  # fmt: skip
    types = {"date": "VARCHAR", **{c: "DOUBLE" for c in numeric}}
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table stg_tiingo.price as
            select regexp_extract(filename, '([^/]+)\\.csv\\.gz$', 1) as ticker,
                   try_cast(left("date", 10) as DATE) as session, open, high, low, close, volume,
                   "adjOpen" as adj_open, "adjHigh" as adj_high, "adjLow" as adj_low,
                   "adjClose" as adj_close, "adjVolume" as adj_volume, "divCash" as dividend,
                   "splitFactor" as split_factor, replace(filename, '{raw}', '') as raw_file
            from read_csv($files, header = true, columns = $types, filename = true,
                          union_by_name = true)
            where try_cast(left("date", 10) as DATE) is not null
            """,
            {"files": files, "types": types},
        )
    n = db.count(con, "stg_tiingo.price")
    meta = _tiingo_meta(con, p)
    listing = _tiingo_listing(con, p)
    search = _tiingo_search(con, p)
    empty = len(stored) - len(files)
    echo(f"  tiingo: {len(files):,} price files ({empty:,} without prices), {n:,} rows; "
         f"{meta:,} meta, {listing:,} listed tickers, {search:,} search hits")  # fmt: skip
    return {"files": len(files), "no_prices": empty, "price": n, "meta": meta, "listing": listing,
            "search": search}  # fmt: skip


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
