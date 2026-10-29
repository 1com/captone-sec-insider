"""Layer 2: the SEC's filer and filing records (`data/raw/sec/company/submissions.zip`) into schema
`stg_sec_filings`.

- `filer`: one row per filer number (CIK) in the file, people included: names (current and former
  with dates), entity type, SIC, filer category, fiscal year end, state of incorporation, today's
  tickers and exchanges, whether insider filings exist for it as an owner or an issuer, and
  whether it looks like a company (`is_company`, below).
- `filing`: every filing of every company-like filer, from the `recent` block and the older-filings
  pages: accession, form, filing and report dates, 8-K items, file number, primary document.

A filer is company-like if it has an SIC code or a ticker, is a Form 4 issuer, is typed operating or
investment, or has filed any company form. The SEC types individuals and many foreign companies
alike as "other", so the type alone cannot separate them. Individuals' own ownership filings are
not staged here; the Form 4 data sets hold them.

`acceptance_raw` is EDGAR's `acceptanceDateTime` as given. It is not reliable as a time: checked
against filing headers, it is ahead of Eastern time by 5 hours for some filings and 8 for others.
Exact acceptance times come from the filing headers (`stg_sec_headers`).
"""

import json
import zipfile
from collections.abc import Callable

import duckdb
import pyarrow as pa

from sentinel import db
from sentinel.config import Paths

SCHEMA = "stg_sec_filings"
COMPANY_FORMS = {
    "10-K", "10-KT", "10-Q", "20-F", "40-F", "8-K", "6-K", "N-CSR", "N-CSRS", "NPORT-P", "N-CEN",
    "N-2", "S-1", "S-3", "S-4", "F-1", "F-3", "F-4", "424B1", "424B2", "424B3", "424B4", "424B5",
    "DEF 14A", "10-12B", "10-12G", "EFFECT",
}  # fmt: skip
FILING_COLS = {
    "accessionNumber": ("accession", pa.string()),
    "filingDate": ("filing_date", pa.date32()),
    "reportDate": ("report_date", pa.date32()),
    "acceptanceDateTime": ("acceptance_raw", pa.string()),
    "act": ("act", pa.string()),
    "form": ("form", pa.string()),
    "fileNumber": ("file_number", pa.string()),
    "items": ("items", pa.string()),
    "size": ("size", pa.int64()),
    "isXBRL": ("is_xbrl", pa.bool_()),
    "isInlineXBRL": ("is_inline_xbrl", pa.bool_()),
    "primaryDocument": ("primary_document", pa.string()),
    "primaryDocDescription": ("primary_doc_description", pa.string()),
}
FILER_SCHEMA = pa.schema([
    ("cik", pa.string()), ("name", pa.string()),
    ("former_names", pa.list_(pa.struct([("name", pa.string()), ("valid_from", pa.string()),
                                         ("valid_to", pa.string())]))),
    ("entity_type", pa.string()), ("sic", pa.string()), ("sic_description", pa.string()),
    ("category", pa.string()), ("fiscal_year_end", pa.string()),
    ("state_of_incorporation", pa.string()), ("tickers", pa.list_(pa.string())),
    ("exchanges", pa.list_(pa.string())), ("insider_as_owner", pa.bool_()),
    ("insider_as_issuer", pa.bool_()), ("is_company", pa.bool_()), ("n_filings", pa.int64()),
    ("raw_file", pa.string()),
])  # fmt: skip
FILING_SCHEMA = pa.schema(
    [("cik", pa.string())] + [(n, t) for n, t in FILING_COLS.values()] + [("raw_file", pa.string())]
)
BATCH = 20_000


def _text(v) -> str | None:
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


def _date(v) -> str | None:
    return v[:10] if isinstance(v, str) and len(v) >= 10 else None


def filer_row(doc: dict, pages: list[dict], raw_file: str) -> tuple[dict, bool]:
    """The `filer` row of one submissions document, and whether its filings are staged."""
    forms = [f for block in [doc.get("filings", {}).get("recent", {}), *pages]
             for f in block.get("form", [])]  # fmt: skip
    tickers = [t for t in doc.get("tickers") or [] if t]
    entity = _text(doc.get("entityType"))
    sic = _text(doc.get("sic"))
    is_company = bool(
        sic or tickers or doc.get("insiderTransactionForIssuerExists") == 1
        or entity in ("operating", "investment")
        or any(f.removesuffix("/A") in COMPANY_FORMS for f in forms)
    )  # fmt: skip
    return {
        "cik": str(int(doc["cik"])),
        "name": _text(doc.get("name")),
        "former_names": [
            {
                "name": n.get("name"),
                "valid_from": _date(n.get("from")),
                "valid_to": _date(n.get("to")),
            }
            for n in doc.get("formerNames") or []
            if n.get("name")
        ],  # fmt: skip
        "entity_type": entity,
        "sic": sic,
        "sic_description": _text(doc.get("sicDescription")),
        "category": _text(doc.get("category")),
        "fiscal_year_end": _text(doc.get("fiscalYearEnd")),
        "state_of_incorporation": _text(doc.get("stateOfIncorporation")),
        "tickers": tickers,
        "exchanges": [e for e in doc.get("exchanges") or [] if e],
        "insider_as_owner": doc.get("insiderTransactionForOwnerExists") == 1,
        "insider_as_issuer": doc.get("insiderTransactionForIssuerExists") == 1,
        "is_company": is_company,
        "n_filings": len(forms),
        "raw_file": raw_file,
    }, is_company


