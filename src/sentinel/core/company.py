"""Steps 8–9: company profiles, filing histories and XBRL facts from the SEC bulk archives
(feature 004, research R9; data-model.md "Company data").

`core.issuer` holds **current** values (name, SIC, exchanges, tickers): they serve the D45 fallback
and reporting, never as information at T. `core.company_filing` holds every filing listed for an
issuer, including those filed about it (25-NSE, SC 14D9, 425, …), except insider forms.
"""

import contextlib
import zipfile
from datetime import date

import duckdb
import pyarrow as pa

from sentinel.config import Paths
from sentinel.ingest import sec_company
from sentinel.warehouse import MissingInput

INSIDER_FORMS = {"3", "4", "5", "144", "3/A", "4/A", "5/A", "144/A"}
CHUNK = 500  # issuers per transaction
ISSUER_SCHEMA = [
    ("issuer_cik", pa.string()), ("name", pa.string()), ("sic", pa.string()),
    ("sic_label", pa.string()), ("exchanges", pa.list_(pa.string())),
    ("tickers", pa.list_(pa.string())), ("raw_path", pa.string()),
]  # fmt: skip
FILING_SCHEMA = [
    ("issuer_cik", pa.string()), ("accession", pa.string()), ("form", pa.string()),
    ("filing_date", pa.date32()), ("report_date", pa.date32()), ("items", pa.string()),
]  # fmt: skip


@contextlib.contextmanager
def _transaction(con: duckdb.DuckDBPyConnection):
    con.execute("begin transaction")
    try:
        yield
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def universe(con: duckdb.DuckDBPyConnection, params: dict, issuers=None) -> list[str]:
    """Issuers with a preliminary event from `rules.final_detection_start`."""
    rows = con.execute(
        "select distinct issuer_cik from evt.prelim_event where signal_date >= cast(? as DATE)",
        [str(params["rules"]["final_detection_start"])],
    ).fetchall()
    return sorted((r[0] for r in rows if issuers is None or r[0] in issuers), key=int)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _arrow(rows: list[tuple], schema) -> pa.Table:
    columns = list(zip(*rows, strict=True)) if rows else [[] for _ in schema]
    return pa.table({n: pa.array(c, t) for (n, t), c in zip(schema, columns, strict=True)})


def _open(paths: Paths, name: str) -> zipfile.ZipFile:
    path = sec_company.archive_path(paths, name)
    if not path.exists():
        raise MissingInput(f"run `sentinel fetch-company` first: missing {path.name}")
    return zipfile.ZipFile(path)


def build_profiles(con, paths: Paths, params: dict, issuers=None) -> tuple[int, int]:
    """`core.issuer` and `core.company_filing` for the universe; returns (issuers, filings)."""
    ciks = universe(con, params, issuers)
    raw_path = sec_company.archive_path(paths, "submissions").relative_to(paths.data_raw).as_posix()
    con.execute(
        "create or replace table core._new_issuer (issuer_cik VARCHAR, name VARCHAR, sic VARCHAR, "
        "sic_label VARCHAR, exchanges VARCHAR[], tickers VARCHAR[], raw_path VARCHAR)"
    )
    con.execute(
        "create or replace table core._new_company_filing (issuer_cik VARCHAR, accession VARCHAR, "
        "form VARCHAR, filing_date DATE, report_date DATE, items VARCHAR)"
    )
    with _open(paths, "submissions") as zf:
        issuers_rows, filing_rows = [], []

        def flush():
            with _transaction(con):
                for table, rows, schema in (
                    ("core._new_issuer", issuers_rows, ISSUER_SCHEMA),
                    ("core._new_company_filing", filing_rows, FILING_SCHEMA),
                ):
                    con.register("_chunk", _arrow(rows, schema))
                    try:
                        con.execute(f"insert into {table} select * from _chunk")
                    finally:
                        con.unregister("_chunk")
            issuers_rows.clear()
            filing_rows.clear()

        for i, (cik, doc, pages) in enumerate(sec_company.iter_submissions(zf, ciks), 1):
            issuers_rows.append((
                cik, doc.get("name"), (doc.get("sic") or None),
                (doc.get("sicDescription") or None), list(doc.get("exchanges") or []),
                list(doc.get("tickers") or []), raw_path,
            ))  # fmt: skip
            seen = set()
            for page in pages:
                cols = [page.get(k, []) for k in ("accessionNumber", "form", "filingDate",
                                                  "reportDate", "items")]  # fmt: skip
                for acc, form, filed, report, items in zip(*cols, strict=False):
                    if form in INSIDER_FORMS or acc in seen:
                        continue
                    seen.add(acc)
                    filing_rows.append((cik, acc, form, _date(filed), _date(report), items or None))
            if i % CHUNK == 0:
                flush()
        flush()
    with _transaction(con):
        for table in ("issuer", "company_filing"):
            con.execute(f"drop table if exists core.{table}")
            con.execute(f"alter table core._new_{table} rename to {table}")
    return (
        con.execute("select count(*) from core.issuer").fetchone()[0],
        con.execute("select count(*) from core.company_filing").fetchone()[0],
    )
