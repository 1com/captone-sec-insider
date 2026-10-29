"""Layer 2: SEC filing headers (`data/raw/sec/headers/<year>/<accession>.txt`) and the SEC's daily
company–ticker lists (`data/raw/sec/reference/company_tickers_exchange_<date>.json`), into schemas
`stg_sec_headers` and `stg_sec_tickers`.

A header gives a filing's exact acceptance time (US Eastern, as EDGAR states it) and the issuer's
SIC code at the time; the parser is v1's (`ingest/sec_headers.py`), unchanged. Files that do not
parse go to `stg_sec_headers.parse_failure`.
"""

import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime

import duckdb
import pyarrow as pa

from sentinel import db
from sentinel.config import Paths
from sentinel.raw import manifest

HEADER_SOURCE = "sec_filing_header"
TICKERS_PREFIX = "company_tickers_exchange_"


class HeaderParseError(Exception):
    """The text is not an EDGAR filing header, or not the expected filing's."""


@dataclass(frozen=True)
class Header:
    accession: str
    form_type: str
    filed_as_of: date
    accepted_at_et: datetime  # as EDGAR states it, US Eastern time
    issuer_cik: str | None
    sic: str | None
    sic_label: str | None


def _first(text: str, *patterns: str) -> str | None:
    for pattern in patterns:
        if m := re.search(pattern, text):
            return m.group(1).strip()
    return None


def parse_header(text: str, expect_accession: str | None = None) -> Header:
    raw = html.unescape(text)
    accepted = _first(raw, r"<ACCEPTANCE-DATETIME>\s*(\d{14})")
    accession = _first(raw, r"<ACCESSION-NUMBER>\s*(\S+)", r"ACCESSION NUMBER:\s*(\S+)")
    form_type = _first(raw, r"<TYPE>\s*([^\n<]+)", r"CONFORMED SUBMISSION TYPE:\s*([^\n]+)")
    filed = _first(raw, r"<FILING-DATE>\s*(\d{8})", r"FILED AS OF DATE:\s*(\d{8})")
    if not (accepted and accession and form_type and filed):
        raise HeaderParseError("no acceptance time, accession, form type or filing date")
    if expect_accession and accession != expect_accession:
        raise HeaderParseError(f"accession {accession}, expected {expect_accession}")
    sgml = _first(raw, r"(?s)<ISSUER>(.*?)</ISSUER>") or ""
    readable = _first(raw, r"(?ms)^ISSUER:(.*?)(?=^\S|\Z)") or ""
    classification = re.search(
        r"STANDARD INDUSTRIAL CLASSIFICATION:[ \t]*([^\n\[]*?)[ \t]*\[(\d{4})\]", readable
    )
    sic = _first(sgml, r"<ASSIGNED-SIC>\s*(\d{4})") or (classification and classification[2])
    label = classification[1].strip() if classification and classification[2] == sic else None
    cik = _first(sgml, r"<CIK>\s*(\d+)") or _first(readable, r"CENTRAL INDEX KEY:\s*(\d+)")
    return Header(
        accession=accession,
        form_type=form_type,
        filed_as_of=datetime.strptime(filed, "%Y%m%d").date(),
        accepted_at_et=datetime.strptime(accepted, "%Y%m%d%H%M%S"),
        issuer_cik=(cik.lstrip("0") or None) if cik else None,
        sic=sic or None,
        sic_label=label or None,
    )


HEADER_SCHEMA = pa.schema([
    ("accession", pa.string()), ("issuer_cik", pa.string()), ("form_type", pa.string()),
    ("filed_as_of", pa.date32()), ("accepted_at_et", pa.timestamp("s")), ("sic", pa.string()),
    ("sic_label", pa.string()), ("raw_file", pa.string()),
])  # fmt: skip


def stage_headers(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    rows, failed = [], []
    for entry in manifest.read_all(p.manifest):
        if entry.source != HEADER_SOURCE or entry.role != "original":
            continue
        try:
            text = (p.raw / entry.path).read_bytes().decode("utf-8", "replace")
            h = parse_header(text, entry.key)
        except (OSError, HeaderParseError) as e:
            failed.append((entry.key, str(e), entry.path))
            continue
        rows.append((h.accession, h.issuer_cik, h.form_type, h.filed_as_of, h.accepted_at_et,
                     h.sic, h.sic_label, entry.path))  # fmt: skip
    cols = list(zip(*rows, strict=True)) if rows else [[] for _ in HEADER_SCHEMA]
    table = pa.Table.from_arrays(
        [pa.array(c, f.type) for c, f in zip(cols, HEADER_SCHEMA, strict=True)],
        schema=HEADER_SCHEMA,
    )
    con.register("_h", table)
    try:
        with db.transaction(con):
            con.execute("create or replace table stg_sec_headers.header as select * from _h")
            con.execute("create or replace table stg_sec_headers.parse_failure "
                        "(accession VARCHAR, reason VARCHAR, raw_file VARCHAR)")  # fmt: skip
            if failed:
                con.executemany("insert into stg_sec_headers.parse_failure values (?, ?, ?)",
                                failed)  # fmt: skip
    finally:
        con.unregister("_h")
    echo(f"  headers: {len(rows):,} parsed, {len(failed):,} failed")
    return {"header": len(rows), "parse_failure": len(failed)}


def stage_tickers(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """Every stored daily snapshot of the SEC company–ticker list, in the SEC's order (`rank` 0 is
    the largest company), so a company's first ticker in a snapshot is its main one."""
    rows = []
    for path in sorted(p.sec_reference.glob(f"{TICKERS_PREFIX}*.json")):
        day = datetime.strptime(path.stem.removeprefix(TICKERS_PREFIX), "%Y%m%d").date()
        doc = json.loads(path.read_text(encoding="utf-8"))
        rel = path.relative_to(p.raw).as_posix()
        rows += [
            (day, str(int(cik)), name, ticker, exchange, rank, rel)
            for rank, (cik, name, ticker, exchange) in enumerate(doc["data"])
            if ticker
        ]
    with db.transaction(con):
        con.execute(
            "create or replace table stg_sec_tickers.snapshot (snapshot_date DATE, cik VARCHAR, "
            "name VARCHAR, ticker VARCHAR, exchange VARCHAR, rank INTEGER, raw_file VARCHAR)"
        )
        if rows:
            con.executemany("insert into stg_sec_tickers.snapshot values (?, ?, ?, ?, ?, ?, ?)",
                            rows)  # fmt: skip
    echo(f"  ticker snapshots: {len(rows):,} rows")
    return {"snapshot": len(rows)}
