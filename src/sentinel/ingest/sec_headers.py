"""Signal-filing headers from EDGAR: the issuer's SIC code at the time and the acceptance time
(plan Step 6; research.md R9; FR-020, FR-021).

One header per preliminary-event signal filing dated from the labelled-window start. Headers are
stored raw and read-only at `data/raw/sec/headers/{year}/{accession}.txt`, one manifest line each,
and re-parsed into `core.filing_header` by `load_headers`. A page has two copies of the header: an
SGML block inside an HTML comment, and a readable one, the only place with the industry's name.
EDGAR has no such page for many filings from 2012 to 2014 (HTTP 404); for those the bare SGML
header (`{accession}.hdr.sgml`) is stored instead, with the same fields but no industry name.
A missing SIC is null, not a failure: some filers have none (G7 and D45 decide what that means).
"""

import html
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import duckdb
import httpx
import pyarrow as pa

from sentinel.config import Paths, registered_value
from sentinel.ingest import manifest
from sentinel.ingest.http import RateLimiter, RetryExhausted, RetryPolicy, stream_to_file
from sentinel.ingest.sec_bulk import tool_version
from sentinel.warehouse import table_exists

SOURCE = "sec_filing_header"


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


@dataclass(frozen=True)
class Target:
    accession: str
    issuer_cik: str
    filing_date: date

    @property
    def relpath(self) -> str:
        """Path under `data/raw/`."""
        return f"sec/headers/{self.filing_date.year}/{self.accession}.txt"


def header_limiter(params: dict) -> RateLimiter:
    ops = params["ops"]
    return RateLimiter(
        ops["sec_header_target_requests_per_second"], ops["sec_max_requests_per_second"]
    )


def signal_accessions(
    con: duckdb.DuckDBPyConnection, params: dict, paths: Paths, include_failed: bool = False
) -> list[Target]:
    """Signal filings of preliminary events from the labelled-window start without a stored
    header; earlier failures are left out unless `include_failed`."""
    skip_failed = (
        "and e.signal_accession not in (select accession from core.header_failure)"
        if not include_failed and table_exists(con, "core.header_failure")
        else ""
    )
    rows = con.execute(
        f"""
        select distinct e.signal_accession, e.issuer_cik, f.filing_date
        from evt.prelim_event e join core.filing f on f.accession = e.signal_accession
        where e.signal_date >= cast($start as DATE) {skip_failed}
        order by 1
        """,
        {"start": str(registered_value(params, "labelled_window_start"))},
    ).fetchall()
    targets = [Target(*row) for row in rows]
    return [t for t in targets if not (paths.data_raw / t.relpath).exists()]


def final_targets(
    con: duckdb.DuckDBPyConnection, paths: Paths, include_failed: bool = False
) -> list[Target]:
    """Signal filings of final-event candidates that may need a header (feature 004): at each
    issuer with a candidate whose G7 waits for one (`needs_header`), that candidate and every later
    one. Fetching only the waiting ones settles one event per round, because each new outcome moves
    the cooldowns and exposes the next date (OPKO Health would have taken dozens of rounds). Without
    a stored header; earlier failures are left out unless asked."""
    skip_failed = (
        "and c.signal_accession not in (select accession from core.header_failure)"
        if not include_failed and table_exists(con, "core.header_failure")
        else ""
    )
    rows = con.execute(
        f"""
        with waiting as (
            select issuer_cik, min(signal_date) as first_date from evt.event_candidate
            where outcome = 'needs_header' group by 1
        )
        select distinct c.signal_accession, c.issuer_cik, f.filing_date
        from evt.event_candidate c join waiting w using (issuer_cik)
        join core.filing f on f.accession = c.signal_accession
        where c.signal_date >= w.first_date
          and c.signal_accession not in (select accession from core.filing_header) {skip_failed}
        order by 1
        """
    ).fetchall()
    targets = [Target(*row) for row in rows]
    return [t for t in targets if not (paths.data_raw / t.relpath).exists()]


@dataclass
class FetchReport:
    stored: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def _store(paths: Paths, target: Target, book: manifest.Manifest, result) -> None:
    final = paths.data_raw / target.relpath
    os.replace(final.with_name(final.name + ".part"), final)
    os.chmod(final, 0o444)
    book.add(
        manifest.ManifestEntry(
            path=target.relpath,
            source=SOURCE,
            key=target.accession,
            role="original",
            url=result.url,
            fetched_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            bytes=result.bytes,
            sha256=result.sha256,
            http_last_modified=result.last_modified,
            http_etag=result.etag,
            tool=tool_version(),
        )
    )


