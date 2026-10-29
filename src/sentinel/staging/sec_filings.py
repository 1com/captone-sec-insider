"""Layer 2: the SEC's filer and filing records into schema `stg_sec_filings`.

- `filer`: one row per filer number (CIK), people included: names (current and former with
  dates), entity type, SIC, filer category, fiscal year end, state of incorporation, today's
  tickers and exchanges, whether insider filings exist for it as an owner or an issuer, and
  whether it looks like a company (`is_company`, below).
- `filing`: every filing of every company-like filer: accession, form, filing and report dates,
  8-K items, file number, primary document, and `origin`: `bulk` from a submissions document,
  `daily` from a day's index.

Sources (specs/001-daily-data-refresh, research R4): the newest stored bulk `submissions.zip` is the
base (its `recent` blocks and older-filings pages); a per-company submissions document fetched for
a CIK the base lacks adds that filer; each stored daily index adds the filings of company-like
filers that the base does not hold. An index row has no report date or 8-K items: `core.filing`
takes them from the filing's header.

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
from sentinel.raw import manifest

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
    [("cik", pa.string())] + [(n, t) for n, t in FILING_COLS.values()]
    + [("origin", pa.string()), ("raw_file", pa.string())]
)  # fmt: skip
FLUSH_ROWS = 250_000  # filing rows held in memory at most: some filers have 100,000+ filings


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
        out["origin"] += ["bulk"] * n
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


def newest_bulk(p: Paths, name: str) -> manifest.ManifestEntry:
    """The newest stored bulk file `name` (`submissions` or `companyfacts`) by fetch time."""
    copies = [e for e in manifest.read_all(p.manifest)
              if e.source == "sec_company" and e.key.split("/")[0] == name]  # fmt: skip
    if not copies:
        raise FileNotFoundError(f"no {name}.zip stored: run `sentinel fetch sec-bulk`")
    return max(copies, key=lambda e: e.fetched_at)


def newest_per_cik(p: Paths, source: str) -> dict[str, manifest.ManifestEntry]:
    """The newest stored per-company document of `source` for each CIK (keys `<cik>/<date>`)."""
    out: dict[str, manifest.ManifestEntry] = {}
    for e in manifest.read_all(p.manifest):
        if e.source == source and e.role == "original":
            cik = e.key.split("/")[0]
            if cik not in out or e.fetched_at > out[cik].fetched_at:
                out[cik] = e
    return out


def _add_new_filers(con, p: Paths) -> int:
    """Filers from per-company submissions documents of CIKs the base lacks."""
    known = {c for (c,) in con.execute(f"select cik from {SCHEMA}._new_filer").fetchall()}
    added = 0
    for cik, entry in sorted(newest_per_cik(p, "sec_submissions_cik").items()):
        if cik in known:
            continue
        doc = json.loads(manifest.read_stored(p, entry))
        row, is_company = filer_row(doc, [], entry.path)
        filers = {k: [v] for k, v in row.items()}
        filings = (filing_rows(row["cik"], [(doc.get("filings", {}).get("recent", {}),
                                             entry.path)]) if is_company
                   else {n: [] for n in FILING_SCHEMA.names})  # fmt: skip
        with db.transaction(con):
            _flush(con, "filer", FILER_SCHEMA, filers)
            _flush(con, "filing", FILING_SCHEMA, filings)
        added += 1
    return added


def _add_index_rows(con, p: Paths) -> int:
    """The filings of company-like filers in each stored daily index that no submissions document
    holds (same CIK and accession)."""
    from sentinel.raw.sec import parse_index

    rows = []
    for e in manifest.read_all(p.manifest):
        if e.source == "sec_index" and e.role == "original":
            text = manifest.read_stored(p, e).decode("latin-1")
            rows += [(r.cik, r.accession, r.filed, r.form, e.path) for r in parse_index(text)]
    if not rows:
        return 0
    cik, acc, filed, form, raw = zip(*rows, strict=True)
    con.register("_index", pa.table({
        "cik": pa.array(cik, pa.string()), "accession": pa.array(acc, pa.string()),
        "filing_date": pa.array(filed, pa.date32()), "form": pa.array(form, pa.string()),
        "raw_file": pa.array(raw, pa.string())}))  # fmt: skip
    try:
        with db.transaction(con):
            before = db.count(con, f"{SCHEMA}._new_filing")
            con.execute(
                f"""
                insert into {SCHEMA}._new_filing (cik, accession, filing_date, form, origin,
                                                  raw_file)
                select distinct i.cik, i.accession, i.filing_date, i.form, 'daily', i.raw_file
                from _index i
                join {SCHEMA}._new_filer f on f.cik = i.cik and f.is_company
                where not exists (select 1 from {SCHEMA}._new_filing x
                                  where x.cik = i.cik and x.accession = i.accession)
                qualify row_number() over (partition by i.cik, i.accession
                                           order by i.raw_file) = 1
                """
            )
            return db.count(con, f"{SCHEMA}._new_filing") - before
    finally:
        con.unregister("_index")


def stage(con: duckdb.DuckDBPyConnection, p: Paths, echo: Callable[[str], None] = print) -> dict:
    base = newest_bulk(p, "submissions")
    path, rel = p.raw / base.path, base.path
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
            if (
                len(filings["cik"]) >= FLUSH_ROWS
                or len(filers["cik"]) >= FLUSH_ROWS
                or i == len(mains)
            ):
                with db.transaction(con):
                    _flush(con, "filer", FILER_SCHEMA, filers)
                    _flush(con, "filing", FILING_SCHEMA, filings)
                filers = {n: [] for n in FILER_SCHEMA.names}
                filings = {n: [] for n in FILING_SCHEMA.names}
            if i % 100_000 == 0 or i == len(mains):
                echo(f"  submissions: {i:,}/{len(mains):,} filers read")
    new_filers = _add_new_filers(con, p)
    daily = _add_index_rows(con, p)
    echo(f"  daily: {new_filers:,} new filers, {daily:,} filings from the daily indexes")
    with db.transaction(con):
        for table in ("filer", "filing"):
            con.execute(f"drop table if exists {SCHEMA}.{table}")
            con.execute(f"alter table {SCHEMA}._new_{table} rename to {table}")
    return {"filer": db.count(con, f"{SCHEMA}.filer"), "filing": db.count(con, f"{SCHEMA}.filing"),
            "new_filers": new_filers, "daily_filings": daily}  # fmt: skip
