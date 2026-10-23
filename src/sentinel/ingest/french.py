"""The Kenneth French Data Library (feature 004, research R12): daily factors, industry portfolio
returns, SIC-to-industry definitions and NYSE size breakpoints, stored as received.

The CSV files start with free text and hold one or more sections, each a title line, a header
line beginning with a comma, and rows `YYYYMMDD, v1, v2, …` in percent; −99.99 and −999 mean
missing. Free for research use.
"""

import io
import os
import re
import zipfile
from datetime import UTC, date, datetime

import httpx

from sentinel import __version__
from sentinel.config import Paths
from sentinel.ingest import manifest

SOURCE = "french"
MISSING = {-99.99, -999.0}
_ROW = re.compile(r"^\s*(\d{6}|\d{8})\s*,")


def fetch(paths: Paths, params: dict, echo=print) -> dict[str, str]:
    """Download each `ops.french_files` zip unless stored; returns {file: 'stored' | 'kept'}."""
    book = manifest.Manifest(paths.manifest)
    paths.french.mkdir(parents=True, exist_ok=True)
    ops, done = params["ops"], {}
    with httpx.Client(
        headers={"User-Agent": f"edgar-sentinel/{__version__}"},
        timeout=ops["http_timeout_seconds"],
        follow_redirects=True,
    ) as client:
        for name in ops["french_files"]:
            final = paths.french / name
            if book.find_original(SOURCE, name) and final.exists():
                done[name] = "kept"
                continue
            resp = client.get(ops["french_base_url"] + name)
            resp.raise_for_status()
            part = final.with_name(final.name + ".part")
            part.write_bytes(resp.content)
            os.replace(part, final)
            os.chmod(final, 0o444)
            now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            book.add(
                manifest.ManifestEntry(
                    path=final.relative_to(paths.data_raw).as_posix(), source=SOURCE, key=name,
                    role="original", url=str(resp.url), fetched_at=now, bytes=len(resp.content),
                    sha256=manifest.sha256_file(final),
                    http_last_modified=resp.headers.get("Last-Modified"),
                    http_etag=resp.headers.get("ETag"), tool="sentinel",
                )
            )  # fmt: skip
            echo(f"french: {name} stored ({len(resp.content):,} bytes)")
            done[name] = "stored"
    return done


def read_member(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return zf.read(zf.namelist()[0]).decode("latin-1")


def _date(token: str) -> date:
    token = token.strip()
    return date(int(token[:4]), int(token[4:6]), int(token[6:8]) if len(token) == 8 else 1)


def _value(token: str) -> float | None:
    token = token.strip()
    if not token:
        return None
    value = float(token)
    return None if value in MISSING else value


def sections(text: str) -> dict[str, tuple[list[str], list[tuple[date, list[float | None]]]]]:
    """{section title: (columns, rows)}; the first untitled section is called "main"."""
    out: dict = {}
    title, current, last_text = None, None, ""
    for line in text.splitlines():
        if line.startswith(","):
            title = last_text.strip() if last_text.startswith((" ", "\t")) else "main"
            columns = [c.strip() for c in line.split(",")[1:] if c.strip()]
            current = out.setdefault(title, (columns, []))
        elif _ROW.match(line) and current is not None:
            cells = line.split(",")
            current[1].append((_date(cells[0]), [_value(c) for c in cells[1:]][: len(current[0])]))
        elif line.strip():
            last_text = line
            if not _ROW.match(line) and current is not None and current[1]:
                current = None  # a new block of text ends the section
    return out


def sic_ranges(text: str) -> list[tuple[int, str, str, int, int]]:
    """(industry_no, short name, description, sic_from, sic_to) from a Siccodes file. An industry
    with no ranges (e.g. 12 "Other") gets none."""
    out, industry = [], None
    for line in text.splitlines():
        is_range = re.match(r"^\s*\d{4}-\d{4}", line)
        if not is_range and (m := re.match(r"^\s*(\d+)\s+(\S+)\s+(.*?)\s*$", line)):
            industry = (int(m.group(1)), m.group(2), m.group(3))
            continue
        if (m := re.match(r"^\s*(\d{4})-(\d{4})", line)) and industry is not None:
            out.append((*industry, int(m.group(1)), int(m.group(2))))
    return out


def breakpoints(text: str) -> list[tuple[date, int, int, float]]:
    """(month, firms, percentile, $ millions) from ME_Breakpoints: every 5th NYSE percentile."""
    out = []
    for line in text.splitlines():
        if re.match(r"^\s*\d{6}\s*,", line):
            cells = [c.strip() for c in line.split(",")]
            month, firms = _date(cells[0]), int(cells[1])
            for i, value in enumerate(cells[2:22], start=1):
                out.append((month, firms, 5 * i, float(value)))
    return out
