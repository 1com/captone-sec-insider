"""Step 2: every table of every stored archive → typed staging tables in schema `stg`.

Columns keep their SEC names, lower-cased, plus `quarter` and `src_row` (the 1-based data-row number
in the file), so every staged row traces back to its file. Dates, numbers and flags are typed; a
non-empty value that fails to convert becomes null and its raw text goes to `stg.conversion_issue`
(research.md R1–R2). Empty fields become null. Duplicates across quarters are kept here and
resolved in `core`.
"""

import contextlib
import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pyarrow as pa

from sentinel.config import Paths
from sentinel.ingest import manifest
from sentinel.ingest.sec_bulk import SOURCE
from sentinel.ingest.sec_tables import read_table

DATE_FMT = "%d-%b-%Y"
CHUNK = 16 << 20
SHADOW = "_new_"  # prefix of the tables being built; they replace the live ones at the end


class StageError(Exception):
    """An archive does not have the expected layout."""


@dataclass(frozen=True)
class TableSpec:
    columns: tuple[str, ...]  # SEC header names, in file order; drifting columns included
    dates: frozenset[str] = frozenset()
    numbers: frozenset[str] = frozenset()
    flags: frozenset[str] = frozenset()
    ciks: frozenset[str] = frozenset()

    def kind(self, column: str) -> str:
        for kind, names in (
            ("date", self.dates),
            ("number", self.numbers),
            ("flag", self.flags),
            ("cik", self.ciks),
        ):
            if column in names:
                return kind
        return "text"


def _fn(*names: str) -> tuple[str, ...]:
    """Each column followed by its footnote column, as in the SEC files."""
    return tuple(c for name in names for c in (name, f"{name}_FN"))


_OWNED = _fn(
    "SHRS_OWND_FOLWNG_TRANS",
    "VALU_OWND_FOLWNG_TRANS",
    "DIRECT_INDIRECT_OWNERSHIP",
    "NATURE_OF_OWNERSHIP",
)
_UNDERLYING = _fn("UNDLYNG_SEC_TITLE", "UNDLYNG_SEC_SHARES", "UNDLYNG_SEC_VALUE")
_OWNED_NUMBERS = frozenset({"SHRS_OWND_FOLWNG_TRANS", "VALU_OWND_FOLWNG_TRANS"})
_UNDERLYING_NUMBERS = frozenset({"UNDLYNG_SEC_SHARES", "UNDLYNG_SEC_VALUE"})

TABLE_SPECS: dict[str, TableSpec] = {
    "SUBMISSION": TableSpec(
        columns=(
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
            "AFF10B5ONE",  # from 2023 Q1 only (research.md R1)
        ),
        dates=frozenset({"FILING_DATE", "PERIOD_OF_REPORT", "DATE_OF_ORIG_SUB"}),
        flags=frozenset(
            {
                "NO_SECURITIES_OWNED",
                "NOT_SUBJECT_SEC16",
                "FORM3_HOLDINGS_REPORTED",
                "FORM4_TRANS_REPORTED",
                "AFF10B5ONE",
            }
        ),
        ciks=frozenset({"ISSUERCIK"}),
    ),
    "REPORTINGOWNER": TableSpec(
        columns=(
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
        ),
        ciks=frozenset({"RPTOWNERCIK"}),
    ),
    "NONDERIV_TRANS": TableSpec(
        columns=(
            "ACCESSION_NUMBER",
            "NONDERIV_TRANS_SK",
            *_fn("SECURITY_TITLE", "TRANS_DATE", "DEEMED_EXECUTION_DATE"),
            "TRANS_FORM_TYPE",
            "TRANS_CODE",
            "EQUITY_SWAP_INVOLVED",
            "EQUITY_SWAP_TRANS_CD_FN",
            *_fn("TRANS_TIMELINESS", "TRANS_SHARES", "TRANS_PRICEPERSHARE"),
            *_fn("TRANS_ACQUIRED_DISP_CD"),
            *_OWNED,
        ),
        dates=frozenset({"TRANS_DATE", "DEEMED_EXECUTION_DATE"}),
        numbers=frozenset({"TRANS_SHARES", "TRANS_PRICEPERSHARE"}) | _OWNED_NUMBERS,
        flags=frozenset({"EQUITY_SWAP_INVOLVED"}),
    ),
    "NONDERIV_HOLDING": TableSpec(
        columns=(
            "ACCESSION_NUMBER",
            "NONDERIV_HOLDING_SK",
            *_fn("SECURITY_TITLE", "TRANS_FORM_TYPE"),
            *_OWNED,
        ),
        numbers=_OWNED_NUMBERS,
    ),
    "DERIV_TRANS": TableSpec(
        columns=(
            "ACCESSION_NUMBER",
            "DERIV_TRANS_SK",
            *_fn("SECURITY_TITLE", "CONV_EXERCISE_PRICE", "TRANS_DATE", "DEEMED_EXECUTION_DATE"),
            "TRANS_FORM_TYPE",
            "TRANS_CODE",
            "EQUITY_SWAP_INVOLVED",
            "EQUITY_SWAP_TRANS_CD_FN",
            *_fn("TRANS_TIMELINESS", "TRANS_SHARES", "TRANS_TOTAL_VALUE", "TRANS_PRICEPERSHARE"),
            *_fn("TRANS_ACQUIRED_DISP_CD", "EXCERCISE_DATE", "EXPIRATION_DATE"),
            *_UNDERLYING,
            *_OWNED,
        ),
        dates=frozenset(
            {"TRANS_DATE", "DEEMED_EXECUTION_DATE", "EXCERCISE_DATE", "EXPIRATION_DATE"}
        ),
        numbers=frozenset(
            {"CONV_EXERCISE_PRICE", "TRANS_SHARES", "TRANS_TOTAL_VALUE", "TRANS_PRICEPERSHARE"}
        )
        | _UNDERLYING_NUMBERS
        | _OWNED_NUMBERS,
        flags=frozenset({"EQUITY_SWAP_INVOLVED"}),
    ),
    "DERIV_HOLDING": TableSpec(
        columns=(
            "ACCESSION_NUMBER",
            "DERIV_HOLDING_SK",
            *_fn("SECURITY_TITLE", "CONV_EXERCISE_PRICE", "TRANS_FORM_TYPE"),
            *_fn("EXERCISE_DATE", "EXPIRATION_DATE"),
            *_UNDERLYING,
            *_OWNED,
        ),
        dates=frozenset({"EXERCISE_DATE", "EXPIRATION_DATE"}),
        numbers=frozenset({"CONV_EXERCISE_PRICE"}) | _UNDERLYING_NUMBERS | _OWNED_NUMBERS,
    ),
    "FOOTNOTES": TableSpec(columns=("ACCESSION_NUMBER", "FOOTNOTE_ID", "FOOTNOTE_TXT")),
    "OWNER_SIGNATURE": TableSpec(
        columns=("ACCESSION_NUMBER", "OWNERSIGNATURENAME", "OWNERSIGNATUREDATE"),
        dates=frozenset({"OWNERSIGNATUREDATE"}),
    ),
}