def _fetch_one(paths, params, client, limiter, policy, target, book) -> str | None:
    """Store one header, falling back to the bare SGML header when the index page is missing;
    returns the failure reason, or None. A 403 raises SecForbidden."""
    final = paths.data_raw / target.relpath
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    ops = params["ops"]
    fields = {"cik": target.issuer_cik, "acc_nodash": target.accession.replace("-", ""),
              "acc": target.accession}  # fmt: skip
    page = ops["sec_headers_url_pattern"].format(**fields)
    sgml = ops["sec_headers_fallback_url_pattern"].format(**fields)
    try:
        try:
            result = stream_to_file(client, page, part, limiter, policy)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            result = stream_to_file(client, sgml, part, limiter, policy)
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code}"
    except RetryExhausted as e:
        return f"retries exhausted: {e}"
    try:
        parse_header(part.read_bytes().decode("utf-8", "replace"), target.accession)
    except HeaderParseError as e:
        part.unlink(missing_ok=True)
        return f"parse: {e}"
    _store(paths, target, book, result)
    return None


def fetch_headers(
    paths: Paths,
    params: dict,
    client: httpx.Client,
    limiter: RateLimiter,
    policy: RetryPolicy,
    targets: list[Target],
    limit: int | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> FetchReport:
    """Fetch the headers of `targets` (at most `limit`); stored ones are never fetched again."""
    book = manifest.Manifest(paths.manifest)
    report = FetchReport()
    todo = [t for t in targets if not book.has_path(t.relpath)]
    for done, target in enumerate(todo[:limit], start=1):
        reason = _fetch_one(paths, params, client, limiter, policy, target, book)
        if reason:
            report.failed.append((target.accession, reason))
        else:
            report.stored += 1
        if on_progress:
            on_progress(done)
    return report


def _ensure_failure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "create table if not exists core.header_failure "
        "(accession VARCHAR, reason VARCHAR, last_attempt TIMESTAMP)"
    )


def record_failures(con: duckdb.DuckDBPyConnection, failed: list[tuple[str, str]]) -> None:
    """Replace the `core.header_failure` rows of these accessions."""
    _ensure_failure_table(con)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    for accession, reason in failed:
        con.execute("delete from core.header_failure where accession = ?", [accession])
        con.execute("insert into core.header_failure values (?, ?, ?)", [accession, reason, now])


def load_headers(con: duckdb.DuckDBPyConnection, paths: Paths) -> int:
    """Re-parse every stored header into `core.filing_header`; parse failures are recorded."""
    rows, failed = [], []
    for entry in manifest.read_all(paths.manifest):
        if entry.source != SOURCE or entry.role != "original":
            continue
        try:
            text = (paths.data_raw / entry.path).read_bytes().decode("utf-8", "replace")
            h = parse_header(text, entry.key)
        except (OSError, HeaderParseError) as e:
            failed.append((entry.key, f"parse: {e}"))
            continue
        rows.append(
            (h.accession, h.issuer_cik, h.form_type, h.filed_as_of, h.accepted_at_et, h.sic,
             h.sic_label, entry.path)
        )  # fmt: skip
    names = ["accession", "issuer_cik", "form_type", "filed_as_of", "accepted_at_et", "sic",
             "sic_label", "raw_path"]  # fmt: skip
    types = [pa.string(), pa.string(), pa.string(), pa.date32(), pa.timestamp("s"), pa.string(),
             pa.string(), pa.string()]  # fmt: skip
    columns = list(zip(*rows, strict=True)) if rows else [[] for _ in names]
    con.register(
        "_headers",
        pa.table({n: pa.array(c, t) for n, c, t in zip(names, columns, types, strict=True)}),
    )
    try:
        con.execute("begin transaction")
        try:
            con.execute("create or replace table core.filing_header as select * from _headers")
            _ensure_failure_table(con)
            record_failures(con, failed)
            con.execute(
                "delete from core.header_failure "
                "where accession in (select accession from core.filing_header)"
            )
        except BaseException:
            con.execute("rollback")
            raise
        con.execute("commit")
    finally:
        con.unregister("_headers")
    return len(rows)
