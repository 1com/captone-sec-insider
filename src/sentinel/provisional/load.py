"""Load the quarterly archives into the scratch DuckDB (data-model.md §5).

All of SUBMISSION is kept (it gives each company's last reported ticker); from the other tables
only code-P purchase lines, their owners and their footnotes. A filing that appears in two
quarterly files is kept once, from the earlier quarter: lines, owners and footnotes follow the
quarter whose SUBMISSION row was kept.
"""

import hashlib
import json
from pathlib import Path

import duckdb

from sentinel.config import Paths, params_sha256
from sentinel.ingest import manifest
from sentinel.ingest.sec_bulk import SOURCE
from sentinel.ingest.sec_tables import read_table

SCRATCH_DB = "provisional_PROVISIONAL.duckdb"
DATE_FMT = "%d-%b-%Y"

SUB_COLS = [
    "ACCESSION_NUMBER",
    "FILING_DATE",
    "DOCUMENT_TYPE",
    "ISSUERCIK",
    "ISSUERNAME",
    "ISSUERTRADINGSYMBOL",
    "AFF10B5ONE",
]
OWNER_COLS = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]
FN_COLS = [
    "SECURITY_TITLE_FN",
    "TRANS_DATE_FN",
    "DEEMED_EXECUTION_DATE_FN",
    "EQUITY_SWAP_TRANS_CD_FN",
    "TRANS_TIMELINESS_FN",
    "TRANS_SHARES_FN",
    "TRANS_PRICEPERSHARE_FN",
    "TRANS_ACQUIRED_DISP_CD_FN",
    "SHRS_OWND_FOLWNG_TRANS_FN",
    "VALU_OWND_FOLWNG_TRANS_FN",
    "DIRECT_INDIRECT_OWNERSHIP_FN",
    "NATURE_OF_OWNERSHIP_FN",
]
TRANS_COLS = [
    "ACCESSION_NUMBER",
    "NONDERIV_TRANS_SK",
    "SECURITY_TITLE",
    "TRANS_DATE",
    "TRANS_CODE",
    "TRANS_SHARES",
    "TRANS_PRICEPERSHARE",
    "TRANS_ACQUIRED_DISP_CD",
    *FN_COLS,
]
FOOT_COLS = ["ACCESSION_NUMBER", "FOOTNOTE_ID", "FOOTNOTE_TXT"]

SCHEMA = """
create or replace table p_submission (
    accession VARCHAR, filing_date DATE, document_type VARCHAR, issuer_cik VARCHAR,
    issuer_name VARCHAR, symbol_raw VARCHAR, aff10b5one BOOLEAN, quarter VARCHAR);
create or replace table p_owner (
    accession VARCHAR, owner_cik VARCHAR, relationship VARCHAR, title VARCHAR,
    is_officer BOOLEAN, is_director BOOLEAN, is_ceo_cfo BOOLEAN);
create or replace table p_purchase_line (
    accession VARCHAR, line_sk VARCHAR, quarter VARCHAR, security_title VARCHAR,
    trans_date DATE, acq_disp VARCHAR, shares DOUBLE, price DOUBLE, fn_ids VARCHAR[]);
create or replace table p_footnote (accession VARCHAR, footnote_id VARCHAR, text VARCHAR);
create or replace table p_load_stats (quarter VARCHAR, submissions_read BIGINT,
    submissions_kept BIGINT, purchase_lines BIGINT);
"""


def _cik(column: str) -> str:
    """CIKs arrive zero-padded ('0000036270'); store them without padding, as the SEC map does."""
    return f"ltrim({column}, '0')"


