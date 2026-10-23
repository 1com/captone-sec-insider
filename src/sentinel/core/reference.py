"""Step 7 reference data: FINRA's tick-size pilot intervals and the Kenneth French library
(feature 004, research R12–R13; data-model.md "Reference data").
"""

from dataclasses import dataclass, field
from datetime import date

import duckdb
import pyarrow as pa

from sentinel.config import Paths
from sentinel.ingest import finra, french

TICK_PILOT_COLUMNS = (
    "ticker VARCHAR, pilot_group VARCHAR, valid_from DATE, valid_to DATE, listing_exchange VARCHAR"
)


def build_tick_pilot(con: duckdb.DuckDBPyConnection, paths: Paths) -> int | None:
    """`core.tick_pilot` from the stored change file; None when it is not stored."""
    path = paths.finra / finra.FILE
    if not path.exists():
        return None
    rows = finra.intervals(path.read_text(encoding="utf-8", errors="replace"))
    con.execute("begin transaction")
    try:
        con.execute(f"create or replace table core.tick_pilot ({TICK_PILOT_COLUMNS})")
        if rows:
            con.executemany("insert into core.tick_pilot values (?, ?, ?, ?, ?)", rows)
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    return len(rows)


# --- Kenneth French library (research R12) -----------------------------------------------------

FACTOR_FILES = {
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip": {
        "Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RMW": "rmw", "CMA": "cma", "RF": "rf",
    },
    "F-F_Momentum_Factor_daily_CSV.zip": {"Mom": "mom"},
    "F-F_ST_Reversal_Factor_daily_CSV.zip": {"ST_Rev": "st_rev"},
}  # fmt: skip
INDUSTRY_FILES = {
    "49_Industry_Portfolios_daily_CSV.zip": 49,
    "12_Industry_Portfolios_daily_CSV.zip": 12,
}
SIC_FILES = {"Siccodes49.zip": 49, "Siccodes12.zip": 12}
WEIGHTING = {"Average Value Weighted Returns -- Daily": "vw",
             "Average Equal Weighted Returns -- Daily": "ew"}  # fmt: skip


@dataclass
class FrenchReport:
    factor_rows: int = 0
    industry_rows: int = 0
    sic_ranges: int = 0
    breakpoints: int = 0
    last_date: date | None = None
    missing_files: list[str] = field(default_factory=list)


def build_french(con: duckdb.DuckDBPyConnection, paths: Paths) -> FrenchReport:
    """`core.ff_factor_daily`, `core.ff_industry_daily`, `core.sic_industry`, `core.me_breakpoint`
    from the stored zips; files not stored are listed and their tables left empty."""
    report = FrenchReport()

    def text(name):
        path = paths.french / name
        if not path.exists():
            report.missing_files.append(name)
            return None
        return french.read_member(path.read_bytes())

    factors, industries, sics, points = [], [], [], []
    for name, names in FACTOR_FILES.items():
        if (t := text(name)) is None:
            continue
        for columns, rows in french.sections(t).values():
            keep = [(i, names[c]) for i, c in enumerate(columns) if c in names]
            for day, values in rows:
                for i, factor in keep:
                    v = values[i] if i < len(values) else None
                    factors.append((day, factor, None if v is None else v / 100))
    for name, scheme in INDUSTRY_FILES.items():
        if (t := text(name)) is None:
            continue
        for title, (columns, rows) in french.sections(t).items():
            weighting = WEIGHTING.get(title)
            if weighting is None:
                continue
            for day, values in rows:
                for i, industry in enumerate(columns):
                    v = values[i] if i < len(values) else None
                    industries.append((day, scheme, i + 1, industry, weighting,
                                       None if v is None else v / 100))  # fmt: skip
    for name, scheme in SIC_FILES.items():
        if (t := text(name)) is not None:
            sics += [(scheme, *r) for r in french.sic_ranges(t)]
    if (t := text("ME_Breakpoints_CSV.zip")) is not None:
        points = french.breakpoints(t)
    tables = {
        "core.ff_factor_daily": ("date DATE, factor VARCHAR, ret DOUBLE", factors),
        "core.ff_industry_daily": (
            "date DATE, scheme INTEGER, industry_no INTEGER, industry VARCHAR, "
            "weighting VARCHAR, ret DOUBLE", industries),
        "core.sic_industry": (
            "scheme INTEGER, industry_no INTEGER, industry VARCHAR, description VARCHAR, "
            "sic_from INTEGER, sic_to INTEGER", sics),
        "core.me_breakpoint": (
            "month DATE, n_firms INTEGER, percentile INTEGER, value_musd DOUBLE", points),
    }  # fmt: skip
    con.execute("begin transaction")
    try:
        for table, (columns, rows) in tables.items():
            con.execute(f"create or replace table {table} ({columns})")
            if rows:
                arrow = pa.table(
                    {f"c{i}": pa.array([r[i] for r in rows]) for i in range(len(rows[0]))}
                )
                con.register("_rows", arrow)
                try:
                    con.execute(f"insert into {table} select * from _rows")
                finally:
                    con.unregister("_rows")
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    report.factor_rows, report.industry_rows = len(factors), len(industries)
    report.sic_ranges, report.breakpoints = len(sics), len(points)
    report.last_date = max((f[0] for f in factors), default=None)
    return report


def unmapped_sics(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    """Header SIC codes (signal filings) outside every 49-industry range, with their filings."""
    if not con.execute(
        "select count(*) from information_schema.tables where table_name = 'filing_header'"
    ).fetchone()[0]:
        return []
    return con.execute(
        """
        select h.sic, count(*) from core.filing_header h
        where h.sic is not null and not exists (
            select 1 from core.sic_industry s
            where s.scheme = 49 and try_cast(h.sic as INTEGER) between s.sic_from and s.sic_to)
        group by 1 order by 2 desc, 1
        """
    ).fetchall()
