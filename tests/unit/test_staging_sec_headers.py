"""Layer 2: filing headers and the SEC's daily ticker lists (v1's parser tests, plus staging)."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from sentinel import db
from sentinel.raw.manifest import Manifest, ManifestEntry, sha256_file
from sentinel.staging import sec_headers

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "edgar_header_form4.txt").read_text()
ACC = "0001225208-19-010527"
SGML = FIXTURE[FIXTURE.index("<SEC-HEADER>") : FIXTURE.index("-->")]  # the bare .hdr.sgml


def without_sic(text):
    return "\n".join(
        x for x in text.split("\n") if "ASSIGNED-SIC" not in x and "INDUSTRIAL CLASS" not in x
    )


def test_parse_header():
    h = sec_headers.parse_header(FIXTURE)
    assert (h.sic, h.sic_label) == ("2810", "INDUSTRIAL INORGANIC CHEMICALS")
    assert h.accepted_at_et == datetime(2019, 7, 26, 11, 48, 41)
    assert (h.form_type, h.filed_as_of, h.issuer_cik) == ("4", date(2019, 7, 26), "2969")


def test_a_header_without_sic_parses_with_sic_null():
    h = sec_headers.parse_header(without_sic(FIXTURE))
    assert (h.sic, h.sic_label) == (None, None)
    assert h.accepted_at_et == datetime(2019, 7, 26, 11, 48, 41)


def test_a_bare_sgml_header_parses_without_the_industry_name():
    h = sec_headers.parse_header(SGML, expect_accession=ACC)
    assert (h.sic, h.sic_label, h.issuer_cik) == ("2810", None, "2969")
    assert h.accepted_at_et == datetime(2019, 7, 26, 11, 48, 41)


def test_a_page_that_is_not_a_header_is_a_parse_error():
    with pytest.raises(sec_headers.HeaderParseError):
        sec_headers.parse_header("<html><body>Not found</body></html>")


def test_a_header_for_another_filing_is_a_parse_error():
    with pytest.raises(sec_headers.HeaderParseError, match="accession"):
        sec_headers.parse_header(FIXTURE, expect_accession="0000000000-00-000000")


def _record(paths, rel: str, key: str, source: str = sec_headers.HEADER_SOURCE) -> None:
    file = paths.raw / rel
    Manifest(paths.manifest).add(ManifestEntry(
        path=rel, source=source, key=key, role="original", url="https://example.test",
        fetched_at="2026-10-29T00:00:00Z", bytes=file.stat().st_size, sha256=sha256_file(file),
        http_last_modified=None, http_etag=None, tool="test"))  # fmt: skip


def test_stage_headers_parses_stored_files_and_lists_failures(tmp_data):
    good = tmp_data.raw / "sec/headers/2019" / f"{ACC}.txt"
    bad = tmp_data.raw / "sec/headers/2019" / "0000000001-19-000001.txt"
    good.parent.mkdir(parents=True)
    good.write_text(FIXTURE)
    bad.write_text("<html>Not found</html>")
    _record(tmp_data, f"sec/headers/2019/{ACC}.txt", ACC)
    _record(tmp_data, "sec/headers/2019/0000000001-19-000001.txt", "0000000001-19-000001")
    con = db.connect(tmp_data)
    assert sec_headers.stage_headers(con, tmp_data, echo=lambda s: None) == {
        "header": 1, "parse_failure": 1}  # fmt: skip
    row = con.execute(
        "select issuer_cik, sic, accepted_at_et from stg_sec_headers.header"
    ).fetchone()
    assert row == ("2969", "2810", datetime(2019, 7, 26, 11, 48, 41))


def test_stage_tickers_keeps_every_snapshot_in_the_secs_order(tmp_data):
    tmp_data.sec_reference.mkdir(parents=True)
    for day, rows in (("20261022", [[320193, "Apple Inc.", "AAPL", "Nasdaq"]]),
                      ("20261023", [[1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
                                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                                    [320193, "Apple Inc.", "", None]])):  # fmt: skip
        doc = {"fields": ["cik", "name", "ticker", "exchange"], "data": rows}
        (tmp_data.sec_reference / f"company_tickers_exchange_{day}.json").write_text(
            json.dumps(doc)
        )
    con = db.connect(tmp_data)
    assert sec_headers.stage_tickers(con, tmp_data, echo=lambda s: None) == {"snapshot": 3}
    got = con.execute(
        "select snapshot_date, cik, ticker, rank from stg_sec_tickers.snapshot order by 1, 4"
    ).fetchall()
    assert got == [(date(2026, 10, 22), "320193", "AAPL", 0), (date(2026, 10, 23), "1045810",
                    "NVDA", 0), (date(2026, 10, 23), "320193", "AAPL", 1)]  # fmt: skip
