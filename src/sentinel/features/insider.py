"""Layer 4, family D: insider activity per row of `feature.row`, from the Form 4 lines known by the
row's date and filed in the 3 or 12 months before it (v1's definitions).

Purchases are open-market purchases of common stock on original Forms 4 outside any plan and any
offering (gates G1–G5); sales are open-market sales (code S) of common stock on original Forms 4;
planned sales are those flagged 10b5-1 (checkbox or footnote); offering purchases are the
purchases G5 removes. `buyers_14d` counts the entities with a clean purchase
(`core.insider_activity`) filed in the 14 days to the row's date.
"""

import duckdb

from sentinel import db
from sentinel.config import Paths

INSIDER_COUNTS = ("buy_filings", "buy_value", "sell_filings", "sell_value")
INSIDER_FEATURES = [f"{k}_{w}" for k in INSIDER_COUNTS for w in ("3m", "12m")] + [
    "planned_sell_share_12m",
    "ceo_cfo_sold_12m",
    "offering_buy_value_12m",
    "buyers_14d",
]
BUY = "base and trans_code = 'P' and acq_disp = 'A'"
SELL = "base and trans_code = 'S' and acq_disp = 'D'"


def build_insider(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.insider_trade", "core.insider_owner_role",
                     "core.insider_activity", "stg_sec_form4.reportingowner"],
               "feature.insider")  # fmt: skip
    windows = ",\n".join(
        f"coalesce(sum(d.{k}) filter (where d.filing_date > r.as_of - interval 3 month), 0) "
        f"as {k}_3m,\ncoalesce(sum(d.{k}), 0) as {k}_12m"
        for k in INSIDER_COUNTS
    )
    with db.transaction(con):
        con.execute(
            f"""
            create or replace temp table _tx_day as
            with t as (
                select issuer_cik as cik, filing_date, known_at, accession, quarter, trans_code,
                       acq_disp, value_usd, g1_form4 and g3_common as base,
                       g4a_no_checkbox and g4b_no_plan_fn as unplanned,
                       g5_no_offering_fn as not_offering
                from core.insider_trade
                where issuer_cik in (select distinct cik from feature.row)
                  and known_at is not null
            ),
            ceo_sells as (
                select distinct t.accession
                from t
                join stg_sec_form4.reportingowner o
                  on o.accession_number = t.accession and o.quarter = t.quarter
                asof join core.insider_owner_role r
                  on r.issuer_cik = t.cik and r.owner_cik = o.rptownercik
                 and r.valid_from <= t.filing_date
                where {SELL} and r.role = 'ceo_cfo'
            )
            select t.cik, t.filing_date, t.known_at,
                   count(distinct t.accession) filter (where {BUY} and unplanned
                                                       and not_offering) as buy_filings,
                   coalesce(sum(value_usd) filter (where {BUY} and unplanned and not_offering), 0)
                       as buy_value,
                   count(distinct t.accession) filter (where {SELL}) as sell_filings,
                   coalesce(sum(value_usd) filter (where {SELL}), 0) as sell_value,
                   count(*) filter (where {SELL}) as sell_lines,
                   count(*) filter (where {SELL} and not unplanned) as planned_sell_lines,
                   coalesce(sum(value_usd) filter (where {BUY} and not not_offering), 0)
                       as offering_buy_value,
                   bool_or(c.accession is not null) as ceo_cfo_sell
            from t left join ceo_sells c using (accession)
            group by 1, 2, 3
            """
        )
        con.execute(
            f"""
            create or replace table feature.insider as
            with buyers as (
                select r.cik, r.as_of, count(distinct a.entity_id) as buyers_14d
                from feature.row r
                join core.insider_activity a on a.issuer_cik = r.cik and a.clean
                 and a.known_at <= r.as_of and a.filing_date > r.as_of - interval 14 day
                group by 1, 2
            )
            select r.cik, r.as_of, {windows},
                   sum(d.planned_sell_lines) / nullif(sum(d.sell_lines), 0)
                       as planned_sell_share_12m,
                   cast(coalesce(bool_or(d.ceo_cfo_sell), false) as DOUBLE) as ceo_cfo_sold_12m,
                   coalesce(sum(d.offering_buy_value), 0) as offering_buy_value_12m,
                   coalesce(any_value(b.buyers_14d), 0) as buyers_14d
            from feature.row r
            left join _tx_day d on d.cik = r.cik and d.known_at <= r.as_of
                 and d.filing_date > r.as_of - interval 12 month
            left join buyers b on b.cik = r.cik and b.as_of = r.as_of
            group by r.cik, r.as_of
            order by r.cik, r.as_of
            """
        )
        con.execute("drop table _tx_day")
    return {"insider": db.count(con, "feature.insider")}
