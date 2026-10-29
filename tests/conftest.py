import io
import socket
import zipfile
from pathlib import Path

import pytest

from sentinel.config import Paths, repo_root, sources

REPO = repo_root(Path(__file__).parent)

# Real column headers of the SEC Form 3/4/5 data sets.
HEADERS = {
    "SUBMISSION": [
        "ACCESSION_NUMBER",
        "FILING_DATE",
        "PERIOD_OF_REPORT",
        "DATE_OF_ORIG_SUB",
        "NO_SECURITIES_OWNED",
        "NOT_SUBJECT_SEC16",
        "FORM3_HOLDINGS_REPORTED",
        "FORM4_TRANS_REPORTED",
        "DOCUMENT_TYPE",
        "ISSUERCIK",
        "ISSUERNAME",
        "ISSUERTRADINGSYMBOL",
        "REMARKS",
    ],
    "REPORTINGOWNER": [
        "ACCESSION_NUMBER",
        "RPTOWNERCIK",
        "RPTOWNERNAME",
        "RPTOWNER_RELATIONSHIP",
        "RPTOWNER_TITLE",
        "RPTOWNER_TXT",
        "RPTOWNER_STREET1",
        "RPTOWNER_STREET2",
        "RPTOWNER_CITY",
        "RPTOWNER_STATE",
        "RPTOWNER_ZIPCODE",
        "RPTOWNER_STATE_DESC",
        "FILE_NUMBER",
    ],
    "NONDERIV_TRANS": [
        "ACCESSION_NUMBER",
        "NONDERIV_TRANS_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "TRANS_DATE",
        "TRANS_DATE_FN",
        "DEEMED_EXECUTION_DATE",
        "DEEMED_EXECUTION_DATE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_CODE",
        "EQUITY_SWAP_INVOLVED",
        "EQUITY_SWAP_TRANS_CD_FN",
        "TRANS_TIMELINESS",
        "TRANS_TIMELINESS_FN",
        "TRANS_SHARES",
        "TRANS_SHARES_FN",
        "TRANS_PRICEPERSHARE",
        "TRANS_PRICEPERSHARE_FN",
        "TRANS_ACQUIRED_DISP_CD",
        "TRANS_ACQUIRED_DISP_CD_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "FOOTNOTES": ["ACCESSION_NUMBER", "FOOTNOTE_ID", "FOOTNOTE_TXT"],
    "NONDERIV_HOLDING": [
        "ACCESSION_NUMBER",
        "NONDERIV_HOLDING_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_FORM_TYPE_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "DERIV_TRANS": [
        "ACCESSION_NUMBER",
        "DERIV_TRANS_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "CONV_EXERCISE_PRICE",
        "CONV_EXERCISE_PRICE_FN",
        "TRANS_DATE",
        "TRANS_DATE_FN",
        "DEEMED_EXECUTION_DATE",
        "DEEMED_EXECUTION_DATE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_CODE",
        "EQUITY_SWAP_INVOLVED",
        "EQUITY_SWAP_TRANS_CD_FN",
        "TRANS_TIMELINESS",
        "TRANS_TIMELINESS_FN",
        "TRANS_SHARES",
        "TRANS_SHARES_FN",
        "TRANS_TOTAL_VALUE",
        "TRANS_TOTAL_VALUE_FN",
        "TRANS_PRICEPERSHARE",
        "TRANS_PRICEPERSHARE_FN",
        "TRANS_ACQUIRED_DISP_CD",
        "TRANS_ACQUIRED_DISP_CD_FN",
        "EXCERCISE_DATE",
        "EXCERCISE_DATE_FN",
        "EXPIRATION_DATE",
        "EXPIRATION_DATE_FN",
        "UNDLYNG_SEC_TITLE",
        "UNDLYNG_SEC_TITLE_FN",
        "UNDLYNG_SEC_SHARES",
        "UNDLYNG_SEC_SHARES_FN",
        "UNDLYNG_SEC_VALUE",
        "UNDLYNG_SEC_VALUE_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "DERIV_HOLDING": [
        "ACCESSION_NUMBER",
        "DERIV_HOLDING_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "CONV_EXERCISE_PRICE",
        "CONV_EXERCISE_PRICE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_FORM_TYPE_FN",
        "EXERCISE_DATE",
        "EXERCISE_DATE_FN",
        "EXPIRATION_DATE",
        "EXPIRATION_DATE_FN",
        "UNDLYNG_SEC_TITLE",
        "UNDLYNG_SEC_TITLE_FN",
        "UNDLYNG_SEC_SHARES",
        "UNDLYNG_SEC_SHARES_FN",
        "UNDLYNG_SEC_VALUE",
        "UNDLYNG_SEC_VALUE_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "OWNER_SIGNATURE": ["ACCESSION_NUMBER", "OWNERSIGNATURENAME", "OWNERSIGNATUREDATE"],
}


def build_quarter_zip(
    tables: dict[str, list[dict]] | None = None, omit=(), checkbox=False
) -> bytes:
    """A synthetic quarterly archive with the real headers. Rows are dicts; missing cells are blank.

    `checkbox=True` adds the 2023-onward AFF10B5ONE column to SUBMISSION.
    """
    tables = tables or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, header in HEADERS.items():
            if name in omit:
                continue
            cols = header + (["AFF10B5ONE"] if checkbox and name == "SUBMISSION" else [])
            lines = ["\t".join(cols)]
            for row in tables.get(name, []):
                lines.append("\t".join(str(row.get(c, "")) for c in cols))
            zf.writestr(f"{name}.tsv", "\n".join(lines) + "\n")
    return buf.getvalue()


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", help="run tests marked 'network'")


def pytest_collection_modifyitems(config, items):
    if not Paths.from_root(REPO).build_db.exists():
        skip_slow = pytest.mark.skip(reason="needs the real data/sentinel.duckdb")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="needs --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Tests run offline unless marked `network`."""
    if "network" in request.keywords:
        return

    def blocked(*args, **kwargs):
        raise RuntimeError("network blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def settings():
    return sources(Paths.from_root(REPO))


@pytest.fixture
def fake_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text('SEC_USER_AGENT="Test User test@example.com"\nTIINGO_API=tiingo-secret-123\n')
    return env


@pytest.fixture
def tmp_data(tmp_path) -> Paths:
    """A project root in a temporary folder, with copies of the real settings files."""
    (tmp_path / "config").mkdir()
    for name in ("sources.yaml", "risk_params.yaml", "tracker.yaml"):
        (tmp_path / "config" / name).write_bytes((REPO / "config" / name).read_bytes())
    return Paths.from_root(tmp_path)


@pytest.fixture
def quarter_zip():
    return build_quarter_zip


# --- Synthetic Form 4 archives ---------------------------------------------------------------


def sub(acc, date="15-MAR-2019", doc="4", cik="100", symbol="ABC", aff="", name="Abc Corp"):
    return {
        "ACCESSION_NUMBER": acc,
        "FILING_DATE": date,
        "DOCUMENT_TYPE": doc,
        "ISSUERCIK": cik,
        "ISSUERNAME": name,
        "ISSUERTRADINGSYMBOL": symbol,
        "AFF10B5ONE": aff,
    }


def owner(acc, ocik="9001", rel="Director", title="", name=None):
    return {
        "ACCESSION_NUMBER": acc,
        "RPTOWNERCIK": ocik,
        "RPTOWNERNAME": name or f"Owner {ocik}",
        "RPTOWNER_RELATIONSHIP": rel,
        "RPTOWNER_TITLE": title,
    }


def line(
    acc,
    sk,
    title="Common Stock",
    code="P",
    ad="A",
    tdate="13-MAR-2019",
    shares="1000",
    price="50",  # with 1,000 shares, $50,000: above the G6 minimum
    after="",
    di="D",
    nature="",
    **fn,
):
    row = {
        "ACCESSION_NUMBER": acc,
        "NONDERIV_TRANS_SK": sk,
        "SECURITY_TITLE": title,
        "TRANS_DATE": tdate,
        "TRANS_CODE": code,
        "TRANS_SHARES": shares,
        "TRANS_PRICEPERSHARE": price,
        "TRANS_ACQUIRED_DISP_CD": ad,
        "SHRS_OWND_FOLWNG_TRANS": after,
        "DIRECT_INDIRECT_OWNERSHIP": di,
        "NATURE_OF_OWNERSHIP": nature,
    }
    row.update(fn)
    return row


def holding(acc, sk, title="Common Stock", shares="500", di="I", nature="By Trust"):
    return {
        "ACCESSION_NUMBER": acc,
        "NONDERIV_HOLDING_SK": sk,
        "SECURITY_TITLE": title,
        "SHRS_OWND_FOLWNG_TRANS": shares,
        "DIRECT_INDIRECT_OWNERSHIP": di,
        "NATURE_OF_OWNERSHIP": nature,
    }


def note(acc, fid, txt):
    return {"ACCESSION_NUMBER": acc, "FOOTNOTE_ID": fid, "FOOTNOTE_TXT": txt}


@pytest.fixture
def archives(tmp_data):
    """make({quarter: {TABLE: [rows]}}) writes one zip per quarter and records it as an original."""
    from sentinel.raw.manifest import Manifest, ManifestEntry, sha256_file
    from sentinel.staging.sec_form4 import SOURCE

    def make(quarters: dict[str, dict[str, list[dict]]], checkbox_from: str = "2023q1"):
        tmp_data.sec_insider.mkdir(parents=True, exist_ok=True)
        manifest = Manifest(tmp_data.manifest)
        out = []
        for quarter, tables in sorted(quarters.items()):
            path = tmp_data.sec_insider / f"{quarter}_form345.zip"
            path.write_bytes(build_quarter_zip(tables, checkbox=quarter >= checkbox_from))
            manifest.add(
                ManifestEntry(
                    path=path.relative_to(tmp_data.raw).as_posix(),
                    source=SOURCE,
                    key=quarter,
                    role="original",
                    url=f"https://example.test/{quarter}_form345.zip",
                    fetched_at="2026-10-22T00:00:00Z",
                    bytes=path.stat().st_size,
                    sha256=sha256_file(path),
                    http_last_modified=None,
                    http_etag=None,
                    tool="sentinel test",
                )
            )
            out.append((quarter, path))
        return out

    return make
