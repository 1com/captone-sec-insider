"""Step 4: gate flags on every transaction line, clean purchases with holdings, and the funnel
(research.md R5; W5, W6).

Line gates G1–G6a run in a fixed order so the funnel chains; footnote screens look only at the
footnotes the line itself cites. A clean purchase is a filing whose passing lines total at least
`registered.g6_min_value` (G6b). Co-filers are one entity, so that is one row per filing, with the
entity and its seniority taken as of the filing date. Every builder takes `cutoff` and `issuers`
like the entity builders, for the truncation test (W9).
"""

from dataclasses import dataclass

import duckdb

from sentinel.config import registered_value
from sentinel.core import entities
from sentinel.core.stage import TABLE_SPECS
from sentinel.warehouse import exact_sum, row_count, scope

LINE_GATES = (
    "g1_form4",
    "g2_purchase",
    "g3_common",
    "g4a_no_checkbox",
    "g4b_no_plan_fn",
    "g5_no_offering_fn",
    "g6a_timely_valued",
)
FILING_GATE = "g6b_min_value"

_FN_COLUMNS = [c.lower() for c in TABLE_SPECS["NONDERIV_TRANS"].columns if c.endswith("_FN")]


def _common(column: str) -> str:
    """SQL: the security title is common stock (G3)."""
    return (
        f"coalesce(regexp_matches({column}, $common_re, 'i') "
        f"and not regexp_matches({column}, $excl_re, 'i'), false)"
    )


def _title_args(params: dict) -> dict:
    rules = params["rules"]
    return {
        "common_re": rules["gate_common_title_regex"],
        "excl_re": rules["gate_excluded_title_regex"],
    }


def build_transactions(con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None):
    """`core.transaction`: every non-derivative line (first quarter per line), with gate flags."""
    where, args = scope(cutoff, issuers)
    rules = params["rules"]
    args |= _title_args(params) | {
        "plan_re": rules["gate_plan_footnote_regex"],
        "offer_re": rules["gate_offering_footnote_regex"],
        "timely_days": registered_value(params, "g6_timeliness"),
    }
    cited = ", ".join(f"t.{c}" for c in _FN_COLUMNS)
    con.execute(
        f"""
        create or replace table core.transaction as
        with lines as materialized (
            select t.accession_number as accession, t.nonderiv_trans_sk as line_sk,
                   f.quarter, f.issuer_cik, f.filing_date, f.document_type, f.aff10b5one,
                   t.security_title, t.trans_date, t.trans_code,
                   t.trans_acquired_disp_cd as acq_disp, t.trans_shares as shares,
                   t.trans_pricepershare as price, t.shrs_ownd_folwng_trans as shares_after,
                   t.direct_indirect_ownership as direct_indirect, t.nature_of_ownership,
                   list_sort(list_distinct(list_filter(
                       list_transform(string_split(concat_ws(',', {cited}), ','), x -> trim(x)),
                       x -> x <> ''
                   ))) as fn_ids
            from stg.nonderiv_trans t
            join core.filing f on f.accession = t.accession_number
            where {where}
            qualify row_number() over (
                partition by t.accession_number, t.nonderiv_trans_sk order by t.quarter, t.src_row
            ) = 1
        ),
        notes as (
            select n.accession_number as accession, n.footnote_id,
                   regexp_matches(n.footnote_txt, $plan_re, 'i') as plan_fn,
                   regexp_matches(n.footnote_txt, $offer_re, 'i') as offering_fn
            from stg.footnotes n
            join core.filing f on f.accession = n.accession_number and f.quarter = n.quarter
            where {where}
        ),
        hits as (
            select c.accession, c.line_sk,
                   bool_or(n.plan_fn) as plan_fn, bool_or(n.offering_fn) as offering_fn
            from (select accession, line_sk, unnest(fn_ids) as footnote_id from lines) c
            join notes n using (accession, footnote_id)
            group by all
        ),
        flagged as (
            select l.* exclude (aff10b5one), l.shares * l.price as value_usd,
                   coalesce(l.document_type = '4', false) as g1_form4,
                   coalesce(l.trans_code = 'P' and l.acq_disp = 'A', false) as g2_purchase,
                   {_common("l.security_title")} as g3_common,
                   not coalesce(l.aff10b5one, false) as g4a_no_checkbox,
                   not coalesce(h.plan_fn, false) as g4b_no_plan_fn,
                   not coalesce(h.offering_fn, false) as g5_no_offering_fn,
                   coalesce(date_diff('day', l.trans_date, l.filing_date) between 0 and $timely_days
                            and l.shares * l.price > 0, false) as g6a_timely_valued
            from lines l left join hits h using (accession, line_sk)
        )
        select *, {" and ".join(LINE_GATES)} as passes_lines from flagged
        """,
        args,
    )
    return row_count(con, "core.transaction")