_DDL_TYPE = {"date": "DATE", "number": "DOUBLE", "flag": "BOOLEAN", "cik": "VARCHAR"}


def _typed(kind: str, col: str) -> str:
    """SQL for one column of the registered all-text table."""
    raw = f'"{col}"'
    match kind:
        case "date":
            return f"try_strptime(nullif(trim({raw}), ''), '{DATE_FMT}')::DATE"
        case "number":
            return f"try_cast(nullif(trim({raw}), '') AS DOUBLE)"
        case "flag":
            return (
                f"CASE lower(trim({raw})) WHEN '1' THEN true WHEN 'true' THEN true "
                "WHEN '0' THEN false WHEN 'false' THEN false END"
            )
        case "cik":
            return f"nullif(ltrim(trim({raw}), '0'), '')"
        case _:
            return f"nullif({raw}, '')"


@dataclass
class StageReport:
    total_rows: int = 0
    mismatches: list[tuple[str, str, int, int]] = field(default_factory=list)
    issues_by_column: dict[tuple[str, str], int] = field(default_factory=dict)


def stored_archives(paths: Paths) -> list[tuple[str, Path]]:
    """(quarter, path) of every original quarterly archive recorded in the manifest."""
    originals = [
        e for e in manifest.read_all(paths.manifest) if e.source == SOURCE and e.role == "original"
    ]
    return sorted((e.key, paths.data_raw / e.path) for e in originals)


def _header_and_rows(zf: zipfile.ZipFile, member: str) -> tuple[list[str], int]:
    """The header names and the data-row count (newlines, plus an unterminated last line)."""
    with zf.open(member) as f:
        header = io.TextIOWrapper(f, encoding="utf-8", newline="").readline()
    newlines, last = 0, b"\n"
    with zf.open(member) as f:
        while chunk := f.read(CHUNK):
            newlines += chunk.count(b"\n")
            last = chunk[-1:]
    lines = newlines + (last != b"\n")
    return header.rstrip("\r\n").split("\t"), lines - 1


TABLES = [*(t.lower() for t in TABLE_SPECS), "conversion_issue", "load_report"]


def _create_tables(con: duckdb.DuckDBPyConnection) -> None:
    """The shadow tables, empty."""
    for table, spec in TABLE_SPECS.items():
        cols = ", ".join(
            f"{c.lower()} {_DDL_TYPE.get(spec.kind(c), 'VARCHAR')}" for c in spec.columns
        )
        con.execute(
            f"create or replace table stg.{SHADOW}{table.lower()} "
            f"({cols}, quarter VARCHAR, src_row BIGINT)"
        )
    con.execute(
        f"create or replace table stg.{SHADOW}conversion_issue (table_name VARCHAR, "
        "quarter VARCHAR, src_row BIGINT, column_name VARCHAR, raw_value VARCHAR)"
    )
    con.execute(
        f"create or replace table stg.{SHADOW}load_report (table_name VARCHAR, quarter VARCHAR, "
        "rows_expected BIGINT, rows_loaded BIGINT, columns VARCHAR[])"
    )


