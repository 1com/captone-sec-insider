"""Insider purchases and sales (Form 4, codes P and S) with their reporting owners.

One pass over the 83 stored archives. Used for the company lookup (buy/sell history) and for model
features that the provisional scratch database lacks: holdings after each purchase and prior
insider selling. Original Form 4s only; a filing repeated across quarters is kept once.
"""

from pathlib import Path

import duckdb

from mvp.config import SENTINEL, WORK
from sentinel.ingest.sec_tables import read_table
from sentinel.provisional.load import stored_archives

OUT = WORK / "insider_tx.parquet"
SUB = ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME"]
TRANS = [
    "ACCESSION_NUMBER",
    "NONDERIV_TRANS_SK",
    "SECURITY_TITLE",
    "TRANS_DATE",
    "TRANS_CODE",
    "TRANS_SHARES",
    "TRANS_PRICEPERSHARE",
    "TRANS_ACQUIRED_DISP_CD",
    "SHRS_OWND_FOLWNG_TRANS",
    "DIRECT_INDIRECT_OWNERSHIP",
    "NATURE_OF_OWNERSHIP",
]
OWN = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]
FMT = "%d-%b-%Y"


def extract(settings, echo=print) -> Path:
    ceo_re = settings.research["provisional"]["ceo_cfo_title_regex"]
    con = duckdb.connect()
    con.execute("""
        create table tx (
            accession VARCHAR, line_sk VARCHAR, quarter VARCHAR, issuer_cik VARCHAR,
            issuer_name VARCHAR, filing_date DATE, trans_date DATE, code VARCHAR,
            acq_disp VARCHAR, shares DOUBLE, price DOUBLE, shares_after DOUBLE,
            direct_indirect VARCHAR, nature VARCHAR, security_title VARCHAR)""")
    con.execute("""
        create table owners (
            accession VARCHAR, owner_names VARCHAR, n_owners INTEGER, is_director BOOLEAN,
            is_officer BOOLEAN, is_ten_pct BOOLEAN, is_ceo_cfo BOOLEAN, title VARCHAR)""")
    archives = stored_archives(SENTINEL)
    for n, (quarter, path) in enumerate(archives, start=1):
        con.register("s", read_table(path, "SUBMISSION", SUB))
        con.register("t", read_table(path, "NONDERIV_TRANS", TRANS))
        con.register("o", read_table(path, "REPORTINGOWNER", OWN))
        con.execute(
            f"""
            insert into tx
            select t.ACCESSION_NUMBER, t.NONDERIV_TRANS_SK, $q, ltrim(s.ISSUERCIK, '0'),
                   s.ISSUERNAME, try_strptime(s.FILING_DATE, '{FMT}')::DATE,
                   try_strptime(t.TRANS_DATE, '{FMT}')::DATE, t.TRANS_CODE,
                   t.TRANS_ACQUIRED_DISP_CD, try_cast(t.TRANS_SHARES as DOUBLE),
                   try_cast(t.TRANS_PRICEPERSHARE as DOUBLE),
                   try_cast(t.SHRS_OWND_FOLWNG_TRANS as DOUBLE), t.DIRECT_INDIRECT_OWNERSHIP,
                   t.NATURE_OF_OWNERSHIP, t.SECURITY_TITLE
            from t join s using (ACCESSION_NUMBER)
            where t.TRANS_CODE in ('P', 'S') and s.DOCUMENT_TYPE = '4'
              and t.ACCESSION_NUMBER not in (select distinct accession from tx)
            """,
            {"q": quarter},
        )
        con.execute(
            """
            insert into owners
            select ACCESSION_NUMBER,
                   string_agg(RPTOWNERNAME, '; ' order by RPTOWNERNAME),
                   count(*)::INTEGER,
                   bool_or(contains(RPTOWNER_RELATIONSHIP, 'Director')),
                   bool_or(contains(RPTOWNER_RELATIONSHIP, 'Officer')),
                   bool_or(contains(RPTOWNER_RELATIONSHIP, 'TenPercentOwner')),
                   bool_or(contains(RPTOWNER_RELATIONSHIP, 'Officer')
                           and regexp_matches(RPTOWNER_TITLE, $re, 'i')),
                   max(nullif(trim(RPTOWNER_TITLE), ''))
            from o
            where ACCESSION_NUMBER in (select distinct accession from tx where quarter = $q)
              and ACCESSION_NUMBER not in (select accession from owners)
            group by ACCESSION_NUMBER
            """,
            {"re": ceo_re, "q": quarter},
        )
        for name in ("s", "t", "o"):
            con.unregister(name)
        if n % 10 == 0 or n == len(archives):
            echo(f"  insider extract: {n}/{len(archives)} quarters")
    WORK.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        copy (
            select tx.*, coalesce(shares * price, 0) as value_usd,
                   owners.owner_names, owners.n_owners, owners.title,
                   coalesce(owners.is_ceo_cfo, false) as is_ceo_cfo,
                   coalesce(owners.is_director, false) as is_director,
                   coalesce(owners.is_officer, false) as is_officer,
                   coalesce(owners.is_ten_pct, false) as is_ten_pct,
                   case when owners.is_ceo_cfo then 'CEO/CFO'
                        when owners.is_officer then 'Officer'
                        when owners.is_director then 'Director'
                        when owners.is_ten_pct then '10% owner'
                        else 'Other' end as role
            from tx left join owners using (accession)
            order by issuer_cik, filing_date, accession, line_sk
        ) to '{OUT}' (format parquet, compression zstd)""")
    rows = con.execute(f"select count(*) from '{OUT}'").fetchone()[0]
    echo(f"  insider extract: {rows:,} purchase/sale lines → {OUT.name}")
    return OUT
