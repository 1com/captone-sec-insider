"""Steps 8–9: company profiles, filing histories and XBRL facts from the SEC bulk archives
(feature 004, research R9; data-model.md "Company data").

`core.issuer` holds **current** values (name, SIC, exchanges, tickers): they serve the D45 fallback
and reporting, never as information at T. `core.company_filing` holds every filing listed for an
issuer, including those filed about it (25-NSE, SC 14D9, 425, …), except insider forms.
"""

import contextlib
import zipfile
from dataclasses import dataclass, field
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


# --- Step 9: first-filed XBRL facts (plan §7.2; research R9) -----------------------------------

# concept → (taxonomy, tag, unit) in order: the main tag, then its one fallback.
CONCEPTS = {
    "shares_outstanding": [("dei", "EntityCommonStockSharesOutstanding", "shares")],
    "equity": [
        ("us-gaap", "StockholdersEquity", "USD"),
        (
            "us-gaap",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "USD",
        ),
    ],
    "assets": [("us-gaap", "Assets", "USD")],
    "liabilities": [("us-gaap", "Liabilities", "USD")],  # else assets − equity, at use
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD"),
    ],
    "net_income": [("us-gaap", "NetIncomeLoss", "USD"), ("us-gaap", "ProfitLoss", "USD")],
}
FACT_COLUMNS = (
    "issuer_cik VARCHAR, concept VARCHAR, unit VARCHAR, period_start DATE, period_end DATE, "
    "value DOUBLE, filed DATE, accession VARCHAR, form VARCHAR, fp VARCHAR, tag_used VARCHAR"
)
FACT_SCHEMA = [
    ("issuer_cik", pa.string()), ("concept", pa.string()), ("unit", pa.string()),
    ("period_start", pa.date32()), ("period_end", pa.date32()), ("value", pa.float64()),
    ("filed", pa.date32()), ("accession", pa.string()), ("form", pa.string()),
    ("fp", pa.string()), ("tag_used", pa.string()),
]  # fmt: skip


@dataclass
class FactsReport:
    issuers: int = 0
    with_facts: int = 0
    rows: int = 0
    concepts: dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        per = ", ".join(f"{k} {v:,}" for k, v in self.concepts.items())
        return (
            f"{self.rows:,} first-filed values for {self.with_facts:,} of {self.issuers:,} "
            f"issuers ({per})"
        )


def first_filed(doc: dict, cik: str, cutoff=None) -> list[tuple]:
    """One row per concept and period: the value as first filed (earliest `filed`, then smallest
    accession). A fallback tag fills only periods the main tag lacks. `cutoff` drops facts filed
    after it (truncation tests)."""
    facts = doc.get("facts", {}) if doc else {}
    rows = []
    for concept, tags in CONCEPTS.items():
        chosen: dict[tuple, tuple] = {}
        for rank, (taxonomy, tag, unit) in enumerate(tags):
            label = f"{'main' if rank == 0 else 'fallback'}:{tag}"
            best: dict[tuple, tuple] = {}
            for f in facts.get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, []):
                filed, end = _date(f.get("filed")), _date(f.get("end"))
                if filed is None or end is None or f.get("val") is None:
                    continue
                if cutoff is not None and filed > cutoff:
                    continue
                period = (_date(f.get("start")), end)
                key = (filed, f.get("accn") or "")
                if period not in best or key < best[period][0]:
                    best[period] = (key, f, label, unit)
            for period, value in best.items():
                chosen.setdefault(period, value)  # the main tag wins its periods
        for (start, end), ((filed, accn), f, label, unit) in sorted(
            chosen.items(), key=lambda kv: (kv[0][1], kv[0][0] or date.min)
        ):
            rows.append((cik, concept, unit, start, end, float(f["val"]), filed, accn or None,
                         f.get("form"), f.get("fp"), label))  # fmt: skip
    return rows


def build_facts(con, paths: Paths, params: dict, issuers=None, cutoff=None) -> FactsReport:
    """`core.xbrl_fact` for the universe, read one company at a time."""
    ciks = universe(con, params, issuers)
    report = FactsReport(issuers=len(ciks))
    con.execute(f"create or replace table core._new_xbrl_fact ({FACT_COLUMNS})")
    with _open(paths, "companyfacts") as zf:
        rows: list[tuple] = []

        def flush():
            with _transaction(con):
                con.register("_chunk", _arrow(rows, FACT_SCHEMA))
                try:
                    con.execute("insert into core._new_xbrl_fact select * from _chunk")
                finally:
                    con.unregister("_chunk")
            rows.clear()

        for i, cik in enumerate(ciks, 1):
            found = first_filed(sec_company.read_companyfacts(zf, cik), cik, cutoff)
            report.with_facts += bool(found)
            report.rows += len(found)
            for r in found:
                report.concepts[r[1]] = report.concepts.get(r[1], 0) + 1
            rows += found
            if i % CHUNK == 0:
                flush()
        flush()
    with _transaction(con):
        con.execute("drop table if exists core.xbrl_fact")
        con.execute("alter table core._new_xbrl_fact rename to xbrl_fact")
    return report


def check_first_filed(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W22 (part): one row per fact key."""
    return [
        f"{r[0]} {r[1]} {r[3]}"
        for r in con.execute(
            "select issuer_cik, concept, unit, period_end, count(*) from core.xbrl_fact "
            "group by issuer_cik, concept, unit, period_start, period_end having count(*) > 1 "
            "order by 1, 2, 4 limit 10"
        ).fetchall()
    ]
