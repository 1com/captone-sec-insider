"""Layer 2: Form 3, 4 and 5 filings as they are filed (source `sec_ownership_filing`, stored at
`data/raw/sec/form4/<YYYY>/<accession>.txt.gz`) into schema `stg_sec_form4_daily` (research R3).

Each stored submission holds the SEC header (acceptance time, filing date) and the filer's
`ownershipDocument` XML, from which the SEC derives its quarterly data sets. Each table has exactly
the columns and types of `sec_form4.TABLE_SPECS`, then `quarter` (the filing day's quarter, e.g.
`2026q4`) and `src_row` (the row's number in the table), so `core` reads both sources through one
union (`union_sql`); then `filing_day` and `raw_file`, and on `submission` `accepted_at_et`. As in
the data sets, `rptowner_relationship` lists the owner's roles (`Director,Officer`), each `_fn`
column the footnote ids of its element (`F1, F2`), and `file_number` is the owner's `SEC FILE
NUMBER` in the header. Line keys (`*_sk`) are the line's number in its document.

A value that cannot be converted becomes null and goes to `parse_issue`, as does a document that
cannot be read (with no rows in the other tables). The manifest holds one file per accession.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date

import duckdb
import pyarrow as pa

from sentinel import db
from sentinel.config import Paths
from sentinel.raw import manifest
from sentinel.staging import sec_form4
from sentinel.staging.sec_form4 import TABLE_SPECS
from sentinel.staging.sec_headers import HeaderParseError, parse_header

SOURCE = "sec_ownership_filing"
SCHEMA = "stg_sec_form4_daily"
QUARTERLY = sec_form4.SCHEMA
ROLES = (("isDirector", "Director"), ("isOfficer", "Officer"),
         ("isTenPercentOwner", "TenPercentOwner"), ("isOther", "Other"))  # fmt: skip
# the lines of each line table, in the document
LINES = {
    "NONDERIV_TRANS": "nonDerivativeTable/nonDerivativeTransaction",
    "NONDERIV_HOLDING": "nonDerivativeTable/nonDerivativeHolding",
    "DERIV_TRANS": "derivativeTable/derivativeTransaction",
    "DERIV_HOLDING": "derivativeTable/derivativeHolding",
}
# a line column's element: its value in `value`, its footnotes in `footnoteId`
VALUES = {
    "SECURITY_TITLE": "securityTitle",
    "CONV_EXERCISE_PRICE": "conversionOrExercisePrice",
    "TRANS_DATE": "transactionDate",
    "DEEMED_EXECUTION_DATE": "deemedExecutionDate",
    "TRANS_TIMELINESS": "transactionTimeliness",
    "TRANS_SHARES": "transactionAmounts/transactionShares",
    "TRANS_TOTAL_VALUE": "transactionAmounts/transactionTotalValue",
    "TRANS_PRICEPERSHARE": "transactionAmounts/transactionPricePerShare",
    "TRANS_ACQUIRED_DISP_CD": "transactionAmounts/transactionAcquiredDisposedCode",
    "EXCERCISE_DATE": "exerciseDate",  # the data sets' spelling, transactions only
    "EXERCISE_DATE": "exerciseDate",
    "EXPIRATION_DATE": "expirationDate",
    "UNDLYNG_SEC_TITLE": "underlyingSecurity/underlyingSecurityTitle",
    "UNDLYNG_SEC_SHARES": "underlyingSecurity/underlyingSecurityShares",
    "UNDLYNG_SEC_VALUE": "underlyingSecurity/underlyingSecurityValue",
    "SHRS_OWND_FOLWNG_TRANS": "postTransactionAmounts/sharesOwnedFollowingTransaction",
    "VALU_OWND_FOLWNG_TRANS": "postTransactionAmounts/valueOwnedFollowingTransaction",
    "DIRECT_INDIRECT_OWNERSHIP": "ownershipNature/directOrIndirectOwnership",
    "NATURE_OF_OWNERSHIP": "ownershipNature/natureOfOwnership",
}
# line columns held as text in `transactionCoding`, whose footnotes are the coding's
CODING = {"TRANS_FORM_TYPE": "transactionFormType", "TRANS_CODE": "transactionCode",
          "EQUITY_SWAP_INVOLVED": "equitySwapInvolved"}  # fmt: skip
CODING_FN = frozenset({"EQUITY_SWAP_TRANS_CD_FN", "TRANS_FORM_TYPE_FN"})
SUBMISSION = {
    "PERIOD_OF_REPORT": "periodOfReport",
    "DATE_OF_ORIG_SUB": "dateOfOriginalSubmission",
    "NO_SECURITIES_OWNED": "noSecuritiesOwned",
    "NOT_SUBJECT_SEC16": "notSubjectToSection16",
    "FORM3_HOLDINGS_REPORTED": "form3HoldingsReported",
    "FORM4_TRANS_REPORTED": "form4TransactionsReported",
    "DOCUMENT_TYPE": "documentType",
    "ISSUERCIK": "issuer/issuerCik",
    "ISSUERNAME": "issuer/issuerName",
    "ISSUERTRADINGSYMBOL": "issuer/issuerTradingSymbol",
    "REMARKS": "remarks",
    "AFF10B5ONE": "aff10b5One",
}
OWNER = {
    "RPTOWNERCIK": "reportingOwnerId/rptOwnerCik",
    "RPTOWNERNAME": "reportingOwnerId/rptOwnerName",
    "RPTOWNER_TITLE": "reportingOwnerRelationship/officerTitle",
    "RPTOWNER_TXT": "reportingOwnerRelationship/otherText",
    "RPTOWNER_STREET1": "reportingOwnerAddress/rptOwnerStreet1",
    "RPTOWNER_STREET2": "reportingOwnerAddress/rptOwnerStreet2",
    "RPTOWNER_CITY": "reportingOwnerAddress/rptOwnerCity",
    "RPTOWNER_STATE": "reportingOwnerAddress/rptOwnerState",
    "RPTOWNER_ZIPCODE": "reportingOwnerAddress/rptOwnerZipCode",
    "RPTOWNER_STATE_DESC": "reportingOwnerAddress/rptOwnerStateDescription",
}
_ARROW = {"date": pa.date32(), "number": pa.float64(), "flag": pa.bool_()}
ISSUE_SCHEMA = pa.schema([
    ("accession_number", pa.string()), ("raw_file", pa.string()), ("table_name", pa.string()),
    ("column_name", pa.string()), ("raw_value", pa.string()), ("message", pa.string()),
])  # fmt: skip


class _Document:
    """One submission's rows per table (raw text) and the values that failed to convert."""

    def __init__(self, accession: str, raw_file: str):
        self.accession, self.raw_file = accession, raw_file
        self.header = None  # the SEC header, once read
        self.rows: dict[str, list[dict]] = {t: [] for t in TABLE_SPECS}
        self.issues: list[tuple] = []

    def issue(self, table: str | None, column: str | None, raw: str | None, message: str) -> None:
        self.issues.append((self.accession, self.raw_file, table and table.lower(),
                            column and column.lower(), raw, message))  # fmt: skip

    def add(self, table: str, raw: dict[str, str | None]) -> None:
        """A row of `table` from raw text values, each converted to its column's type."""
        spec = TABLE_SPECS[table]
        row = {}
        for column in spec.columns:
            text = raw.get(column)
            row[column] = _convert(spec.kind(column), text) if text is not None else None
            if text is not None and row[column] is None and spec.kind(column) != "cik":
                self.issue(table, column, text, f"not a {spec.kind(column)}")
        self.rows[table].append(row)


