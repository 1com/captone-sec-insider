"""Layer 2: reported financial values (`data/raw/sec/company/companyfacts.zip`) into schema
`stg_sec_xbrl`.

`companyfacts.zip` is the SEC's own extraction of every XBRL value each company reported, one
JSON file per company. `fact` keeps **every version** (each filing that reported the value, with
its accession and filing date) of the tags in `ITEMS`, for every company; the full file holds
hundreds of millions of values the platform does not use. Which version counts at a given date is
decided in `core.financial_fact` (as first filed, with `known_at`).

`ITEMS` maps each financial item to its tags, main tag first; a later tag fills only the periods
the earlier ones lack (v1's rule).
"""

import json
import zipfile
from collections.abc import Callable

import duckdb
import pyarrow as pa

from sentinel import db
from sentinel.config import Paths

SCHEMA = "stg_sec_xbrl"
USD, SHARES = "USD", "shares"
ITEMS: dict[str, list[tuple[str, str, str]]] = {
    "shares_outstanding": [("dei", "EntityCommonStockSharesOutstanding", SHARES)],
    "shares_basic_avg": [("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", SHARES)],
    "diluted_shares": [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", SHARES)],
    "equity": [("us-gaap", "StockholdersEquity", USD),
               ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                USD)],
    "assets": [("us-gaap", "Assets", USD)],
    "liabilities": [("us-gaap", "Liabilities", USD)],
    "cash": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue", USD),
             ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", USD)],
    "net_income": [("us-gaap", "NetIncomeLoss", USD), ("us-gaap", "ProfitLoss", USD)],
    "revenue": [("us-gaap", "Revenues", USD),
                ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", USD),
                ("us-gaap", "SalesRevenueNet", USD)],
    "gross_profit": [("us-gaap", "GrossProfit", USD)],
    "operating_income": [("us-gaap", "OperatingIncomeLoss", USD)],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", USD),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", USD)],
    "capex": [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", USD)],
    "rd_expense": [("us-gaap", "ResearchAndDevelopmentExpense", USD)],
    "interest_expense": [("us-gaap", "InterestExpense", USD)],
    "long_term_debt": [("us-gaap", "LongTermDebtNoncurrent", USD),
                       ("us-gaap", "LongTermDebt", USD)],
    "current_assets": [("us-gaap", "AssetsCurrent", USD)],
    "current_liabilities": [("us-gaap", "LiabilitiesCurrent", USD)],
    "receivables": [("us-gaap", "AccountsReceivableNetCurrent", USD)],
    "stock_issue_proceeds": [("us-gaap", "ProceedsFromIssuanceOfCommonStock", USD)],
    "stock_compensation": [("us-gaap", "ShareBasedCompensation", USD)],
    "dividends_paid": [("us-gaap", "PaymentsOfDividends", USD)],
}  # fmt: skip
WANTED = {(tax, tag, unit) for tags in ITEMS.values() for tax, tag, unit in tags}
FACT_SCHEMA = pa.schema([
    ("cik", pa.string()), ("taxonomy", pa.string()), ("tag", pa.string()), ("unit", pa.string()),
    ("period_start", pa.date32()), ("period_end", pa.date32()), ("value", pa.float64()),
    ("accession", pa.string()), ("fy", pa.int32()), ("fp", pa.string()), ("form", pa.string()),
    ("filed", pa.date32()), ("frame", pa.string()), ("raw_file", pa.string()),
])  # fmt: skip
BATCH_ROWS = 500_000


def facts(doc: dict, raw_file: str) -> list[tuple]:
    """Every wanted value in one company's document, as `FACT_SCHEMA` rows."""
    cik = str(int(doc["cik"]))
    rows = []
    for taxonomy, tags in (doc.get("facts") or {}).items():
        for tag, body in tags.items():
            for unit, entries in (body.get("units") or {}).items():
                if (taxonomy, tag, unit) not in WANTED:
                    continue
                for f in entries:
                    if f.get("val") is None or not f.get("end") or not f.get("filed"):
                        continue
                    rows.append((cik, taxonomy, tag, unit, f.get("start"), f["end"],
                                 float(f["val"]), f.get("accn"), f.get("fy"), f.get("fp"),
                                 f.get("form"), f["filed"], f.get("frame"), raw_file))  # fmt: skip
    return rows


def _flush(con, rows: list[tuple]) -> None:
    if not rows:
        return
    cols = list(zip(*rows, strict=True))
    arrays = []
    for f, values in zip(FACT_SCHEMA, cols, strict=True):
        if f.type == pa.date32():
            arrays.append(pa.array(values, pa.string()).cast(pa.date32()))
        else:
            arrays.append(pa.array(values, f.type))
    con.register("_batch", pa.Table.from_arrays(arrays, schema=FACT_SCHEMA))
    try:
        with db.transaction(con):
            con.execute(f"insert into {SCHEMA}._new_fact select * from _batch")
    finally:
        con.unregister("_batch")


def stage(con: duckdb.DuckDBPyConnection, p: Paths, echo: Callable[[str], None] = print) -> dict:
    path = p.sec_company / "companyfacts.zip"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: run `sentinel fetch company`")
    rel = path.relative_to(p.raw).as_posix()
    con.register("_empty", pa.Table.from_pylist([], schema=FACT_SCHEMA))
    con.execute(f"create or replace table {SCHEMA}._new_fact as select * from _empty")
    con.unregister("_empty")
    rows: list[tuple] = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.startswith("CIK"))
        for i, name in enumerate(names, 1):
            rows += facts(json.loads(z.read(name)), f"{rel}!{name}")
            if len(rows) >= BATCH_ROWS:
                _flush(con, rows)
                rows = []
            if i % 5000 == 0:
                echo(f"  companyfacts: {i:,}/{len(names):,} companies read")
    _flush(con, rows)
    with db.transaction(con):
        con.execute(f"drop table if exists {SCHEMA}.fact")
        con.execute(f"alter table {SCHEMA}._new_fact rename to fact")
    return {"fact": db.count(con, f"{SCHEMA}.fact")}
