"""The price coverage audit (feature 027, research R12; `specs/027-price-history-repair/`).

`sentinel audit` reads the build database read-only and measures, after any build, the problem
families the audit of 11 November 2026 found in how prices are matched to companies: histories
cut although stored prices reach further back, ticker changes not joined, holes of over a year,
listed companies without a price, disappeared companies whose prices end early, ticker-days given
to two companies, blank-check (SPAC) name periods; then the named cases and coverage by year and
status (constitution III). It runs on the build before the repair (one segment per company, no
decision table) as well as after it, so the two can be compared.

Writes `data/audit/prices-<date>.json` (private: its examples carry dates derived from Tiingo
prices). `summary_markdown` gives the counts-only version for the report.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from sentinel import db
from sentinel.config import Paths

IN_LIST = ("yahoo_primary", "yahoo_primary_late", "yahoo_starts_late→tiingo",
           "yahoo_missing→tiingo", "no_price")  # fmt: skip
EXAMPLES = 5
from sentinel.core.segments import SPAC_NAME, SPAC_NEAR_10, SPAC_YEARS  # noqa: E402


@dataclass(frozen=True)
class Case:
    """A named real case: `sql` returns one boolean for the build."""

    case: str
    sql: str


def _first(cik: str) -> str:
    return f"(select min(session) from core.price_daily where cik = '{cik}')"


NAMED = (
    Case("MGP Ingredients priced from 2010 across MGPI and CASK",
         f"{_first('835011')} <= date '2010-01-31' and exists (select 1 from core.price_daily "
         "where cik = '835011' and ticker = 'CASK')"),
    Case("Viavi priced from 2010 (JDSU, then VIAV)", f"{_first('912093')} <= date '2010-01-31'"),
    Case("Ingersoll Rand priced from Gardner Denver's first day (May 2017)",
         f"{_first('1699150')} <= date '2017-05-31'"),
    Case("Digital Realty priced from 2010", f"{_first('1297996')} <= date '2010-01-31'"),
    Case("Digital Realty's operating partnership has no DLR prices",
         "not exists (select 1 from core.price_daily where cik = '1494877' and ticker = 'DLR')"),
    Case("Palatin priced from 2010 across its exchange move", f"{_first('911216')} <= "
         "date '2010-01-31'"),
    Case("AMN Healthcare priced from 2010", f"{_first('1142750')} <= date '2010-01-31'"),
    Case("Standard BioTools without LaBranche's prices, with its Fluidigm years",
         f"{_first('1162194')} >= date '2011-02-01' and exists (select 1 from core.price_daily "
         "where cik = '1162194' and year(session) = 2015)"),
    Case("Heidmar without the 2010 block", f"{_first('2029471')} >= date '2025-01-01'"),
    Case("Telephone & Data Systems priced",
         "exists (select 1 from core.price_daily where cik = '1051512')"),
    Case("Chatham Lodging priced from its common stock since 2010",
         f"{_first('1476045')} <= date '2010-06-30' and not exists (select 1 from "
         "core.price_daily where cik = '1476045' and ticker like '%-P%')"),
    Case("Xcerra priced across LTXC and XCRA",
         "exists (select 1 from core.price_daily where cik = '357020' and year(session) = 2012) "
         "and exists (select 1 from core.price_daily where cik = '357020' "
         "and year(session) = 2017)"),
    Case("Hanger priced across HGR and HNGR",
         "exists (select 1 from core.price_daily where cik = '722723' and year(session) = 2014) "
         "and exists (select 1 from core.price_daily where cik = '722723' "
         "and year(session) = 2018)"),
    Case("DocGo priced from its merger, without its SPAC months",
         f"{_first('1822359')} >= date '2021-11-01'"),
    Case("Redwire priced from its merger, without its SPAC months",
         f"{_first('1819810')} >= date '2021-08-31'"),
    Case("Fabrinet priced from 2010 (V2-63)", f"{_first('1408710')} <= date '2010-06-30'"),
    Case("Geospace priced from 2010 (not a SPAC name)", f"{_first('1001115')} <= "
         "date '2010-01-31'"),
    Case("Skyline Bankshares keeps its years as Parkway Acquisition Corp. (not a SPAC)",
         f"{_first('1657642')} <= date '2018-12-31'"),
)  # fmt: skip


def _has_table(con, table: str) -> bool:
    schema, name = table.split(".")
    return bool(con.execute(
        "select count(*) from information_schema.tables where table_schema = ? "
        "and table_name = ?", [schema, name]).fetchone()[0])  # fmt: skip


def _columns(con, table: str) -> set[str]:
    schema, name = table.split(".")
    return {r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_schema = ? "
        "and table_name = ?", [schema, name]).fetchall()}  # fmt: skip


def _setup(con) -> dict:
    """Temporary views over either the old layout (one row per company) or segments."""
    cols = _columns(con, "core.price_choice")
    segmented = {"seq", "main"} <= cols
    seq = "seq" if segmented else "1"
    main = "main" if segmented else "true"
    con.execute(f"""
        create or replace temp view seg as
        select cik, {seq} as seq, source, ticker, reason, trim_from, trim_to, listed,
               {main} as main from core.price_choice""")
    in_list = ", ".join(f"'{r}'" for r in IN_LIST)
    con.execute(f"""
        create or replace temp table co as
        select m.cik, c.name, m.ticker, m.reason in ({in_list}) as in_list, c.filer_type,
               c.is_fund, c.is_blank_check, c.first_form4, c.last_periodic, c.tickers,
               p.first_price, p.last_price
        from seg m join ref.company c on c.cik = m.cik
        left join (select cik, min(session) first_price, max(session) last_price
                   from core.price_daily group by 1) p on p.cik = m.cik
        where m.main""")
    con.execute("""
        create or replace temp table series as
        select 'yahoo' as source, ticker, min(session) s0, max(session) s1
        from stg_yahoo.price where close is not null group by 2
        union all
        select 'tiingo', ticker, min(session), max(session)
        from stg_tiingo.price where close is not null group by 2""")
    con.execute("""
        create or replace temp table first_seg as
        select s.cik, s.source, s.ticker, s.trim_from, x.s0 as series_first
        from seg s join (select cik, min(seq) seq from seg group by 1) f using (cik, seq)
        left join series x on x.source = s.source and x.ticker = s.ticker""")
    return {"segmented": segmented, "decisions": _has_table(con, "core.price_decision")}


def _examples(con, sql: str) -> list[dict]:
    rows = con.execute(f"select * from ({sql}) order by cik limit {EXAMPLES}").fetchall()
    return [{"cik": r[0], "name": r[1], "ticker": r[2], "detail": str(r[3])} for r in rows]


def _cuts(con, layout: dict) -> dict:
    """Listed companies whose first segment's series reaches over 180 days before its first day."""
    con.execute("""
        create or replace temp table own_use as select cik, ticker, min(valid_from) f,
               max(valid_to) t from ref.ticker_history where evidence = 'form4' group by 1, 2""")
    con.execute("""
        create or replace temp table other_use as   -- other companies' closed uses, V2-63 rule
        select a.cik, a.ticker, max(b.valid_to) as other_end,
               bool_or(o.f is not null and b.valid_from <= o.t and b.valid_to >= o.f) concurrent
        from (select distinct cik, ticker from ref.ticker_history) a
        join ref.ticker_history b on b.ticker = a.ticker and b.cik <> a.cik
             and b.valid_to is not null
        left join own_use o on o.cik = a.cik and o.ticker = a.ticker
        where not coalesce(b.valid_from > o.f and b.valid_to < o.t, false)
        group by 1, 2""")
    if layout["decisions"]:
        cause = """coalesce((select arg_max(d.kind, d.day_to) from core.price_decision d
                     where d.cik = f.cik and d.kind in ('cut_reuse', 'cut_hole',
                     'cut_blank_check')), 'other')"""
    else:
        cause = """case when f.trim_from = (select max(listing_start) from core.price_candidate k
                         where k.cik = f.cik and k.source = f.source and k.ticker = f.ticker)
                        then 'listing_start'
                        when f.trim_from = o.other_end + 1 then 'other_use' else 'other' end"""
    con.execute(f"""
        create or replace temp table cut as
        select f.*, c.name, {cause} as cause,
               greatest(f.series_first, date '2012-01-01') d0,
               least(f.trim_from, date '2022-12-31') d1,
               coalesce(u.f < f.trim_from - interval 365 day, false) as own_before,
               coalesce(o.concurrent and f.trim_from = o.other_end + 1, false) as concurrent,
               exists (select 1 from stg_tiingo.listing g where g.ticker = f.ticker
                       and g.asset_type = 'Stock' and g.currency = 'USD'
                       and g.end_date between f.trim_from - interval 7 day and f.trim_from)
                   as exchange_move
        from first_seg f join co c on c.cik = f.cik and c.in_list and c.first_price is not null
        left join own_use u on u.cik = f.cik and u.ticker = f.ticker
        left join other_use o on o.cik = f.cik and o.ticker = f.ticker
        where f.trim_from > date '2010-01-01'
          and f.series_first < f.trim_from - interval 180 day""")
    n, months, clear = con.execute("""
        select count(*), coalesce(sum(greatest(0, datediff('month', d0, d1))), 0),
               count(*) filter (where exchange_move or own_before or concurrent)
        from cut""").fetchone()
    by_cause = dict(con.execute("select cause, count(*) from cut group by 1 order by 1").fetchall())
    return {"companies": n, "company_months_2012_2022": int(months), "by_cause": by_cause,
            "clear_evidence": clear,
            "examples": _examples(con, "select cik, name, ticker, cause || ': series from ' "
                                       "|| series_first || ', used from ' || trim_from "
                                       "from cut")}  # fmt: skip


