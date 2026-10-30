"""Layer 3b: filings, financial facts, share counts and results releases, each with `known_at`.

`known_at` is the trading day from whose close a fact may be used. A filing counts from the next
trading day after its filing date, unless its header shows it was accepted before the 4 pm close on
a trading day (then that day). Only headers carry reliable acceptance times (`stg_sec_filings`), so
most filings take the conservative next day: a feature for day D never uses a filing the market
could not have read by D's close. Before the trading calendar starts (2010), the next weekday
stands in for the next trading day.

- `core.filing`: every staged filing: form, dates, 8-K items, `accepted_at_et`, `known_at`. A filing
  staged from a daily index takes its report date and 8-K items from its header.
- `core.financial_fact`: each financial item per company and period, every reported version, the
  first filed flagged; the main tag wins its periods and later tags fill only periods it lacks
  (`staging.sec_xbrl.ITEMS`). `known_at` is the next trading day after the version's filing date.
  Values with impossible dates (a typed year such as 2201) stay in staging but not here.
- `core.shares_outstanding`: the cover-page share count (first filed); a company with no cover-page
  count at all (several share classes, tagged per class) uses its quarterly weighted-average basic
  shares instead, for all its periods (risk_params v5). Typed-in errors are left out (V2-23,
  `share_typos`) and kept with their reason in `core.shares_rejected`.
- `core.results_release`: results releases by the risk_params v5 rule: item 2.02 8-Ks within
  `same_announcement_days` of each other are one announcement, dated by the first; each belongs to
  the company's first 10-Q or 10-K filed from `report_before_days` before it to
  `release_within_days` after it; the last announcement per report is the release. `known_at` is
  the later of the release and its report (only then is it known to be the release).
"""

import math

import duckdb
import pandas as pd

from sentinel import db
from sentinel.config import Paths, risk_params
from sentinel.staging.sec_xbrl import ITEMS