def load_archives(con: duckdb.DuckDBPyConnection, archives: list[tuple[str, Path]], params) -> None:
    con.execute(SCHEMA)
    ceo_re = params["provisional"]["ceo_cfo_title_regex"]
    fn_concat = "concat_ws(',', " + ", ".join(FN_COLS) + ")"
    for quarter, path in sorted(archives):
        sub = read_table(path, "SUBMISSION", SUB_COLS)
        con.register("_sub", sub)
        con.execute(
            f"""
            insert into p_submission
            select ACCESSION_NUMBER, try_strptime(FILING_DATE, '{DATE_FMT}')::DATE, DOCUMENT_TYPE,
                   {_cik("ISSUERCIK")}, ISSUERNAME, ISSUERTRADINGSYMBOL,
                   case lower(trim(AFF10B5ONE)) when '1' then true when 'true' then true
                        when '0' then false when 'false' then false end,
                   $quarter
            from _sub s
            where not exists (select 1 from p_submission p where p.accession = s.ACCESSION_NUMBER)
            qualify row_number() over (partition by ACCESSION_NUMBER) = 1
            """,
            {"quarter": quarter},
        )
        con.unregister("_sub")
        kept = f"(select accession from p_submission where quarter = '{quarter}')"

        con.register("_trans", read_table(path, "NONDERIV_TRANS", TRANS_COLS))
        con.execute(
            f"""
            insert into p_purchase_line
            select ACCESSION_NUMBER, NONDERIV_TRANS_SK, $quarter, SECURITY_TITLE,
                   try_strptime(TRANS_DATE, '{DATE_FMT}')::DATE, TRANS_ACQUIRED_DISP_CD,
                   try_cast(TRANS_SHARES as DOUBLE), try_cast(TRANS_PRICEPERSHARE as DOUBLE),
                   list_distinct(list_filter(
                       list_transform(string_split({fn_concat}, ','), x -> trim(x)), x -> x <> ''))
            from _trans
            where TRANS_CODE = 'P' and ACCESSION_NUMBER in {kept}
            qualify row_number() over (partition by ACCESSION_NUMBER, NONDERIV_TRANS_SK) = 1
            """,
            {"quarter": quarter},
        )
        con.unregister("_trans")
        with_lines = f"(select distinct accession from p_purchase_line where quarter = '{quarter}')"

        con.register("_own", read_table(path, "REPORTINGOWNER", OWNER_COLS))
        con.execute(
            f"""
            insert into p_owner
            select ACCESSION_NUMBER, {_cik("RPTOWNERCIK")}, RPTOWNER_RELATIONSHIP, RPTOWNER_TITLE,
                   contains(RPTOWNER_RELATIONSHIP, 'Officer'),
                   contains(RPTOWNER_RELATIONSHIP, 'Director'),
                   contains(RPTOWNER_RELATIONSHIP, 'Officer')
                       and regexp_matches(RPTOWNER_TITLE, $ceo_re, 'i')
            from _own
            where ACCESSION_NUMBER in {with_lines}
            qualify row_number() over (partition by ACCESSION_NUMBER, RPTOWNERCIK) = 1
            """,
            {"ceo_re": ceo_re},
        )
        con.unregister("_own")

        con.register("_foot", read_table(path, "FOOTNOTES", FOOT_COLS))
        con.execute(
            f"""
            insert into p_footnote
            select ACCESSION_NUMBER, FOOTNOTE_ID, FOOTNOTE_TXT from _foot
            where ACCESSION_NUMBER in {with_lines}
            qualify row_number() over (partition by ACCESSION_NUMBER, FOOTNOTE_ID) = 1
            """
        )
        con.unregister("_foot")

        con.execute(
            f"""
            insert into p_load_stats select $quarter, {sub.num_rows},
                (select count(*) from p_submission where quarter = $quarter),
                (select count(*) from p_purchase_line where quarter = $quarter)
            """,
            {"quarter": quarter},
        )


def stored_archives(paths: Paths) -> list[tuple[str, Path]]:
    originals = [
        e for e in manifest.read_all(paths.manifest) if e.source == SOURCE and e.role == "original"
    ]
    return sorted((e.key, paths.data_raw / e.path) for e in originals)


def input_fingerprint(paths: Paths) -> str:
    originals = sorted(
        (e.key, e.sha256)
        for e in manifest.read_all(paths.manifest)
        if e.source == SOURCE and e.role == "original"
    )
    blob = json.dumps({"archives": originals, "params": params_sha256(paths.params_file)})
    return hashlib.sha256(blob.encode()).hexdigest()


def build_scratch(paths: Paths, params: dict, rebuild: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the scratch database, rebuilding it when the archives or parameters changed."""
    db = paths.provisional / SCRATCH_DB
    fingerprint = input_fingerprint(paths)
    if db.exists() and not rebuild:
        con = duckdb.connect(str(db))
        try:
            stored = con.execute("select fingerprint from p_meta").fetchone()
        except duckdb.CatalogException:
            stored = None
        if stored and stored[0] == fingerprint:
            return con
        con.close()
    paths.provisional.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    load_archives(con, stored_archives(paths), params)
    con.execute("create or replace table p_meta as select $f as fingerprint", {"f": fingerprint})
    return con