def _ticker_changes(con) -> dict:
    con.execute("""
        create or replace temp table change as
        select c.cik, c.name, h.ticker old_ticker, c.first_price,
               exists (select 1 from series x where x.ticker = h.ticker
                       and x.s0 < c.first_price - interval 180 day) as stored
        from co c join ref.ticker_history h on h.cik = c.cik and h.evidence = 'form4'
        where c.in_list and c.first_price > date '2010-07-01'
          and h.ticker not in (select ticker from seg s
                               where s.cik = c.cik and s.ticker is not null)
          and h.valid_to >= date '2010-06-01'
          and h.valid_from < c.first_price - interval 180 day
          and h.valid_to >= c.first_price - interval 400 day
          and not starts_with(h.ticker, c.ticker) and not starts_with(c.ticker, h.ticker)""")
    n, stored = con.execute(
        "select count(distinct cik), count(distinct cik) filter (where stored) from change"
    ).fetchone()
    return {"companies": n, "old_prices_stored": stored,
            "examples": _examples(con, "select cik, name, old_ticker, 'first price ' || "
                                       "first_price from change")}  # fmt: skip


def _holes(con) -> tuple[dict, dict]:
    con.execute("""
        create or replace temp table hole as
        select cik, max(gap) gap from (
            select cik, session - lag(session) over (partition by cik order by session) gap
            from core.price_daily) where gap > 30 group by 1""")
    over = con.execute("""
        select count(*) filter (where c.in_list), count(*) filter (where not c.in_list)
        from hole h join co c using (cik) where h.gap > 365""").fetchone()
    mid = con.execute("""select count(*) from hole h join co c using (cik)
                         where c.in_list and h.gap between 31 and 365""").fetchone()[0]
    ex = (
        "select h.cik, c.name, c.ticker, h.gap || ' days' from hole h join co c using (cik) "
        "where h.gap {cond}"
    )
    return (
        {
            "listed": over[0],
            "disappeared": over[1],
            "examples": _examples(con, ex.format(cond="> 365")),
        },
        {"listed": mid, "examples": _examples(con, ex.format(cond="between 31 and 365"))},
    )