@contextlib.contextmanager
def _transaction(con: duckdb.DuckDBPyConnection):
    con.execute("begin transaction")
    try:
        yield
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def _load_one(con, quarter: str, path: Path, table: str, spec: TableSpec) -> None:
    member = f"{table}.tsv"
    with zipfile.ZipFile(path) as zf:
        if member not in zf.namelist():
            raise StageError(f"{path.name} has no {member}")
        header, expected = _header_and_rows(zf, member)
    unexpected = [c for c in header if c not in spec.columns]
    if unexpected:
        raise StageError(f"{path.name} {member} has unexpected column(s): {', '.join(unexpected)}")

    data = read_table(path, table, list(spec.columns))
    data = data.append_column("src_row", pa.array(range(1, data.num_rows + 1), pa.int64()))
    con.register("_raw", data)
    try:
        exprs = ", ".join(_typed(spec.kind(c), c) for c in spec.columns)
        con.execute(
            f"insert into stg.{SHADOW}{table.lower()} select {exprs}, ?, src_row from _raw",
            [quarter],
        )
        checks = [
            f"select '{c.lower()}' as column_name, src_row, \"{c}\" as raw_value from _raw "
            f"where trim(\"{c}\") <> '' and {_typed(spec.kind(c), c)} is null"
            for c in spec.columns
            if c in header and spec.kind(c) in ("date", "number", "flag")
        ]
        if checks:
            con.execute(
                f"insert into stg.{SHADOW}conversion_issue "
                "select ?, ?, src_row, column_name, raw_value "
                f"from ({' union all '.join(checks)})",
                [table.lower(), quarter],
            )
    finally:
        con.unregister("_raw")
    con.execute(
        f"insert into stg.{SHADOW}load_report values (?, ?, ?, NULL, ?)",
        [table.lower(), quarter, expected, [c.lower() for c in header]],
    )


def stage_all(
    con: duckdb.DuckDBPyConnection,
    archives: list[tuple[str, Path]],
    on_progress: Callable[[str], None] | None = None,
) -> StageReport:
    """Recreate every `stg` table from the archives.

    Each quarter is committed on its own into shadow tables, which replace the live tables in one
    final transaction, so a failed run leaves the previous tables as they were. A single
    transaction over every quarter would hold all uncommitted rows in memory (about 300 MB per
    quarter, beyond what DuckDB's memory limit can spill).
    """
    try:
        _create_tables(con)
        for quarter, path in sorted(archives):
            with _transaction(con):
                for table, spec in TABLE_SPECS.items():
                    _load_one(con, quarter, path, table, spec)
            if on_progress:
                on_progress(quarter)
        with _transaction(con):
            for table in TABLE_SPECS:
                con.execute(
                    f"""
                    update stg.{SHADOW}load_report r set rows_loaded = coalesce(c.n, 0)
                    from (select r2.quarter, count(s.quarter) as n
                          from stg.{SHADOW}load_report r2
                          left join stg.{SHADOW}{table.lower()} s on s.quarter = r2.quarter
                          where r2.table_name = '{table.lower()}' group by r2.quarter) c
                    where r.table_name = '{table.lower()}' and r.quarter = c.quarter
                    """
                )
    except BaseException:
        with contextlib.suppress(duckdb.Error):
            for name in TABLES:
                con.execute(f"drop table if exists stg.{SHADOW}{name}")
        raise
    with _transaction(con):
        for name in TABLES:
            con.execute(f"drop table if exists stg.{name}")
            con.execute(f"alter table stg.{SHADOW}{name} rename to {name}")

    report = StageReport()
    for table, quarter, expected, loaded in con.execute(
        "select table_name, quarter, rows_expected, rows_loaded from stg.load_report "
        "order by table_name, quarter"
    ).fetchall():
        report.total_rows += loaded
        if expected != loaded:
            report.mismatches.append((table, quarter, expected, loaded))
    report.issues_by_column = {
        (t, c): n
        for t, c, n in con.execute(
            "select table_name, column_name, count(*) from stg.conversion_issue "
            "group by all order by 3 desc, 1, 2"
        ).fetchall()
    }
    return report


def drift_report(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, list[str]]]:
    """Per table, the quarters in which each column appears in the source files (FR-003)."""
    out: dict[str, dict[str, list[str]]] = {}
    rows = con.execute(
        "select table_name, quarter, unnest(columns) from stg.load_report order by 1, 2"
    ).fetchall()
    for table, quarter, column in rows:
        out.setdefault(table, {}).setdefault(column, []).append(quarter)
    return out
