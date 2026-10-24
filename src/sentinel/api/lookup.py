"""`sentinel lookup`: build `data/lookup.duckdb` for the stock lookup (feature 005, research R1–R2).

The file holds only what the lookup shows, copied from an allow-list of SEC-derived warehouse
tables (`SOURCES`), so no market price can reach the product (constitution VI) and the running app
never locks the warehouse. It is written to `lookup.duckdb.part` and renamed over the old file only
when every table is built, so a failed build leaves the previous file in place.
"""

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb
import pyarrow as pa

from sentinel.config import Paths
from sentinel.core.symbols import normalise
from sentinel.warehouse import MEMORY_LIMIT, MissingInput

# Transactions are shown newest filing first; line keys are numbers stored as text.
NEWEST_FIRST = "filing_date desc, accession desc, try_cast(line_sk as BIGINT), line_sk"

# Every warehouse table the builder reads (research R2). A guard test checks that the SQL below
# names no other table: no prices, events with floor values, XBRL facts or labels.
SOURCES = (
    "core.filing",
    "core.issuer",
    "core.transaction",
    "core.owner_role",
    "core.build_log",
    "stg.reportingowner",
    "stg.nonderiv_holding",
    "stg.footnotes",
    "evt.prelim_event",
    "evt.prelim_event_member",
)
OPTIONAL = {"core.issuer"}  # company profiles from feature 004; names fall back to the filings
RUN_FIRST = {
    "core.filing": "entities", "core.transaction": "gates", "core.owner_role": "entities",
    "core.build_log": "stage", "stg.reportingowner": "stage", "stg.nonderiv_holding": "stage",
    "stg.footnotes": "stage", "evt.prelim_event": "detect-prelim",
    "evt.prelim_event_member": "detect-prelim",
}  # fmt: skip


@dataclass
class LookupReport:
    rows: dict[str, int] = field(default_factory=dict)
    data_as_of: str | None = None
    dataset: str | None = None


def _quote(path) -> str:
    return str(path).replace("'", "''")


def _exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    schema, table = name.split(".")
    return bool(
        con.execute(
            "select count(*) from information_schema.tables "
            "where table_catalog = 'w' and table_schema = ? and table_name = ?",
            [schema, table],
        ).fetchone()[0]
    )