def _unpriced(con) -> tuple[dict, dict, dict]:
    listed = dict(
        con.execute("""select filer_type, count(*) from co
                                 where in_list and first_price is null group by 1""").fetchall()
    )
    other = con.execute("""select count(distinct c.cik) from co c join core.price_candidate k
                           on k.cik = c.cik where c.in_list and c.first_price is null
                           and k.n_sessions > 0""").fetchone()[0]
    early = con.execute("""select count(*) from co where not in_list and first_price is not null
                           and last_periodic > last_price + interval 365 day""").fetchone()[0]
    never = con.execute("""select count(*) from co where not in_list and filer_type = 'us'
                           and not is_fund and not is_blank_check and first_form4 is not null
                           and first_price is null""").fetchone()[0]
    return (
        {"us": listed.get("us", 0), "foreign": listed.get("foreign", 0),
         "price_only": listed.get("non_reporting", 0), "other_ticker_has_data": other,
         "examples": _examples(con, "select cik, name, ticker, filer_type from co "
                                    "where in_list and first_price is null")},
        {"companies": early,
         "examples": _examples(con, "select cik, name, ticker, 'prices end ' || last_price || "
                                    "', reports to ' || last_periodic from co where not in_list "
                                    "and first_price is not null and last_periodic > "
                                    "last_price + interval 365 day")},
        {"companies": never},
    )  # fmt: skip