def build_clean_purchases(
    con: duckdb.DuckDBPyConnection,
    params: dict,
    cutoff=None,
    issuers=None,
    target: str = "core.clean_purchase",
    line_filter: str | None = None,
) -> int:
    """`core.clean_purchase`: filings whose passing lines reach the G6 minimum, with the entity
    as of the filing date and the entity's holdings before and after (research.md R5).

    Holdings use every common-stock line of the filing, whatever its code or gates: per holding
    (`direct_indirect`, `nature_of_ownership`), after = the last line's shares owned, and before =
    after − acquired + disposed. Untraded common-stock rows of `stg.nonderiv_holding` add to both.
    Missing shares make the totals null; so does a negative "before" in any holding, for "before".
    """
    where, args = scope(cutoff, issuers, alias="t")
    args |= {"min_value": registered_value(params, "g6_min_value")}
    con.execute(
        f"""
        create or replace temp table _clean as
        select accession, any_value(issuer_cik) as issuer_cik,
               any_value(filing_date) as filing_date, any_value(quarter) as quarter,
               {exact_sum("value_usd")} as value_usd, {exact_sum("shares")} as shares,
               max(trans_date) as max_trade_date, min(trans_date) as min_trade_date
        from core.transaction t
        where passes_lines and {where} and ({line_filter or "true"})
        group by accession
        having {exact_sum("value_usd")} >= $min_value
        """,
        args,
    )
    con.execute(
        """
        create or replace temp table _clean_owner as
        select c.accession, c.issuer_cik, c.filing_date as t,
               min(o.rptownercik) as owner_cik,
               list_sort(list_distinct(list(o.rptownercik))) as owner_ciks
        from _clean c
        left join stg.reportingowner o on o.accession_number = c.accession and o.quarter = c.quarter
        group by all
        """
    )
    entities.resolve_entities(con, "_clean_owner", "_clean_entity")
    role = " ".join(f"when {n} then '{r}'" for r, n in entities.SENIORITY.items())
    con.execute(
        f"""
        create or replace table {target} as
        with lines as (
            select t.accession, t.direct_indirect, t.nature_of_ownership, t.acq_disp, t.shares,
                   t.shares_after,
                   row_number() over (
                       partition by t.accession, t.direct_indirect, t.nature_of_ownership
                       order by try_cast(t.line_sk as BIGINT) desc nulls last, t.line_sk desc
                   ) as from_last
            from core.transaction t join _clean c using (accession)
            where t.g3_common
        ),
        per_holding as (
            select accession,
                   max(shares_after) filter (where from_last = 1) as after,
                   {exact_sum("case acq_disp when 'A' then shares when 'D' then -shares end")}
                       as net_bought,
                   bool_or(shares is null or acq_disp not in ('A', 'D')
                           or (from_last = 1 and shares_after is null)) as broken
            from lines
            group by accession, direct_indirect, nature_of_ownership
        ),
        traded as (
            select accession, {exact_sum("after - net_bought")} as before,
                   {exact_sum("after")} as after,
                   bool_or(broken) as broken, bool_or(after - net_bought < 0) as negative
            from per_holding group by accession
        ),
        untraded as (
            select h.accession_number as accession,
                   {exact_sum("h.shrs_ownd_folwng_trans")} as shares,
                   bool_or(h.shrs_ownd_folwng_trans is null) as broken
            from stg.nonderiv_holding h
            join _clean c on c.accession = h.accession_number and c.quarter = h.quarter
            where {_common("h.security_title")}
            group by 1
        ),
        joined as (
            select c.*, e.entity_id, e.entity_seniority, e.owner_ciks,
                   coalesce(tr.broken, true) or coalesce(u.broken, false) as broken,
                   coalesce(tr.negative, false) as negative,
                   tr.before + coalesce(u.shares, 0) as before,
                   tr.after + coalesce(u.shares, 0) as after
            from _clean c
            join _clean_entity e using (accession)
            left join traded tr using (accession)
            left join untraded u using (accession)
        ),
        holdings as (
            select *,
                   case when not broken and not negative then before end as shares_before,
                   case when not broken then after end as shares_after
            from joined
        )
        select accession, issuer_cik, filing_date, quarter, entity_id,
               case entity_seniority {role} end as entity_role, entity_seniority, owner_ciks,
               value_usd, shares, max_trade_date, min_trade_date, shares_before, shares_after,
               shares_before = 0 as opens_position
        from holdings
        """,
        _title_args(params),
    )
    for name in ("_clean", "_clean_owner", "_clean_entity"):
        con.execute(f"drop table {name}")
    return row_count(con, target)


