"""Layer 3b: filings, financial facts, share counts and results releases, each with `known_at`.

`known_at` is the trading day from whose close a fact may be used. A filing counts from the next
trading day after its filing date, unless its header shows it was accepted before the 4 pm close on
a trading day (then that day). Only headers carry reliable acceptance times (`stg_sec_filings`), so
most filings take the conservative next day: a feature for day D never uses a filing the market
could not have read by D's close. Before the trading calendar starts (2010), the next weekday
stands in for the next trading day.

- `core.filing`: every staged filing: form, dates, 8-K items, `accepted_at_et`, `known_at`.
- `core.financial_fact`: each financial item per company and period, every reported version, the
  first filed flagged; the main tag wins its periods and later tags fill only periods it lacks
  (`staging.sec_xbrl.ITEMS`). `known_at` is the next trading day after the version's filing date.
  Values with impossible dates (a typed year such as 2201) stay in staging but not here.
- `core.shares_outstanding`: the cover-page share count (first filed); a company with no cover-page
  count at all (several share classes, tagged per class) uses its quarterly weighted-average basic
  shares instead, for all its periods (risk_params v5).
- `core.results_release`: results releases by the risk_params v5 rule: item 2.02 8-Ks within
  `same_announcement_days` of each other are one announcement, dated by the first; each belongs to
  the company's first 10-Q or 10-K filed from `report_before_days` before it to
  `release_within_days` after it; the last announcement per report is the release. `known_at` is
  the later of the release and its report (only then is it known to be the release).
"""

import duckdb

from sentinel import db
from sentinel.config import Paths, risk_params
from sentinel.staging.sec_xbrl import ITEMS

CLOSE_HOUR = 16
QUARTER_DAYS = (80, 100)  # a quarterly weighted average, not a year-to-date one
LATE_END_DAYS = 31  # a cover-page count may be dated a little after the filing date
EARLIEST_PERIOD = "1950-01-01"


def next_session(day: str, session: str) -> str:
    """SQL: `session`, the first trading day after `day` (ASOF-joined from `ref.calendar`). Before
    the calendar starts (2010) the next weekday stands in: nothing is priced then, but earlier
    filings keep their order instead of all landing on the calendar's first day."""
    return (
        f"case when {day} < (select min(session) from ref.calendar) "
        f"then {day} + case dayofweek({day}) when 5 then 3 when 6 then 2 else 1 end "
        f"else {session} end"
    )


def same_day_or_next(day: str, accepted: str, session: str) -> str:
    """SQL: `day` itself if `accepted` (ET) is before the close on that trading day, otherwise
    `next_session`."""
    return (
        f"case when hour({accepted}) < {CLOSE_HOUR} and {accepted}::DATE = {day} "
        f"and {day} in (select session from ref.calendar) then {day} "
        f"else {next_session(day, session)} end"
    )