def _twice(con) -> dict:
    rows, tickers = con.execute("""
        select count(*), count(distinct ticker) from (
            select source, ticker, session from core.price_daily group by all
            having count(distinct cik) > 1)""").fetchone()
    # across providers: one ticker's day at the same as-traded price for two companies
    same_rows, same_tickers = con.execute("""
        select count(*), count(distinct ticker) from (
            select ticker, session from core.price_daily group by all
            having count(distinct cik) > 1 and max(close) <= 1.01 * min(close))""").fetchone()
    return {
        "rows": rows,
        "tickers": tickers,
        "same_price_rows": same_rows,
        "same_price_tickers": same_tickers,
    }


def _blank_check(con) -> dict:
    con.execute(f"""
        create or replace temp table spac as
        select s.*, (s.vt - s.vf) / 365.25 as years,
               (select avg(case when p.close between 9 and 11 then 1.0 else 0 end)
                from core.price_daily p where p.cik = s.cik and p.session between s.vf and s.vt)
                   as near_10,
               (select count(*) from core.price_daily p where p.cik = s.cik
                and p.session between s.vf and s.vt) as priced_days
        from (select c.cik, c.name, f.name as former, try_cast(f.valid_from as DATE) vf,
                     try_cast(f.valid_to as DATE) vt
              from ref.company c, unnest(c.former_names) u(f)
              where regexp_matches(upper(f.name), '{SPAC_NAME}')
                and c.sic is distinct from '6770') s""")
    con.execute(f"""create or replace temp table spac_counted as select *,
                    years <= {SPAC_YEARS} or coalesce(near_10 >= {SPAC_NEAR_10}, false) as counted
                    from spac""")
    names, cos, counted, rows = con.execute("""
        select count(*), count(distinct cik), count(*) filter (where counted),
               coalesce(sum(priced_days) filter (where counted), 0) from spac_counted""").fetchone()
    return {"names": names, "companies": cos, "counted": counted, "left_out": names - counted,
            "rows_in_counted_periods": int(rows),
            "examples": _examples(con, "select cik, name, former, round(years, 1) || "
                                       "' years, ' || coalesce(round(100 * near_10)::INTEGER "
                                       "|| '% near $10', 'no prices') from spac_counted "
                                       "where not counted")}  # fmt: skip


def _named(con) -> list[dict]:
    out = []
    for c in NAMED:
        try:
            ok = bool(con.execute(f"select coalesce(({c.sql}), false)").fetchone()[0])
        except duckdb.Error:
            ok = False
        out.append({"case": c.case, "pass": ok})
    return out


def _coverage(con) -> list[dict]:
    """Per year and status: companies that filed a periodic report that year, and how many of
    them have a price that year (constitution III)."""
    rows = con.execute("""
        with active as (
            select distinct f.cik, year(f.filing_date) y from stg_sec_filings.filing f
            where f.form in ('10-K', '10-Q', '20-F', '40-F') and year(f.filing_date) >= 2010),
        priced as (select distinct cik, year(session) y from core.price_daily)
        select a.y, case when c.in_list then 'listed' else 'disappeared' end status,
               count(*), count(p.cik)
        from active a join co c on c.cik = a.cik and not c.is_fund and not c.is_blank_check
        left join priced p on p.cik = a.cik and p.y = a.y
        group by 1, 2 order by 1, 2""").fetchall()
    return [{"year": y, "status": s, "companies": n, "priced": k} for y, s, n, k in rows]