def _convert(kind: str, text: str):
    match kind:
        case "date":
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[Z+-].*)?", text)
            try:
                return date.fromisoformat(m[1]) if m else None
            except ValueError:
                return None
        case "number":
            try:
                return float(text)
            except ValueError:
                return None
        case "flag":
            return {"1": True, "true": True, "0": False, "false": False}.get(text.lower())
        case "cik":
            return text.lstrip("0") or None
        case _:
            return text


def _text(el: ET.Element | None) -> str | None:
    """An element's text with whitespace runs made single spaces; None when empty or absent."""
    if el is None:
        return None
    return " ".join("".join(el.itertext()).split()) or None


def _notes(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    return ", ".join(f.get("id", "") for f in el.findall("footnoteId")) or None


def _line(table: str, el: ET.Element, n: int) -> dict[str, str | None]:
    raw: dict[str, str | None] = {f"{table}_SK": str(n)}
    coding = el.find("transactionCoding")
    for column in TABLE_SPECS[table].columns:
        if column in VALUES:
            raw[column] = _text(el.find(f"{VALUES[column]}/value"))
            raw[f"{column}_FN"] = _notes(el.find(VALUES[column]))
        elif column in CODING:
            raw[column] = _text(coding.find(CODING[column])) if coding is not None else None
        elif column in CODING_FN:
            raw[column] = _notes(coding)
    return raw


def _file_numbers(header: str) -> dict[str, str]:
    """Each reporting owner's `SEC FILE NUMBER` in the header, by CIK without leading zeros."""
    out = {}
    for block in re.findall(r"(?ms)^REPORTING-OWNER:(.*?)(?=^\S|\Z)", header):
        cik = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", block)
        number = re.search(r"SEC FILE NUMBER:[ \t]*(\S+)", block)
        if cik and number:
            out[cik[1].lstrip("0")] = number[1]
    return out


def _xml(data: bytes) -> ET.Element:
    """The document as UTF-8 (the XML default), else as Latin-1 (older filings)."""
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return ET.fromstring(data.decode("latin-1"))


def parse(data: bytes, accession: str, raw_file: str) -> _Document:
    """One stored submission's rows; a document that cannot be read gives one issue, no rows."""
    doc = _Document(accession, raw_file)
    text = data.decode("latin-1")
    end = text.find("</SEC-HEADER>")
    start = data.find(b"<ownershipDocument")
    stop = data.find(b"</ownershipDocument>")
    try:
        header = parse_header(text[:end] if end >= 0 else text, expect_accession=accession)
        if start < 0 or stop < 0:
            raise ValueError("no ownershipDocument")
        root = _xml(data[start : stop + len(b"</ownershipDocument>")])
    except (HeaderParseError, ValueError, ET.ParseError) as e:
        doc.issue(None, None, None, f"{type(e).__name__}: {e}")
        return doc
    doc.header = header
    doc.add("SUBMISSION", {
        "ACCESSION_NUMBER": accession, "FILING_DATE": header.filed_as_of.isoformat(),
        **{c: _text(root.find(path)) for c, path in SUBMISSION.items()}})  # fmt: skip
    numbers = _file_numbers(text[:end] if end >= 0 else "")
    for owner in root.findall("reportingOwner"):
        raw = {"ACCESSION_NUMBER": accession, **{c: _text(owner.find(p)) for c, p in OWNER.items()}}
        roles = []
        for element, role in ROLES:
            flag = _text(owner.find(f"reportingOwnerRelationship/{element}"))
            if flag is not None and _convert("flag", flag) is None:
                doc.issue("REPORTINGOWNER", "RPTOWNER_RELATIONSHIP", f"{element}={flag}",
                          "not a flag")  # fmt: skip
            elif flag is not None and _convert("flag", flag):
                roles.append(role)
        raw["RPTOWNER_RELATIONSHIP"] = ",".join(roles) or None
        cik = (raw["RPTOWNERCIK"] or "").lstrip("0")
        raw["FILE_NUMBER"] = numbers.get(cik) or next(iter(numbers.values()), None)
        doc.add("REPORTINGOWNER", raw)
    for table, path in LINES.items():
        for n, el in enumerate(root.findall(path), start=1):
            doc.add(table, {"ACCESSION_NUMBER": accession, **_line(table, el, n)})
    for note in root.findall("footnotes/footnote"):
        doc.add("FOOTNOTES", {"ACCESSION_NUMBER": accession, "FOOTNOTE_ID": note.get("id"),
                              "FOOTNOTE_TXT": _text(note)})  # fmt: skip
    for sig in root.findall("ownerSignature"):
        doc.add("OWNER_SIGNATURE", {
            "ACCESSION_NUMBER": accession, "OWNERSIGNATURENAME": _text(sig.find("signatureName")),
            "OWNERSIGNATUREDATE": _text(sig.find("signatureDate"))})  # fmt: skip
    return doc


def _schema(table: str) -> pa.Schema:
    spec = TABLE_SPECS[table]
    fields = [(c.lower(), _ARROW.get(spec.kind(c), pa.string())) for c in spec.columns]
    fields += [("quarter", pa.string()), ("src_row", pa.int64()), ("filing_day", pa.date32()),
               ("raw_file", pa.string())]  # fmt: skip
    if table == "SUBMISSION":
        fields.append(("accepted_at_et", pa.timestamp("s")))
    return pa.schema(fields)


def stored_files(p: Paths) -> list[manifest.ManifestEntry]:
    """Every stored submission, by accession."""
    entries = manifest.read_all(p.manifest)
    return sorted(
        (e for e in entries if e.source == SOURCE and e.role == "original"), key=lambda e: e.key
    )


def stage(con: duckdb.DuckDBPyConnection, p: Paths, echo: Callable[[str], None] = print) -> dict:
    """Recreate every `stg_sec_form4_daily` table from the stored submissions."""
    docs = [parse(manifest.read_stored(p, e), e.key, e.path) for e in stored_files(p)]
    read = [d for d in docs if d.header is not None]
    read.sort(key=lambda d: (d.header.filed_as_of, d.accession))
    tables = {}
    for table in TABLE_SPECS:
        rows = [(d, r) for d in read for r in d.rows[table]]
        columns = {c.lower(): [r[c] for _, r in rows] for c in TABLE_SPECS[table].columns}
        days = [d.header.filed_as_of for d, _ in rows]
        columns["quarter"] = [f"{x.year}q{(x.month - 1) // 3 + 1}" for x in days]
        columns["src_row"] = list(range(1, len(rows) + 1))
        columns["filing_day"] = days
        columns["raw_file"] = [d.raw_file for d, _ in rows]
        if table == "SUBMISSION":
            columns["accepted_at_et"] = [d.header.accepted_at_et for d, _ in rows]
        tables[table.lower()] = pa.table(columns, schema=_schema(table))
    issues = [i for d in docs for i in d.issues]
    tables["parse_issue"] = pa.Table.from_pylist(
        [dict(zip(ISSUE_SCHEMA.names, i, strict=True)) for i in issues], schema=ISSUE_SCHEMA
    )
    with db.transaction(con):
        for name, data in tables.items():
            con.register("_t", data)
            try:
                con.execute(f"create or replace table {SCHEMA}.{name} as select * from _t")
            finally:
                con.unregister("_t")
    echo(f"  form 4 filings: {len(read):,} read, {len(issues):,} parse issues")
    return {"documents": len(read), "lines": sum(len(tables[t]) for t in ("nonderiv_trans",
            "deriv_trans")), "parse_issues": len(issues)}  # fmt: skip


def has_daily(con: duckdb.DuckDBPyConnection, table: str = "submission") -> bool:
    return con.execute("select count(*) from duckdb_tables() where schema_name = ? "
                       "and table_name = ?", [SCHEMA, table]).fetchone()[0] > 0  # fmt: skip


def union_sql(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """Form 4 table `table` as the layers above read it: the quarterly data sets' rows, then the
    daily rows of accessions no data set holds. The quarterly table alone without daily tables."""
    quarterly = f"{QUARTERLY}.{table}"
    if not has_daily(con, table):
        return quarterly
    cols = ", ".join([*(c.lower() for c in TABLE_SPECS[table.upper()].columns), "quarter",
                      "src_row"])  # fmt: skip
    return (
        f"(select {cols} from {quarterly} union all select {cols} from {SCHEMA}.{table} d "
        f"where not exists (select 1 from {QUARTERLY}.submission q "
        "where q.accession_number = d.accession_number))"
    )