def _meta(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        create table lookup.meta as
        select (select max(filing_date) from w.core.filing) as data_as_of,
               (select max(quarter) from w.core.filing) as dataset,
               cast(? as TIMESTAMP) as built_at,
               (select max(finished_at) from w.core.build_log) as warehouse_built_at
        """,
        [datetime.now(UTC).replace(tzinfo=None, microsecond=0)],
    )


def _issuer_search(con: duckdb.DuckDBPyConnection) -> None:
    """One row per company: current name, every filed name, every ticker with its years."""
    raw = [
        r[0]
        for r in con.execute(
            "select distinct symbol_raw from w.core.filing where symbol_raw is not null"
        ).fetchall()
    ]
    con.register("_tickers", pa.table({
        "symbol_raw": pa.array(raw, pa.string()),
        "ticker": pa.array([normalise(s) for s in raw], pa.string()),
    }))  # fmt: skip
    current = (
        "select issuer_cik, unnest(tickers) as ticker from w.core.issuer"
        if _exists(con, "core.issuer")
        else "select null::VARCHAR as issuer_cik, null::VARCHAR as ticker where false"
    )
    issuer_name = (
        "left join w.core.issuer i on i.issuer_cik = l.issuer_cik"
        if _exists(con, "core.issuer")
        else "left join (select null::VARCHAR as issuer_cik, null::VARCHAR as name) i on false"
    )
    con.execute(
        f"""
        create table lookup.issuer_search as
        with filed as (
            select f.issuer_cik, f.issuer_name, f.filing_date, f.accession, m.ticker
            from w.core.filing f left join _tickers m on m.symbol_raw = f.symbol_raw
        ),
        latest as (
            select issuer_cik, arg_max(issuer_name, (filing_date, accession)) as filed_name,
                   min(filing_date) as first_filing, max(filing_date) as last_filing
            from filed group by 1
        ),
        names as (
            select issuer_cik, list(distinct issuer_name order by issuer_name) as names
            from filed where issuer_name is not null group by 1
        ),
        now_listed as (select issuer_cik, ticker from ({current}) where ticker is not null),
        years as (
            select issuer_cik, ticker, min(year(filing_date)) as first_year,
                   max(year(filing_date)) as last_year
            from filed where ticker is not null group by 1, 2
            union all
            select n.issuer_cik, n.ticker, null, null from now_listed n
            where not exists (select 1 from filed f where f.issuer_cik = n.issuer_cik
                              and f.ticker = n.ticker)
        ),
        tickers as (
            select y.issuer_cik,
                   list({{'ticker': y.ticker, 'first_year': y.first_year,
                          'last_year': y.last_year}}
                        order by (n.ticker is not null) desc, y.last_year desc nulls first,
                                 y.ticker) as tickers
            from years y left join now_listed n using (issuer_cik, ticker)
            group by 1
        ),
        counts as (select issuer_cik, count(*) as n from w.core.transaction group by 1)
        select l.issuer_cik, coalesce(i.name, l.filed_name) as name,
               coalesce(nm.names, []) as names, coalesce(t.tickers, []) as tickers,
               coalesce(c.n, 0) as n_transactions, l.first_filing, l.last_filing
        from latest l {issuer_name}
        left join names nm on nm.issuer_cik = l.issuer_cik
        left join tickers t on t.issuer_cik = l.issuer_cik
        left join counts c on c.issuer_cik = l.issuer_cik
        order by l.issuer_cik
        """
    )
    con.unregister("_tickers")


def _filing_owner(con: duckdb.DuckDBPyConnection) -> None:
    """One row per (filing, reporting owner), with the owner's role at the filing date."""
    con.execute(
        """
        create table lookup.filing_owner as
        with owners as (
            select o.accession_number as accession, o.rptownercik as owner_cik,
                   arg_min(o.rptownername, o.quarter) as owner_name,
                   any_value(f.issuer_cik) as issuer_cik, any_value(f.filing_date) as filing_date,
                   any_value(f.document_type) as document_type
            from w.stg.reportingowner o join w.core.filing f on f.accession = o.accession_number
            group by 1, 2
        )
        select o.accession, o.owner_cik, o.issuer_cik, o.filing_date, o.document_type,
               o.owner_name, coalesce(r.role, 'other') as role, r.title, r.is_director,
               r.is_officer, r.is_ten_pct, r.is_other
        from owners o asof left join w.core.owner_role r
          on r.issuer_cik = o.issuer_cik and r.owner_cik = o.owner_cik
         and o.filing_date >= r.valid_from
        order by o.issuer_cik, o.filing_date desc, o.accession desc, o.owner_cik
        """
    )


def _transaction(con: duckdb.DuckDBPyConnection) -> None:
    """Every non-derivative line, sorted so one company's rows sit together, newest first. Owners
    are not copied onto the lines: a page reads them from `lookup.filing_owner` (owner lists for
    7.4 million lines ran out of memory at 3 GB, since list() states cannot spill to disk)."""
    con.execute(
        f"""
        create table lookup.transaction as
        select accession, line_sk, issuer_cik, filing_date, document_type, trans_date, trans_code,
               acq_disp, security_title, shares, price, value_usd, shares_after, direct_indirect,
               nature_of_ownership, fn_ids
        from w.core.transaction
        order by issuer_cik, {NEWEST_FIRST}
        """
    )


def _footnote(con: duckdb.DuckDBPyConnection) -> None:
    """The footnotes some transaction cites, from the filing's own quarter (as `core.filing`)."""
    con.execute(
        """
        create table lookup.footnote as
        with cited as (
            select distinct accession, unnest(fn_ids) as footnote_id
            from w.core.transaction where len(fn_ids) > 0
        )
        select c.accession, c.footnote_id, f.footnote_txt as text
        from cited c
        join w.core.filing fl on fl.accession = c.accession
        join w.stg.footnotes f on f.accession_number = c.accession
         and f.footnote_id = c.footnote_id and f.quarter = fl.quarter
        order by 1, 2
        """
    )


def _holding(con: duckdb.DuckDBPyConnection) -> None:
    """Shares held after each filing, per holding (research R5): the holding's last transaction
    line, else its untraded `NONDERIV_HOLDING` row."""
    con.execute(
        """
        create table lookup.holding as
        with lines as (
            select accession, issuer_cik, filing_date, security_title, direct_indirect,
                   coalesce(nature_of_ownership, '') as nature_of_ownership, shares_after,
                   row_number() over (
                       partition by accession, security_title, direct_indirect,
                                    coalesce(nature_of_ownership, '')
                       order by try_cast(line_sk as BIGINT) desc nulls last, line_sk desc
                   ) as from_last
            from w.core.transaction
        ),
        untraded as (
            select h.accession_number as accession, f.issuer_cik, f.filing_date, h.security_title,
                   h.direct_indirect_ownership as direct_indirect,
                   coalesce(h.nature_of_ownership, '') as nature_of_ownership,
                   h.shrs_ownd_folwng_trans as shares_after,
                   row_number() over (
                       partition by h.accession_number, h.security_title,
                                    h.direct_indirect_ownership, coalesce(h.nature_of_ownership, '')
                       order by try_cast(h.nonderiv_holding_sk as BIGINT) desc nulls last,
                                h.nonderiv_holding_sk desc
                   ) as from_last
            from w.stg.nonderiv_holding h
            join w.core.filing f on f.accession = h.accession_number and f.quarter = h.quarter
        ),
        traded as (select * exclude (from_last), 'trade' as source from lines where from_last = 1)
        select * from traded
        union all
        select u.* exclude (from_last), 'holding' from untraded u
        where u.from_last = 1 and not exists (
            select 1 from traded t
            where t.accession = u.accession and t.nature_of_ownership = u.nature_of_ownership
              and t.security_title is not distinct from u.security_title
              and t.direct_indirect is not distinct from u.direct_indirect)
        order by issuer_cik, accession, security_title, direct_indirect, nature_of_ownership
        """
    )


def _event(con: duckdb.DuckDBPyConnection) -> None:
    """The SEC-only insider-buying events and their member filings, with the names on each filing.
    The price stand-in and labelled-window flags stay in the warehouse: the lookup shows no outcome
    or research filter."""
    con.execute(
        """
        create table lookup.event as
        select event_id, issuer_cik, "group", signal_date, signal_accession, n_entities,
               total_value_usd, max_seniority
        from w.evt.prelim_event
        order by issuer_cik, signal_date desc, event_id
        """
    )
    con.execute(
        """
        create table lookup.event_member as
        with names as (
            select accession, list(owner_name order by owner_cik) as owner_names
            from lookup.filing_owner
            where accession in (select accession from w.evt.prelim_event_member)
            group by 1
        )
        select m.event_id, m.accession, f.filing_date, m.value_usd, m.entity_role_at_t,
               coalesce(n.owner_names, []) as owner_names
        from w.evt.prelim_event_member m
        join w.core.filing f on f.accession = m.accession
        left join names n on n.accession = m.accession
        order by m.event_id, f.filing_date, m.accession
        """
    )


# Table builders in build order; each story adds its own (tasks.md).
TABLES: list[Callable[[duckdb.DuckDBPyConnection], None]] = [
    _meta, _issuer_search, _filing_owner, _transaction, _footnote, _holding, _event,
]  # fmt: skip


def build(paths: Paths, params: dict | None = None) -> LookupReport:
    """Build every `lookup.*` table into a shadow file, then replace `data/lookup.duckdb`."""
    part = paths.lookup.with_name(paths.lookup.name + ".part")
    spill = paths.lookup.with_name(paths.lookup.name + ".tmp")
    for leftover in (part, part.with_name(part.name + ".wal")):
        leftover.unlink(missing_ok=True)
    part.parent.mkdir(parents=True, exist_ok=True)
    # Large sorts spill next to the lookup file (not /tmp, a small RAM disk); output order comes
    # from the ORDER BY clauses alone.
    con = duckdb.connect(
        config={"memory_limit": MEMORY_LIMIT, "threads": 2, "temp_directory": str(spill),
                "preserve_insertion_order": False}
    )  # fmt: skip
    try:
        # Attached under an alias: a file named lookup.* would otherwise be catalog "lookup", and
        # "lookup.meta" would be ambiguous between that catalog and the schema.
        con.execute(f"attach '{_quote(part)}' as lk")
        con.execute("use lk")
        con.execute(f"attach '{_quote(paths.warehouse)}' as w (read_only)")
        for name in SOURCES:
            if name not in OPTIONAL and not _exists(con, name):
                raise MissingInput(f"run `sentinel {RUN_FIRST[name]}` first: missing {name}")
        con.execute("create schema lookup")
        for build_table in TABLES:
            build_table(con)
        report = LookupReport()
        tables = con.execute(
            "select table_name from information_schema.tables "
            "where table_catalog = 'lk' and table_schema = 'lookup' order by 1"
        ).fetchall()
        for (table,) in tables:
            report.rows[table] = con.execute(f"select count(*) from lookup.{table}").fetchone()[0]
        as_of, dataset = con.execute("select data_as_of, dataset from lookup.meta").fetchone()
        report.data_as_of, report.dataset = str(as_of), dataset
        con.execute("detach w")
        con.execute("checkpoint lk")
        con.execute("use memory")
        con.execute("detach lk")
    except BaseException:
        con.close()
        part.unlink(missing_ok=True)
        shutil.rmtree(spill, ignore_errors=True)
        raise
    con.close()
    shutil.rmtree(spill, ignore_errors=True)
    os.replace(part, paths.lookup)
    return report
