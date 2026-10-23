"""FINRA's Tick Size Pilot change file (feature 004, research R13).

The daily pilot lists are discontinued, but `TSPilotChanges.txt` is cumulative from September 2016
to April 2019: every assignment of a ticker to a group (C = control; G1–G3 = quoted in $0.05
increments) with its effective and deleted dates. Stored as received, with a manifest line.
"""

import csv
import io
import os
from datetime import UTC, date, datetime

import httpx

from sentinel import __version__
from sentinel.config import Paths
from sentinel.ingest import manifest

SOURCE = "finra"
FILE = "TSPilotChanges.txt"
TEST_GROUPS = ("G1", "G2", "G3")


def fetch(paths: Paths, params: dict, echo=print) -> str:
    """Download the change file unless stored; returns 'stored' or 'kept'."""
    book = manifest.Manifest(paths.manifest)
    final = paths.finra / FILE
    if book.find_original(SOURCE, FILE) and final.exists():
        return "kept"
    url = params["ops"]["finra_tick_pilot_url"]
    resp = httpx.get(
        url,
        headers={"User-Agent": f"edgar-sentinel/{__version__}"},
        timeout=params["ops"]["http_timeout_seconds"],
        follow_redirects=True,
    )
    resp.raise_for_status()
    paths.finra.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    part.write_bytes(resp.content)
    os.replace(part, final)
    os.chmod(final, 0o444)
    book.add(
        manifest.ManifestEntry(
            path=final.relative_to(paths.data_raw).as_posix(), source=SOURCE, key=FILE,
            role="original", url=str(resp.url),
            fetched_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            bytes=len(resp.content), sha256=manifest.sha256_file(final),
            http_last_modified=resp.headers.get("Last-Modified"),
            http_etag=resp.headers.get("ETag"), tool="sentinel",
        )
    )  # fmt: skip
    echo(f"finra: {FILE} stored ({len(resp.content):,} bytes)")
    return "stored"


def _day(value: str) -> date | None:
    value = (value or "").strip()
    return date(int(value[:4]), int(value[4:6]), int(value[6:8])) if len(value) == 8 else None


def intervals(text: str) -> list[tuple[str, str, date, date | None, str]]:
    """(ticker, group, valid_from, valid_to, listing exchange) for the test groups. Each record
    opens (ticker, group, effective date); a record with a deleted date closes it, exclusive."""
    reader = csv.DictReader(io.StringIO(text.replace("\r\n", "\n")), delimiter="|")
    spans: dict[tuple[str, str, date], list] = {}
    for row in reader:
        group = (row.get("Tick_Size_Pilot_Program_Group") or "").strip()
        start = _day(row.get("Effective_Date"))
        if group not in TEST_GROUPS or start is None:
            continue
        key = (row["Ticker_Symbol"].strip(), group, start)
        span = spans.setdefault(key, [None, row.get("Listing_Exchange", "").strip()])
        deleted = _day(row.get("Deleted_Date"))
        if deleted is not None and (span[0] is None or deleted > span[0]):
            span[0] = deleted
    return sorted((t, g, s, end, ex) for (t, g, s), (end, ex) in spans.items())