CLOSE_HOUR = 16
QUARTER_DAYS = (80, 100)  # a quarterly weighted average, not a year-to-date one
SHARE_JUMP = 100.0  # a share count this many times above or below its reference is a typo (V2-23)
SHARE_FLOOR = 1000.0  # no listed company has fewer shares: a placeholder or a typo (V2-30)
SHARE_COLUMNS = ["cik", "as_of", "shares", "filed", "known_at", "source"]
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
            with h as (select accession, min(accepted_at_et) as accepted_at_et,
                              max(items) as items, max(period_of_report) as period_of_report
                       from stg_sec_headers.header group by 1),
            base as (select f.cik, f.accession, f.form, f.filing_date,
                            coalesce(f.report_date::DATE, h.period_of_report::DATE) as report_date,
                            coalesce(f.items::VARCHAR, h.items::VARCHAR) as items,
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


def _num(x) -> float | None:
    return float(x) if x is not None and not pd.isna(x) and math.isfinite(float(x)) else None


def share_typos(counts: pd.DataFrame) -> list[str | None]:
    """V2-23: why each share count is a typed-in error, or None. `counts` (cik, shares, source,
    `basic`: the weighted-average basic count of the same filing, `cum`: the price series'
    `cum_split_after` on the count's date, `close`: the as-traded close on or before its filing
    date) is in the order the counts became known per company.

    Each count is judged only by what was known when it was filed (constitution I):
    - zero or below: not a count; below 1,000 shares: a placeholder or a typo (V2-30);
    - a cover-page count with a same-filing average: a typo when 100 times or more away from it;
    - otherwise, a count 100 times or more away from the company's last accepted count (adjusted
      for splits in the price series between the two) is a typo unless the company's market value
      stayed within 10 times of its value then: a real issue of shares or a reverse split moves
      the price the other way, a typo does not. Without both prices, two filings in a row at about
      the same level (within a factor of 2) confirm the change instead."""
    reasons: list[str | None] = []
    last: dict[str, tuple[float, float | None, float | None]] = {}  # count, `cum`, `close`
    jumped: dict[str, float] = {}  # the count just rejected as a jump

    def far(ratio: float) -> bool:
        return ratio >= SHARE_JUMP or ratio <= 1 / SHARE_JUMP

    columns = [counts[c] for c in ("cik", "shares", "source", "basic", "cum", "close")]
    for cik, shares, source, basic, cum, close in zip(*columns, strict=True):
        shares, basic, cum, close = _num(shares), _num(basic), _num(cum), _num(close)
        reason = None
        if shares is None or shares <= 0:
            reason = "not positive"
        elif shares < SHARE_FLOOR:
            reason = "below 1,000 shares"
        elif source == "cover_page" and basic and basic > 0:
            if far(shares / basic):
                reason = "far from the same filing's average count"
        elif cik in last:
            prev, prev_cum, prev_close = last[cik]
            ref = prev * prev_cum / cum if prev_cum and cum else prev
            if far(shares / ref):
                if close and prev_close:
                    kept_value = 0.1 <= shares * close / (prev * prev_close) <= 10
                else:
                    kept_value = cik in jumped and 0.5 <= shares / jumped[cik] <= 2
                if not kept_value:
                    reason = "jump from the last accepted count"
                    jumped[cik] = shares
        reasons.append(reason)
        if reason is None:
            last[cik] = (shares, cum, close)
            jumped.pop(cik, None)
    return reasons


def build_shares(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.financial_fact"], "core.shares_outstanding")
    lo, hi = QUARTER_DAYS
    has_prices = con.execute(
        "select count(*) from duckdb_tables() where schema_name = 'core' "
        "and table_name = 'price_daily'"
    ).fetchone()[0]
    split = (  # the split factor on the count's date; the close known when it was filed
        "asof left join core.price_daily p on p.cik = c.cik and p.session <= c.as_of "
        "asof left join core.price_daily q on q.cik = c.cik and q.session <= c.filed"
        if has_prices
        else ""
    )
    counts = con.execute(
        f"""
        with c as (
            select cik, period_end as as_of, value as shares, filed, known_at,
                   'cover_page' as source
            from core.financial_fact where item = 'shares_outstanding' and first_filed
            union all
            select cik, period_end, value, filed, known_at, 'basic_average'
            from core.financial_fact
            where item = 'shares_basic_avg' and first_filed and period_days between {lo} and {hi}
              and cik not in (select cik from core.financial_fact
                              where item = 'shares_outstanding')
        ),
        basic as (
            select cik, filed, median(value) as basic from core.financial_fact
            where item = 'shares_basic_avg' and value > 0 group by cik, filed
        ),
        priced as (
            select c.*, {"p.cum_split_after" if has_prices else "null::DOUBLE"} as cum,
                   {"q.close" if has_prices else "null::DOUBLE"} as close
            from c {split}
        )
        select priced.*, b.basic from priced left join basic b using (cik, filed)
        order by cik, known_at, as_of, filed
        """
    ).df()
    counts["reason"] = share_typos(counts)
    kept = counts[counts["reason"].isna()][SHARE_COLUMNS]
    rejected = counts[counts["reason"].notna()][[*SHARE_COLUMNS, "reason"]]
    with db.transaction(con):
        for table, frame in (("shares_outstanding", kept), ("shares_rejected", rejected)):
            con.register("_counts", frame)
            con.execute(
                f"create or replace table core.{table} as select * replace "
                "(as_of::DATE as as_of, filed::DATE as filed, known_at::DATE as known_at) "
                "from _counts"
            )
            con.unregister("_counts")
    counts = dict(
        con.execute(
            "select source, count(distinct cik) from core.shares_outstanding group by 1"
        ).fetchall()
    )
    counts |= {f"rejected: {r}": n for r, n in rejected["reason"].value_counts().items()}
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
