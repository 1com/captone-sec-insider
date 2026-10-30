"""Layer 2: market and macro sources into schema `stg_market`.

- `fred`: each FRED/ALFRED series, newest stored download: market series (yields, the yield-curve
  slope, the Fed funds rate, the Baa spread) are never revised and are available on their own date;
  released statistics (CPI, unemployment) are their **first release**, available from the day it
  was published.
- `vix`: Cboe's daily VIX close, newest stored copy.
- `short_volume`: FINRA's daily short-sale and total volume per symbol (off-exchange trades
  reported to FINRA), summed over its reporting facilities.
- `sic_industry`: Kenneth French's SIC-code ranges for the 12 and 49 industries.
"""

import io
import json
import re
import zipfile
from datetime import date

import duckdb

from sentinel import db
from sentinel.config import Paths
from sentinel.raw import manifest


def _newest(p: Paths, source: str) -> dict[str, manifest.ManifestEntry]:
    newest: dict[str, manifest.ManifestEntry] = {}
    for e in manifest.read_all(p.manifest):
        if e.source == source and e.role == "original":
            key = e.key.rsplit("-", 3)[0] if source == "fred" else source
            if key not in newest or e.key > newest[key].key:
                newest[key] = e
    return newest


def fred_observations(payload: bytes, mode: str) -> list[tuple[date, float, date]]:
    """(period, value, available from); FRED's "." (no value) is skipped."""
    rows = []
    for o in json.loads(payload)["observations"]:
        if o["value"] == ".":
            continue
        period = date.fromisoformat(o["date"])
        available = period if mode == "market" else date.fromisoformat(o["realtime_start"])
        rows.append((period, float(o["value"]), available))
    return rows


def sic_ranges(text: str) -> list[tuple[int, str, str, int, int]]:
    """(industry_no, short name, description, sic_from, sic_to) from a Siccodes file; an industry
    with no ranges (12 "Other") gets none. v1's parser."""
    out, industry = [], None
    for line in text.splitlines():
        is_range = re.match(r"^\s*\d{4}-\d{4}", line)
        if not is_range and (m := re.match(r"^\s*(\d+)\s+(\S+)\s+(.*?)\s*$", line)):
            industry = (int(m.group(1)), m.group(2), m.group(3))
            continue
        if (m := re.match(r"^\s*(\d{4})-(\d{4})", line)) and industry is not None:
            out.append((*industry, int(m.group(1)), int(m.group(2))))
    return out


def stage(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    counts = {"fred": _fred(con, p), "vix": _vix(con, p), "sic_industry": _sic(con, p)}
    counts["short_volume"] = _short(con, p, echo)
    echo(f"  market: {counts}")
    return counts


def _fred(con, p: Paths) -> int:
    rows = []
    for e in _newest(p, "fred").values():
        series, mode = e.key.split("-")[:2]
        payload = manifest.read_stored(p, e)  # checked; daily copies are gzip-compressed
        rows += [(series, mode, *r, e.path) for r in fred_observations(payload, mode)]
    with db.transaction(con):
        con.execute(
            "create or replace table stg_market.fred (series VARCHAR, mode VARCHAR, period DATE, "
            "value DOUBLE, available DATE, raw_file VARCHAR)"
        )
        if rows:
            con.executemany("insert into stg_market.fred values (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def _vix(con, p: Paths) -> int:
    newest = _newest(p, "cboe").get("cboe")
    with db.transaction(con):
        con.execute("create or replace table stg_market.vix (session DATE, close DOUBLE, "
                    "raw_file VARCHAR)")  # fmt: skip
        if newest:
            con.execute(
                "insert into stg_market.vix select strptime(\"DATE\", '%m/%d/%Y')::DATE, "
                'try_cast("CLOSE" as DOUBLE), ? from read_csv(?, header = true, '
                'all_varchar = true) where try_cast("CLOSE" as DOUBLE) is not null',
                [newest.path, (p.raw / newest.path).as_posix()],
            )
    return db.count(con, "stg_market.vix")


def _sic(con, p: Paths) -> int:
    rows = []
    for scheme in (12, 49):
        path = p.french / f"Siccodes{scheme}.zip"
        if not path.exists():
            continue
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as zf:
            text = zf.read(zf.namelist()[0]).decode("latin-1")
        rows += [(scheme, *r) for r in sic_ranges(text)]
    with db.transaction(con):
        con.execute(
            "create or replace table stg_market.sic_industry (scheme INTEGER, industry_no INTEGER, "
            "industry VARCHAR, description VARCHAR, sic_from INTEGER, sic_to INTEGER)"
        )
        if rows:
            con.executemany("insert into stg_market.sic_industry values (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def _short(con, p: Paths, echo=print) -> int:
    """One calendar month of files per batch, so memory stays bounded."""
    by_month: dict[str, list[str]] = {}
    for e in manifest.read_all(p.manifest):
        if e.source == "finra_short" and e.role == "original":
            by_month.setdefault(e.key.split("/")[1][:6], []).append((p.raw / e.path).as_posix())
    con.execute(
        "create or replace table stg_market._new_short_volume (session DATE, symbol VARCHAR, "
        "short_volume DOUBLE, total_volume DOUBLE, facilities INTEGER)"
    )
    for i, month in enumerate(sorted(by_month), 1):
        with db.transaction(con):
            con.execute(
                """
                insert into stg_market._new_short_volume
                with raw as (
                    select "Symbol" as symbol,
                           try_strptime(cast("Date" as VARCHAR), '%Y%m%d')::DATE as session,
                           try_cast("ShortVolume" as DOUBLE) as short_volume,
                           try_cast("TotalVolume" as DOUBLE) as total_volume
                    from read_csv($files, delim = '|', header = true, all_varchar = true,
                                  ignore_errors = true, union_by_name = true)
                )
                select session, symbol, sum(short_volume), sum(total_volume), count(*)
                from raw where session is not null and symbol is not null
                  and total_volume is not null
                group by 1, 2
                """,
                {"files": by_month[month]},
            )
        if i % 24 == 0:
            echo(f"  short volume: {i}/{len(by_month)} months")
    with db.transaction(con):
        con.execute("drop table if exists stg_market.short_volume")
        con.execute("alter table stg_market._new_short_volume rename to short_volume")
    return db.count(con, "stg_market.short_volume")
