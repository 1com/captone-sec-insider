"""Read-only queries on `data/lookup.duckdb` for the stock lookup (feature 005, research R4, R7–R9).

The app opens one read-only connection; every request uses its own cursor, because DuckDB
connections are not thread-safe and cursors are.
"""

import duckdb

from sentinel.api import glossary
from sentinel.api.lookup import NEWEST_FIRST
from sentinel.config import Paths
from sentinel.core.entities import SENIORITY
from sentinel.core.symbols import normalise
from sentinel.warehouse import MEMORY_LIMIT, exact_sum


def open_lookup(paths: Paths) -> duckdb.DuckDBPyConnection:
    """The lookup file, read-only, attached as `lk` and made the default: opened directly, a file
    named lookup.duckdb would be catalog "lookup" and clash with the schema `lookup`."""
    con = duckdb.connect(config={"memory_limit": MEMORY_LIMIT, "threads": 4})
    target = str(paths.lookup).replace("'", "''")
    con.execute(f"attach '{target}' as lk (read_only)")
    con.execute("use lk")
    return con


def cursor(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """A cursor for one request. `use` is per connection, so each cursor sets `lk` again."""
    cur = con.cursor()
    cur.execute("use lk")
    return cur


def meta(cur: duckdb.DuckDBPyConnection) -> dict:
    """The data-as-of facts (rule P6)."""
    as_of, dataset, built, warehouse_built = cur.execute(
        "select data_as_of, dataset, built_at, warehouse_built_at from lookup.meta"
    ).fetchone()
    return {"date": as_of, "dataset": dataset, "built_at": built,
            "warehouse_built_at": warehouse_built}  # fmt: skip


def edgar_url(issuer_cik: str, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{issuer_cik}/{accession.replace('-', '')}/"


def _dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


# --- Search (research R7) ----------------------------------------------------------------------

MIN_QUERY = 2
MAX_RESULTS = 25


def search(cur: duckdb.DuckDBPyConnection, q: str) -> list[dict]:
    """Companies matching a CIK, a ticker (current or past) or part of a filed name: exact CIK or
    ticker first, then names starting with `q`, then the rest; at most 25."""
    q = q.strip()
    cik = q.lstrip("0") if q.isdigit() else None
    return _dicts(
        cur.execute(
            """
            with hits as (
                select *, list_contains([t.ticker for t in tickers], $ticker) as ticker_hit,
                       len([n for n in names if starts_with(lower(n), $lq)]) > 0 as starts,
                       len([n for n in names if contains(lower(n), $lq)]) > 0 as contains_q
                from lookup.issuer_search
            )
            select issuer_cik, name, tickers, n_transactions, first_filing, last_filing
            from hits
            where issuer_cik = $cik or ticker_hit or contains_q
            order by case when issuer_cik = $cik or ticker_hit then 0 when starts then 1 else 2 end,
                     n_transactions desc, name
            limit $limit
            """,
            {"cik": cik, "ticker": normalise(q), "lq": q.lower(), "limit": MAX_RESULTS},
        )
    )


def issuer(cur: duckdb.DuckDBPyConnection, cik: str) -> dict | None:
    found = _dicts(
        cur.execute(
            "select issuer_cik, name, tickers, n_transactions, first_filing, last_filing "
            "from lookup.issuer_search where issuer_cik = ?",
            [cik],
        )
    )
    return found[0] if found else None


# --- Transactions (research R8) ----------------------------------------------------------------

PAGE_SIZE = 100


def transaction_row(r: dict) -> dict:
    """One transaction as pages and JSON show it (contracts/http.md): the same dict for both."""
    return {
        "accession": r["accession"],
        "line_sk": r["line_sk"],
        "filing_date": r["filing_date"],
        "trade_date": r["trans_date"],
        "form": r["document_type"],
        "form_description": glossary.label(glossary.FORMS, r["document_type"]),
        "code": r["trans_code"] or "",
        "code_description": glossary.describe_code(r["trans_code"]),
        "acquired_disposed": r["acq_disp"],
        "security_title": r["security_title"],
        "shares": r["shares"],
        "price": r["price"],
        "value_usd": r["value_usd"],
        "shares_after": r["shares_after"],
        "holding": {"D": "direct", "I": "indirect"}.get(r["direct_indirect"]),
        "holder": r["nature_of_ownership"],
        "owners": r["owners"],
        "footnote_ids": list(r["fn_ids"] or []),
        "edgar_url": edgar_url(r["issuer_cik"], r["accession"]),
    }


def transactions_page(
    cur: duckdb.DuckDBPyConnection, cik: str, page: int = 1, page_size: int = PAGE_SIZE
) -> tuple[list[dict], int]:
    """One page of a company's transactions, newest filing first, and the total count."""
    total = cur.execute(
        "select count(*) from lookup.transaction where issuer_cik = ?", [cik]
    ).fetchone()[0]
    found = _dicts(
        cur.execute(
            f"select * from lookup.transaction where issuer_cik = ? order by {NEWEST_FIRST} "
            "limit ? offset ?",
            [cik, page_size, (page - 1) * page_size],
        )
    )
    owners = dict(
        cur.execute(
            "select accession, list({'cik': owner_cik, 'name': owner_name, 'role': role, "
            "'title': title} order by owner_cik) from lookup.filing_owner "
            "where issuer_cik = ? and list_contains(?, accession) group by 1",
            [cik, sorted({r["accession"] for r in found})],
        ).fetchall()
    )
    return [transaction_row({**r, "owners": owners.get(r["accession"], [])}) for r in found], total


def footnotes(cur: duckdb.DuckDBPyConnection, accession: str, ids: list[str]) -> list[tuple]:
    """(footnote id, text) for the given ids of one filing, in the order asked; unknown ids skip."""
    found = dict(
        cur.execute(
            "select footnote_id, text from lookup.footnote where accession = ? "
            "and list_contains(?, footnote_id)",
            [accession, ids],
        ).fetchall()
    )
    return [(i, found[i]) for i in ids if i in found]


# --- Insiders and holdings (research R5) -------------------------------------------------------


def insiders(cur: duckdb.DuckDBPyConnection, cik: str, owner_cik: str | None = None) -> list[dict]:
    """A company's reporting owners: name, role and title on their latest filing, number of
    filings, first and last filing date; newest filer first. `owner_cik` keeps one owner."""
    rows = _dicts(
        cur.execute(
            """
            select * from (
                select owner_cik,
                       arg_max({'name': owner_name, 'role': role, 'title': title},
                               (filing_date, accession)) as latest,
                       count(distinct accession) as n_filings,
                       min(filing_date) as first_filing, max(filing_date) as last_filing
                from lookup.filing_owner
                where issuer_cik = $cik and ($owner is null or owner_cik = $owner)
                group by owner_cik
            )
            order by last_filing desc, latest.name, owner_cik
            """,
            {"cik": cik, "owner": owner_cik},
        )
    )
    return [{"owner_cik": r["owner_cik"], **r.pop("latest"), **r} for r in rows]


def holdings(cur: duckdb.DuckDBPyConnection, cik: str, owner_cik: str) -> list[dict]:
    """One insider's shares held after each filing date, per security title: held directly,
    indirectly, the total, the split by holding, and who else was on the filings. On a date with
    several filings, each holding counts once, from the latest filing."""
    direct = exact_sum("case when direct_indirect = 'D' then shares_after end")
    indirect = exact_sum("case when direct_indirect = 'I' then shares_after end")
    return _dicts(
        cur.execute(
            f"""
            with mine as (
                select accession, filing_date from lookup.filing_owner
                where issuer_cik = $cik and owner_cik = $owner
            ),
            latest as (
                select h.*, row_number() over (
                           partition by h.filing_date, h.security_title, h.direct_indirect,
                                        h.nature_of_ownership
                           order by h.accession desc) as rn
                from lookup.holding h join mine using (accession)
            ),
            joint as (
                select m.filing_date, list(distinct o.owner_name order by o.owner_name) as names
                from mine m join lookup.filing_owner o
                  on o.accession = m.accession and o.owner_cik <> $owner
                group by 1
            )
            select l.filing_date, l.security_title, {direct} as direct, {indirect} as indirect,
                   {exact_sum("shares_after")} as total,
                   bool_or(shares_after is null) as incomplete,
                   list({{'holding': direct_indirect, 'holder': nature_of_ownership,
                          'shares': shares_after}}
                        order by direct_indirect, nature_of_ownership) as split,
                   list(distinct accession order by accession) as accessions,
                   coalesce(any_value(j.names), []) as filed_with
            from latest l left join joint j using (filing_date)
            where rn = 1
            group by l.filing_date, l.security_title
            order by l.filing_date desc, l.security_title
            """,
            {"cik": cik, "owner": owner_cik},
        )
    )


# --- Insider-buying events ---------------------------------------------------------------------

ROLE_BY_SENIORITY = {n: role for role, n in SENIORITY.items()}


def events(cur: duckdb.DuckDBPyConnection, cik: str) -> list[dict]:
    """A company's SEC-only insider-buying events, newest first, each with its member filings.
    No return, outcome or score: those exist only after the pre-registration lock."""
    found = _dicts(
        cur.execute(
            """
            select e.event_id, e."group", e.signal_date, e.signal_accession, e.n_entities,
                   e.total_value_usd, e.max_seniority,
                   list({'accession': m.accession, 'filing_date': m.filing_date,
                         'value_usd': m.value_usd, 'role': m.entity_role_at_t,
                         'owner_names': m.owner_names}
                        order by m.filing_date, m.accession) as members
            from lookup.event e join lookup.event_member m using (event_id)
            where e.issuer_cik = ?
            group by all
            order by e.signal_date desc, e.event_id
            """,
            [cik],
        )
    )
    for e in found:
        e["top_role"] = ROLE_BY_SENIORITY.get(e["max_seniority"], "other")
    return found