def run(con: duckdb.DuckDBPyConnection, today: date) -> dict:
    """Every family, the named cases and coverage, as the JSON of the contract."""
    layout = _setup(con)
    over, mid = _holes(con)
    listed_none, early, never = _unpriced(con)
    listed, priced = con.execute(
        "select count(*) filter (where in_list), count(*) filter (where in_list and "
        "first_price is not null) from co").fetchone()  # fmt: skip
    families = {
        "cut_with_stored_prices": _cuts(con, layout),
        "ticker_change_not_joined": _ticker_changes(con),
        "join_failed": {"companies": 0, "by_reason": {}, "examples": []},
        "hole_over_a_year": over,
        "hole_31_to_365_days": mid,
        "listed_without_price": listed_none,
        "disappeared_prices_end_early": early,
        "disappeared_us_with_form4_without_prices": never,
        "ticker_days_claimed_twice": _twice(con),
        "blank_check_periods": _blank_check(con),
    }
    if layout["decisions"]:
        failed = con.execute("""select count(distinct cik) from core.price_decision
                                where kind = 'join_failed'""").fetchone()[0]
        reasons = dict(
            con.execute("""select split_part(detail, ':', 1), count(*)
                                      from core.price_decision where kind = 'join_failed'
                                      group by 1 order by 1""").fetchall()
        )
        families["join_failed"] = {
            "companies": failed, "by_reason": reasons,
            "examples": _examples(con, "select d.cik, c.name, d.ticker, d.detail from "
                                       "core.price_decision d join co c using (cik) "
                                       "where d.kind = 'join_failed'")}  # fmt: skip
    build_day = con.execute("select max(session) from core.price_daily").fetchone()[0]
    return {"build_date": str(build_day), "audit_date": str(today),
            "layout": "segments" if layout["segmented"] else "one series per company",
            "listed": {"companies": listed, "priced": priced}, "families": families,
            "named_cases": _named(con), "coverage": _coverage(con)}  # fmt: skip


def problems(result: dict) -> list[str]:
    """What makes the audit fail: a ticker-day given twice, a named case failing."""
    out = []
    if result["families"]["ticker_days_claimed_twice"]["rows"]:
        out.append(f"{result['families']['ticker_days_claimed_twice']['rows']:,} ticker-days "
                   "given to two or more companies")  # fmt: skip
    out += [f"named case fails: {c['case']}" for c in result["named_cases"] if not c["pass"]]
    return out


def write(p: Paths, result: dict) -> Path:
    path = p.data / "audit" / f"prices-{result['audit_date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, default=str) + "\n")
    return path


def lines(result: dict) -> list[str]:
    """The printed summary: one line per family, then the named cases."""
    f = result["families"]
    cut, spac = f["cut_with_stored_prices"], f["blank_check_periods"]
    out = [
        f"listed companies: {result['listed']['companies']:,}, priced "
        f"{result['listed']['priced']:,} ({result['layout']}; build {result['build_date']})",
        f"cut although stored prices reach further back: {cut['companies']:,} companies, "
        f"{cut['company_months_2012_2022']:,} company-months of 2012-2022; by cause "
        f"{cut['by_cause']}; clear evidence the cut is wrong: {cut['clear_evidence']:,}",
        f"ticker changes not joined: {f['ticker_change_not_joined']['companies']:,} "
        f"(old prices stored for {f['ticker_change_not_joined']['old_prices_stored']:,}); "
        f"joins failed: {f['join_failed']['companies']:,} {f['join_failed']['by_reason']}",
        f"holes over a year: {f['hole_over_a_year']['listed']:,} listed, "
        f"{f['hole_over_a_year']['disappeared']:,} disappeared; 31-365 days: "
        f"{f['hole_31_to_365_days']['listed']:,} listed",
        f"listed without a price: {f['listed_without_price']['us']:,} US, "
        f"{f['listed_without_price']['foreign']:,} foreign, "
        f"{f['listed_without_price']['price_only']:,} price-only; another ticker has data: "
        f"{f['listed_without_price']['other_ticker_has_data']:,}",
        f"disappeared, prices end over a year before the last report: "
        f"{f['disappeared_prices_end_early']['companies']:,}; US with Form 4s and no prices: "
        f"{f['disappeared_us_with_form4_without_prices']['companies']:,}",
        f"ticker-days given to two or more companies: "
        f"{f['ticker_days_claimed_twice']['rows']:,} on "
        f"{f['ticker_days_claimed_twice']['tickers']:,} tickers; at one price from either "
        f"provider: {f['ticker_days_claimed_twice']['same_price_rows']:,} on "
        f"{f['ticker_days_claimed_twice']['same_price_tickers']:,} tickers",
        f"blank-check (SPAC) names: {spac['names']:,} ({spac['companies']:,} companies), "
        f"counted {spac['counted']:,}, left out {spac['left_out']:,}; priced days inside "
        f"counted periods: {spac['rows_in_counted_periods']:,}",
    ]  # fmt: skip
    passed = sum(c["pass"] for c in result["named_cases"])
    out.append(f"named cases: {passed} of {len(result['named_cases'])} pass")
    out += [f"  {'pass' if c['pass'] else 'FAIL'}  {c['case']}" for c in result["named_cases"]]
    return out