def build_filing(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["stg_sec_filings.filing", "stg_sec_headers.header", "ref.calendar"],
               "core.filing")  # fmt: skip
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table core.filing as
            with h as (select accession, min(accepted_at_et) as accepted_at_et
                       from stg_sec_headers.header group by 1),
            base as (select f.cik, f.accession, f.form, f.filing_date, f.report_date, f.items,
                            h.accepted_at_et
                     from stg_sec_filings.filing f left join h using (accession)
                     where f.filing_date is not null)
            select b.*,
                   {same_day_or_next("b.filing_date", "b.accepted_at_et", "c.session")} as known_at
            from base b asof left join ref.calendar c on c.session > b.filing_date
            """
        )
    total, timed = con.execute("select count(*), count(accepted_at_et) from core.filing").fetchone()
    counts = {"filing": total, "with_acceptance_time": timed}
    echo(f"  filings: {counts}")
    return counts


def _item_tags_sql() -> str:
    rows = [
        f"('{item}', '{tax}', '{tag}', '{unit}', {rank})"
        for item, tags in ITEMS.items()
        for rank, (tax, tag, unit) in enumerate(tags)
    ]
    return "select * from (values " + ", ".join(rows) + ") t(item, taxonomy, tag, unit, tag_rank)"


def _possible_dates(f: str) -> str:
    """SQL: a value's period could be real: it ends by `LATE_END_DAYS` after the filing that
    reports it, and no date is before `EARLIEST_PERIOD`. Typed dates such as 2201 for 2015 fail."""
    return (f"{f}.period_end <= {f}.filed + {LATE_END_DAYS} "
            f"and {f}.period_end >= DATE '{EARLIEST_PERIOD}' "
            f"and ({f}.period_start is null or {f}.period_start between DATE '{EARLIEST_PERIOD}' "
            f"and {f}.period_end)")  # fmt: skip


def build_financial_fact(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["stg_sec_xbrl.fact", "ref.calendar"], "core.financial_fact")
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table core.financial_fact as
            with tagged as (
                select f.cik, t.item, t.tag_rank, f.taxonomy, f.tag, f.unit, f.period_start,
                       f.period_end, f.value, f.filed, f.accession, f.form, f.fp
                from stg_sec_xbrl.fact f
                join ({_item_tags_sql()}) t using (taxonomy, tag, unit)
                where {_possible_dates("f")}
            ),
            best_tag as (  -- per company, item and period: the highest-priority tag reporting it
                select cik, item, period_start, period_end, min(tag_rank) as tag_rank
                from tagged group by all
            ),
            chosen as (
                select t.* from tagged t
                join best_tag b on b.cik = t.cik and b.item = t.item and b.tag_rank = t.tag_rank
                     and b.period_start is not distinct from t.period_start
                     and b.period_end = t.period_end
            )
            select t.cik, t.item, t.period_start, t.period_end,
                   datediff('day', t.period_start, t.period_end) as period_days,
                   t.value, t.unit, t.filed, t.accession, t.form, t.fp, t.taxonomy, t.tag,
                   row_number() over (partition by t.cik, t.item, t.period_start, t.period_end
                                      order by t.filed, t.accession) = 1 as first_filed,
                   {next_session("t.filed", "c.session")} as known_at
            from chosen t asof left join ref.calendar c on c.session > t.filed
            """
        )
    counts = dict(zip(["fact", "first_filed", "companies"], con.execute(
        "select count(*), count(*) filter (where first_filed), count(distinct cik) "
        "from core.financial_fact").fetchone(), strict=True))  # fmt: skip
    counts["impossible_dates"] = con.execute(
        f"select count(*) from stg_sec_xbrl.fact f join ({_item_tags_sql()}) t "
        f"using (taxonomy, tag, unit) where not ({_possible_dates('f')})"
    ).fetchone()[0]
    echo(f"  financial facts: {counts}")
    return counts


def build_shares(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.financial_fact"], "core.shares_outstanding")
    lo, hi = QUARTER_DAYS
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table core.shares_outstanding as
            select cik, period_end as as_of, value as shares, filed, known_at,
                   'cover_page' as source
            from core.financial_fact where item = 'shares_outstanding' and first_filed
            union all
            select cik, period_end, value, filed, known_at, 'basic_average'
            from core.financial_fact
            where item = 'shares_basic_avg' and first_filed and period_days between {lo} and {hi}
              and cik not in (select cik from core.financial_fact
                              where item = 'shares_outstanding')
            """
        )
    counts = dict(
        con.execute(
            "select source, count(distinct cik) from core.shares_outstanding group by 1"
        ).fetchall()
    )
    echo(f"  shares outstanding (companies): {counts}")
    return counts


def build_results_release(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.filing"], "core.results_release")
    rule = risk_params(p)["labels"]["results_move"]
    same, before = int(rule["same_announcement_days"]), int(rule["report_before_days"])
    within = int(rule["release_within_days"])
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table core.results_release as
            with r as (
                select cik, filing_date, report_date from core.filing
                where form = '8-K' and list_contains(string_split(coalesce(items, ''), ','), '2.02')
            ),
            g as (select *, case when filing_date - lag(filing_date) over w <= {same} then 0 else 1
                            end as starts
                  from r window w as (partition by cik order by filing_date)),
            n as (select *, sum(starts) over (partition by cik order by filing_date
                                              rows unbounded preceding) as announcement from g),
            a as (select cik, min(filing_date) as filing_date,
                         arg_min(report_date, filing_date) as report_date
                  from n group by cik, announcement),
            rep as (select cik, filing_date as report_filed from core.filing
                    where form in ('10-Q', '10-K', '10-KT')),
            m as (select a.*, (select min(rep.report_filed) from rep where rep.cik = a.cik
                               and rep.report_filed >= a.filing_date - interval {before} day)
                              as report_filed
                  from a),
            last as (select *, row_number() over (partition by cik, report_filed
                                                  order by filing_date desc) as k
                     from m where report_filed <= filing_date + interval {within} day)
            select cik, filing_date, report_date, report_filed,
                   greatest(report_filed, filing_date) as confirmed
            from last where k = 1
            order by cik, filing_date
            """
        )
    n = db.count(con, "core.results_release")
    echo(f"  results releases: {n:,}")
    return {"results_release": n}
