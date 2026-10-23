"""The pilot's simplified purchase gates (Appendix A; data-model.md §6–7) and the funnel.

Line gates run in a fixed order so the funnel reconciles; footnote screens look only at the
footnotes cited by that line. Clean filings are filings whose passing lines total at least the
G6 minimum value.
"""

import duckdb

from sentinel.config import registered_value

GATES = (
    "g_purchase",
    "g_original_form4",
    "g_common",
    "g_no_checkbox",
    "g_no_plan_fn",
    "g_no_offering_fn",
    "g_timely",
    "g_price",
)


def apply_gates(con: duckdb.DuckDBPyConnection, params: dict) -> None:
    prov = params["provisional"]
    args = {
        "plan_re": prov["plan_footnote_regex"],
        "offer_re": prov["offering_footnote_regex"],
        "common_re": prov["common_title_regex"],
        "excl_re": prov["excluded_title_regex"],
        "timely_days": registered_value(params, "g6_timeliness"),
        "price_floor": prov["price_standin_floor"],
    }
    con.execute(
        """
        create or replace table p_gated as
        with cited as (
            select accession, line_sk, unnest(fn_ids) as footnote_id from p_purchase_line
        ), hits as (
            select c.accession, c.line_sk,
                   bool_or(regexp_matches(f.text, $plan_re, 'i')) as plan_fn,
                   bool_or(regexp_matches(f.text, $offer_re, 'i')) as offering_fn
            from cited c join p_footnote f using (accession, footnote_id)
            group by c.accession, c.line_sk
        )
        select l.accession, l.line_sk, l.quarter, s.issuer_cik, s.filing_date, l.shares, l.price,
               coalesce(l.acq_disp = 'A', false) as g_purchase,
               coalesce(s.document_type = '4', false) as g_original_form4,
               coalesce(regexp_matches(l.security_title, $common_re, 'i')
                        and not regexp_matches(l.security_title, $excl_re, 'i'), false) as g_common,
               not coalesce(s.aff10b5one, false) as g_no_checkbox,
               not coalesce(h.plan_fn, false) as g_no_plan_fn,
               not coalesce(h.offering_fn, false) as g_no_offering_fn,
               coalesce(date_diff('day', l.trans_date, s.filing_date)
                        between 0 and $timely_days, false) as g_timely,
               coalesce(l.price >= $price_floor, false) as g_price
        from p_purchase_line l
        join p_submission s using (accession)
        left join hits h using (accession, line_sk)
        """,
        args,
    )
    con.execute(
        "create or replace table p_gated as select *, " + " and ".join(GATES) + " as passes "
        "from p_gated"
    )
    con.execute(
        """
        create or replace table p_clean_filing as
        with v as (
            select accession, any_value(quarter) as quarter, any_value(issuer_cik) as issuer_cik,
                   any_value(filing_date) as filing_date, sum(shares * price) as value_usd
            from p_gated where passes group by accession
            having sum(shares * price) >= $min_value
        )
        select v.*,
               list_sort(list(o.owner_cik) filter (where o.owner_cik is not null)) as owner_ciks,
               coalesce(bool_or(o.is_ceo_cfo), false) as has_ceo_cfo
        from v left join p_owner o using (accession)
        group by all
        """,
        {"min_value": prov["filing_min_value"]},
    )
    _build_funnel(con)


def _build_funnel(con: duckdb.DuckDBPyConnection) -> None:
    passed = ["count(*)"] + [
        f"count(*) filter (where {' and '.join(GATES[: k + 1])})" for k in range(len(GATES))
    ]
    rows = con.execute(
        f"select quarter, {', '.join(passed)} from p_gated group by quarter order by quarter"
    ).fetchall()
    filings = dict(
        con.execute(
            "select quarter, count(distinct accession) from p_gated where passes group by quarter"
        ).fetchall()
    )
    clean = dict(
        con.execute("select quarter, count(*) from p_clean_filing group by quarter").fetchall()
    )
    out = []
    for quarter, *counts in rows:
        for step, gate in enumerate(GATES):
            rin, rout = counts[step], counts[step + 1]
            out.append((quarter, step, gate, "lines", rin, rout, rin - rout))
        rin, rout = filings.get(quarter, 0), clean.get(quarter, 0)
        out.append((quarter, len(GATES), "g_min_value", "filings", rin, rout, rin - rout))
    con.execute(
        "create or replace table p_funnel (quarter VARCHAR, step INTEGER, gate VARCHAR, "
        "unit VARCHAR, rows_in BIGINT, rows_out BIGINT, rows_removed BIGINT)"
    )
    if out:
        con.executemany("insert into p_funnel values (?, ?, ?, ?, ?, ?, ?)", out)


def a1_counts(con: duckdb.DuckDBPyConnection, quarter: str) -> dict[str, int]:
    """Counts laid out like Appendix A.1: each line count is a subset of all purchase lines."""
    lines = con.execute(
        """
        select count(*) filter (where g_purchase),
               count(*) filter (where g_purchase and g_original_form4),
               count(*) filter (where g_purchase and g_common),
               count(*) filter (where g_purchase and not g_no_plan_fn),
               count(*) filter (where g_purchase and not g_no_offering_fn),
               count(distinct accession) filter (where g_purchase and g_original_form4 and g_common
                   and g_no_checkbox and g_no_plan_fn and g_no_offering_fn)
        from p_gated where quarter = ?
        """,
        [quarter],
    ).fetchone()
    clean = con.execute(
        "select count(*) from p_clean_filing where quarter = ?", [quarter]
    ).fetchone()[0]
    keys = ["purchase_lines", "original_form4", "common", "plan_fn", "offering_fn", "filings_g1_g5"]
    return dict(zip(keys, lines, strict=True)) | {"clean_filings": clean}
