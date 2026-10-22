import io
import socket
import zipfile
from pathlib import Path

import pytest

from sentinel.config import Paths, load_params, repo_root

REPO = repo_root(Path(__file__).parent)

# Real column headers of the SEC Form 3/4/5 data sets (research.md R2).
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
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="needs --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Tests run offline (FR-007) unless marked `network`."""
    if "network" in request.keywords:
        return

    def blocked(*args, **kwargs):
        raise RuntimeError("network blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def params():
    return load_params(REPO / "config" / "params.yaml")


@pytest.fixture
def fake_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text('SEC_USER_AGENT="Test User test@example.com"\nTIINGO_API=tiingo-secret-123\n')
    return env


@pytest.fixture
def tmp_data(tmp_path) -> Paths:
    return Paths.from_root(tmp_path)


@pytest.fixture
def quarter_zip():
    return build_quarter_zip
