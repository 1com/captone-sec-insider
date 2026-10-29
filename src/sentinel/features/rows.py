"""Layer 4: the (company, trading day) rows that features are computed for, as of that day's close.

- `month_end`: the last session of each month from `panel.first_month` (risk_params) on which the
  company has a price; for the current month, its latest session. The training panel of the
  volatility and dilution models.
- `release_eve`: for each results release whose report date is usable (`labels.results_move`: on
  or before the filing date, at most `max_report_gap_days` before it), the session before the
  report date: the last close before the results were out. The training rows of the results-move
  model.
- `latest`: each company's last session with a price: the product's current values.

Glitch days have no price, so they have no rows.
"""

import duckdb

from sentinel import db
from sentinel.config import Paths, risk_params


def build_rows(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.price_daily", "core.results_release", "ref.calendar"], "feature.row")
    rp = risk_params(p)
    first = f"{rp['panel']['first_month']}-01"
    gap = int(rp["labels"]["results_move"]["max_report_gap_days"])
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table feature.row as
            with priced as (
                select cik, session from core.price_daily
                where not glitch and close > 0 and adj_close > 0
            ),
            ends as (
                select max(session) as session from ref.calendar
                where session >= DATE '{first}' group by date_trunc('month', session)
            ),
            usable as (
                select cik, report_date from core.results_release
                where report_date <= filing_date and filing_date - report_date <= {gap}
            ),
            eves as (
                select u.cik, c.session
                from usable u asof join ref.calendar c on c.session < u.report_date
            ),
            tagged as (
                select cik, session, 'month_end' as kind from priced join ends using (session)
                union all
                select cik, session, 'release_eve' from eves join priced using (cik, session)
                union all
                select cik, max(session), 'latest' from priced group by cik
            )
            select cik, session as as_of,
                   bool_or(kind = 'month_end') as month_end,
                   bool_or(kind = 'release_eve') as release_eve,
                   bool_or(kind = 'latest') as latest
            from tagged group by cik, session
            order by cik, as_of
            """
        )
    counts = dict(zip(["rows", "month_end", "release_eve", "latest", "companies"], con.execute(
        "select count(*), count(*) filter (where month_end), count(*) filter (where release_eve), "
        "count(*) filter (where latest), count(distinct cik) from feature.row").fetchone(),
        strict=True))  # fmt: skip
    echo(f"  feature rows: {counts}")
    return counts