def build_funnel(con: duckdb.DuckDBPyConnection) -> int:
    """`audit.funnel`: per quarter, lines through each line gate in order, then filings (G6b)."""
    passed = ["count(*)"] + [
        f"count(*) filter (where {' and '.join(LINE_GATES[: k + 1])})"
        for k in range(len(LINE_GATES))
    ]
    steps = [
        f"select quarter, {k} as step, '{gate}' as gate, 'lines' as unit, "
        f"n{k} as rows_in, n{k + 1} as rows_out from counts"
        for k, gate in enumerate(LINE_GATES)
    ]
    steps.append(
        f"select c.quarter, {len(LINE_GATES)}, '{FILING_GATE}', 'filings', c.filings, "
        "coalesce(k.clean, 0) from counts c left join clean k using (quarter)"
    )
    con.execute(
        f"""
        create or replace table audit.funnel as
        with counts as (
            select quarter, {", ".join(f"{expr} as n{k}" for k, expr in enumerate(passed))},
                   count(distinct accession) filter (where passes_lines) as filings
            from core.transaction group by quarter
        ),
        clean as (select quarter, count(*) as clean from core.clean_purchase group by quarter)
        select quarter, step, gate, unit, rows_in, rows_out, rows_in - rows_out as rows_removed
        from ({" union all ".join(steps)})
        """
    )
    return row_count(con, "audit.funnel")


@dataclass(frozen=True)
class GateReport:
    lines: int
    clean_purchases: int
    funnel_rows: int
    null_before: int  # clean purchases whose holdings before could not be computed
    null_after: int

    @property
    def rows_written(self) -> int:
        return self.lines + self.clean_purchases + self.funnel_rows


def build(con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None) -> GateReport:
    """Recreate `core.transaction`, `core.clean_purchase` and `audit.funnel`, in one transaction."""
    con.execute("begin transaction")
    try:
        lines = build_transactions(con, params, cutoff, issuers)
        clean = build_clean_purchases(con, params, cutoff, issuers)
        funnel = build_funnel(con)
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    null_before, null_after = con.execute(
        "select count(*) filter (where shares_before is null), "
        "count(*) filter (where shares_after is null) from core.clean_purchase"
    ).fetchone()
    return GateReport(lines, clean, funnel, null_before, null_after)


def funnel_totals(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, int, int]]:
    """(gate, unit, rows_in, rows_out) summed over quarters, in gate order."""
    return con.execute(
        "select gate, unit, sum(rows_in)::BIGINT, sum(rows_out)::BIGINT from audit.funnel "
        "group by step, gate, unit order by step"
    ).fetchall()


def check_funnel(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W5: each step's rows add up, line gates chain, and the ends match the tables they count."""
    problems = [
        f"{q} {gate}: in {i:,} ≠ out {o:,} + removed {r:,}"
        for q, gate, i, o, r in con.execute(
            "select quarter, gate, rows_in, rows_out, rows_removed from audit.funnel "
            "where rows_in <> rows_out + rows_removed order by all"
        ).fetchall()
    ]
    problems += [
        f"{q} {gate}: in {i:,} ≠ previous step's out {prev:,}"
        for q, gate, i, prev in con.execute(
            """
            select quarter, gate, rows_in, prev from (
                select *, lag(rows_out) over (partition by quarter order by step) as prev
                from audit.funnel where unit = 'lines')
            where prev is not null and rows_in <> prev order by all
            """
        ).fetchall()
    ]
    problems += [
        f"{q}: {what} {got:,} in the funnel but {want:,} in the tables"
        for q, what, got, want in con.execute(
            f"""
            with lines as (
                select quarter, count(*) as n,
                       count(distinct accession) filter (where passes_lines) as filings
                from core.transaction group by quarter
            ), clean as (select quarter, count(*) as n from core.clean_purchase group by quarter),
            f as (select * from audit.funnel)
            select quarter, 'lines', f.rows_in, coalesce(l.n, 0)
            from f full join lines l using (quarter) where f.step = 0 or f.step is null
            union all
            select f.quarter, 'passing filings', f.rows_in, l.filings
            from f join lines l using (quarter) where f.gate = '{FILING_GATE}'
            union all
            select f.quarter, 'clean purchases', f.rows_out, coalesce(c.n, 0)
            from f left join clean c using (quarter) where f.gate = '{FILING_GATE}'
            """
        ).fetchall()
        if got != want
    ]
    return problems


def check_min_value(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """W6: clean purchases below the G6 minimum (accessions)."""
    return [
        acc
        for (acc,) in con.execute(
            "select accession from core.clean_purchase where not (value_usd >= ?) order by 1",
            [registered_value(params, "g6_min_value")],
        ).fetchall()
    ]