def audit(p: Paths, today: date, echo=print) -> tuple[dict, Path]:
    """Run the audit on the build database (read-only) and write its JSON."""
    con = db.connect(p, read_only=True)
    try:
        result = run(con, today)
    finally:
        con.close()
    path = write(p, result)
    for line in lines(result):
        echo(line)
    echo(f"written: {path}")
    return result, path


ROWS = (  # (label, path in the JSON): the counts the report shows, before and after
    ("Listed companies (in today's SEC list or their last one)", ("listed", "companies")),
    ("... of them priced", ("listed", "priced")),
    ("Cut although stored prices reach further back (companies)",
     ("families", "cut_with_stored_prices", "companies")),
    ("... company-months of 2012-2022 they lack",
     ("families", "cut_with_stored_prices", "company_months_2012_2022")),
    ("Ticker changes not joined (companies)",
     ("families", "ticker_change_not_joined", "companies")),
    ("Joins refused (companies)", ("families", "join_failed", "companies")),
    ("Holes over a year: listed companies", ("families", "hole_over_a_year", "listed")),
    ("Holes over a year: disappeared companies", ("families", "hole_over_a_year", "disappeared")),
    ("Listed US companies without a price", ("families", "listed_without_price", "us")),
    ("Disappeared, prices end over a year before the last report",
     ("families", "disappeared_prices_end_early", "companies")),
    ("Disappeared US companies with Form 4s and no prices",
     ("families", "disappeared_us_with_form4_without_prices", "companies")),
    ("Ticker-days given to two companies (one provider)",
     ("families", "ticker_days_claimed_twice", "rows")),
    ("Ticker-days at one price for two companies (either provider)",
     ("families", "ticker_days_claimed_twice", "same_price_rows")),
    ("Priced days inside blank-check (SPAC) periods",
     ("families", "blank_check_periods", "rows_in_counted_periods")),
)  # fmt: skip


def _get(result: dict, path: tuple):
    for key in path:
        result = (result or {}).get(key) if isinstance(result, dict) else None
    return result


def summary_markdown(after: dict, before: dict | None = None) -> str:
    """The counts-only summary for the report (no price, date or company derived from Tiingo
    values): each family before and after the repair, the named cases' pass or fail."""
    head = (
        "| Measure | Before | After |\n|---|---:|---:|"
        if before
        else "| Measure | Count |\n|---|---:|"
    )
    lines = ["# Price coverage audit", "",
             "Generated by `sentinel audit` (feature 027); never edited by hand. Counts only.", "",
             f"Build of {after['build_date']}" + (f"; before: build of {before['build_date']}"
                                                  if before else "") + ".", "", head]  # fmt: skip
    for label, path in ROWS:
        a = _get(after, path)
        cells = [f"{_get(before, path):,}" if isinstance(_get(before, path), int) else "–"] \
            if before else []  # fmt: skip
        lines.append(f"| {label} | " + " | ".join([*cells, f"{a:,}" if isinstance(a, int) else "–"])
                     + " |")  # fmt: skip
    passed = sum(c["pass"] for c in after["named_cases"])
    lines += ["", f"Named cases: {passed} of {len(after['named_cases'])} pass.", ""]
    lines += [f"- {'pass' if c['pass'] else 'FAIL'}: {c['case']}" for c in after["named_cases"]]
    return "\n".join(lines) + "\n"
