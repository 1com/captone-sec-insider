"""Layer 4: `feature.snapshot`, every family joined on (company, day), with the panel's row rules
of `config/risk_params.yaml` (v1's `assemble`).

- `active_filer`: any filing (`core.filing`, or a Form 4 about the company) filed in the
  `active_filer_months` before the row's date and known by it.
- `excluded`: funds and blank-check companies (`ref.company`, and the excluded SIC codes).
- `eligible`: an active filer, close and 20-day dollar volume at the floors, at least
  `min_price_history_sessions` price days, not excluded: the rows the risk models learn from.
- Foreign private issuers (`foreign_filer`): their insiders did not file Form 4 and they report on
  6-K, not 8-K, so the insider and 8-K features are missing, not zero; their share counts are of
  ordinary shares while the price is often an ADR's, so market value is missing too.
- `net_buy_to_mcap_12m`: insider purchases minus sales over the year, over market value.
"""

import duckdb

from sentinel import db
from sentinel.config import Paths, risk_params
from sentinel.features.events import EIGHT_K_FEATURES, EVENT_FEATURES
from sentinel.features.fundamentals import FUND_FEATURES
from sentinel.features.insider import INSIDER_FEATURES
from sentinel.features.market import SHORT_FEATURES, macro_features
from sentinel.features.price import PRICE_EXTRAS, PRICE_FEATURES

FOREIGN_BLANK = [*INSIDER_FEATURES, "log_market_cap", "book_to_market"]


def feature_columns(p: Paths) -> list[str]:
    """The model features, in snapshot order."""
    return [*PRICE_FEATURES, *FUND_FEATURES, *EVENT_FEATURES, *INSIDER_FEATURES,
            "net_buy_to_mcap_12m", *SHORT_FEATURES, *macro_features(p)]  # fmt: skip


def build_snapshot(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    tables = ["feature.row", "feature.price", "feature.fundamental", "feature.event",
              "feature.insider", "feature.short", "feature.macro", "ref.company", "ref.sector",
              "ref.security", "core.filing", "core.insider_filing"]  # fmt: skip
    db.require(con, tables, "feature.snapshot")
    rules = risk_params(p)["panel"]
    months = int(rules["active_filer_months"])
    excluded_sic = ", ".join(str(int(s)) for s in rules["excluded_sic"])
    blank = set(FOREIGN_BLANK) | set(EIGHT_K_FEATURES)
    families = (("f", FUND_FEATURES), ("e", EVENT_FEATURES), ("i", INSIDER_FEATURES),
                ("s", SHORT_FEATURES), ("m", macro_features(p)))  # fmt: skip
    columns = ", ".join(
        f"case when foreign_filer then null else {alias}.{c} end as {c}" if c in blank
        else f"{alias}.{c}"
        for alias, cols in families
        for c in cols
    )  # fmt: skip
    with db.transaction(con):
        con.execute(
            """
            create or replace temp table _filed as
            select cik, known_at, max(filing_date) as filing_date from (
                select cik, filing_date, known_at from core.filing
                union all
                select issuer_cik, filing_date, known_at from core.insider_filing
            )
            where known_at is not null and cik in (select distinct cik from feature.row)
            group by cik, known_at
            """
        )
        con.execute(
            f"""
            create or replace table feature.snapshot as
            with x as (
                select r.*, sc.coverage, c.filer_type, c.filer_type = 'foreign' as foreign_filer,
                       g.sector,
                       coalesce(c.is_fund or c.is_blank_check, false)
                           or coalesce(try_cast(c.sic as INTEGER) in ({excluded_sic}), false)
                           as excluded,
                       coalesce(a.filing_date > r.as_of - interval {months} month, false)
                           as active_filer
                from feature.row r
                left join ref.company c using (cik)
                left join ref.sector g using (cik)
                left join ref.security sc on sc.security_id = r.cik
                asof left join _filed a on a.cik = r.cik and a.known_at <= r.as_of
            )
            select x.cik, x.as_of, x.month_end, x.release_eve, x.latest, x.coverage,
                   x.filer_type, x.foreign_filer, x.sector,
                   {", ".join(f"p.{c}" for c in PRICE_FEATURES + PRICE_EXTRAS)},
                   f.market_cap, f.shares_outstanding, {columns},
                   case when x.foreign_filer then null
                        else (i.buy_value_12m - i.sell_value_12m) / nullif(f.market_cap, 0)
                   end as net_buy_to_mcap_12m,
                   x.active_filer, x.excluded,
                   x.active_filer and p.close >= {float(rules["min_close"])}
                       and coalesce(p.addv20 >= {float(rules["min_addv20_usd"])}, false)
                       and p.sessions_listed >= {int(rules["min_price_history_sessions"])}
                       and not x.excluded as eligible
            from x
            join feature.price p using (cik, as_of)
            left join feature.fundamental f using (cik, as_of)
            left join feature.event e using (cik, as_of)
            left join feature.insider i using (cik, as_of)
            left join feature.short s using (cik, as_of)
            left join feature.macro m on m.as_of = x.as_of
            order by x.cik, x.as_of
            """
        )
        con.execute("drop table _filed")
    counts = dict(zip(["rows", "eligible", "eligible_month_end", "latest"], con.execute(
        "select count(*), count(*) filter (where eligible), "
        "count(*) filter (where eligible and month_end), count(*) filter (where latest) "
        "from feature.snapshot").fetchone(), strict=True))  # fmt: skip
    echo(f"  feature snapshot: {counts}")
    return counts