def filing_rows(cik: str, blocks: list[tuple[dict, str]]) -> dict[str, list]:
    """Column lists of the `filing` rows from (block, file) pairs: `recent` and each page."""
    out: dict[str, list] = {n: [] for n in FILING_SCHEMA.names}
    for block, raw_file in blocks:
        n = len(block.get("accessionNumber", []))
        out["cik"] += [cik] * n
        out["raw_file"] += [raw_file] * n
        for key, (name, typ) in FILING_COLS.items():
            values = block.get(key) or [None] * n
            if typ == pa.date32():
                values = [_date(v) for v in values]
            elif typ == pa.string():
                values = [_text(v) for v in values]
            elif typ == pa.bool_():
                values = [None if v in (None, "") else bool(v) for v in values]
            out[name] += list(values)
    return out


def _flush(con, table: str, schema: pa.Schema, columns: dict[str, list]) -> None:
    if not columns[schema.names[0]]:
        return
    arrays = []
    for f in schema:
        values = columns[f.name]
        if f.type == pa.date32():
            arrays.append(pa.array(values, pa.string()).cast(pa.date32()))
        else:
            arrays.append(pa.array(values, f.type))
    con.register("_batch", pa.Table.from_arrays(arrays, schema=schema))
    try:
        con.execute(f"insert into {SCHEMA}._new_{table} select * from _batch")
    finally:
        con.unregister("_batch")


def stage(con: duckdb.DuckDBPyConnection, p: Paths, echo: Callable[[str], None] = print) -> dict:
    path = p.sec_company / "submissions.zip"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: run `sentinel fetch company`")
    rel = path.relative_to(p.raw).as_posix()
    con.register("_filer_schema", pa.Table.from_pylist([], schema=FILER_SCHEMA))
    con.register("_filing_schema", pa.Table.from_pylist([], schema=FILING_SCHEMA))
    con.execute(f"create or replace table {SCHEMA}._new_filer as select * from _filer_schema")
    con.execute(f"create or replace table {SCHEMA}._new_filing as select * from _filing_schema")
    con.unregister("_filer_schema")
    con.unregister("_filing_schema")
    filers: dict[str, list] = {n: [] for n in FILER_SCHEMA.names}
    filings: dict[str, list] = {n: [] for n in FILING_SCHEMA.names}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        pages: dict[str, list[str]] = {}
        for n in names:
            if "-submissions-" in n:
                pages.setdefault(n.split("-submissions-")[0] + ".json", []).append(n)
        mains = sorted(n for n in names if n.startswith("CIK") and "-submissions-" not in n)
        for i, name in enumerate(mains, 1):
            doc = json.loads(z.read(name))
            extra = [(json.loads(z.read(pg)), f"{rel}!{pg}") for pg in sorted(pages.get(name, []))]
            row, is_company = filer_row(doc, [b for b, _ in extra], f"{rel}!{name}")
            for k, v in row.items():
                filers[k].append(v)
            if is_company:
                rows = filing_rows(row["cik"], [(doc.get("filings", {}).get("recent", {}),
                                                 f"{rel}!{name}"), *extra])  # fmt: skip
                for k, v in rows.items():
                    filings[k] += v
            if i % BATCH == 0 or i == len(mains):
                with db.transaction(con):
                    _flush(con, "filer", FILER_SCHEMA, filers)
                    _flush(con, "filing", FILING_SCHEMA, filings)
                filers = {n: [] for n in FILER_SCHEMA.names}
                filings = {n: [] for n in FILING_SCHEMA.names}
                if i % 200_000 == 0 or i == len(mains):
                    echo(f"  submissions: {i:,}/{len(mains):,} filers read")
    with db.transaction(con):
        for table in ("filer", "filing"):
            con.execute(f"drop table if exists {SCHEMA}.{table}")
            con.execute(f"alter table {SCHEMA}._new_{table} rename to {table}")
    return {"filer": db.count(con, f"{SCHEMA}.filer"), "filing": db.count(con, f"{SCHEMA}.filing")}
