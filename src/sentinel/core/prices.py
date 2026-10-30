"""Layer 3b: one price series per company, and the securities it defines.

Tables:
- `core.price_candidate`: every series that could price a company, with the evidence that links
  them and Tiingo's identity check.
- `core.price_choice`: the series chosen per company and why (one row per company).
- `core.price_daily`: one row per company and trading day: as-traded open, high, low, close and
  volume (what printed that day), the adjusted close, `cum_split_after` (the product of split
  ratios after the day: split-adjusted price = as-traded ÷ `cum_split_after`), dividend, dollar
  volume, and `glitch` (a one-day spike that reverses, `risk_params.yaml` `prices.glitch`).
- `core.price_issue`: rows dropped as invalid (non-positive close, high below low, off-calendar).
- `core.price_check`: Yahoo against Tiingo where both cover a listed company.
- `ref.security`: each priced company's traded line, with its coverage level (spec §4).

Rules (docs/spec.md §5, lessons from v1):
- **Listed today** (in the newest SEC ticker list): Yahoo, under the company's main ticker (its
  first in the SEC's order with Yahoo data). If Yahoo has nothing, or its history starts more than
  `LATE_DAYS` after the company needs it, Tiingo's series of the same ticker is used. The SEC's
  list is the authority on who holds a ticker today, so either source's series of a company's own
  listed ticker is accepted on dates alone (it must still be trading), without comparing names:
  companies renamed since they stopped filing keep their prices (specs/001-daily-data-refresh,
  research R12).
- **Disappeared:** Tiingo, under a ticker its own Form 4s printed (or the bankruptcy `Q` form),
  matched to Tiingo's listing by the longest date overlap with the company's use of it; for a
  company without Form 4 tickers, a hit of Tiingo's name search. The series is kept only if
  Tiingo's company name shares a significant word with one of the company's SEC names and its dates
  overlap the company's filings (v1's identity check).
- **Trims:** a listed company's history starts at the latest of `prices.history_start`, the start
  of its ticker's current listing (Tiingo's ticker list; else the series' first day) and the day
  after another company last used the symbol; a disappeared company's starts `WARMUP_DAYS` before
  its first SEC evidence (another company's older use of the ticker) and ends `TAIL_DAYS` after its
  last (a reused ticker's later prices).
- Yahoo's prices are split-adjusted: as-traded values are rebuilt by undoing later splits; Tiingo's
  unprefixed prices are already as traded. Products of split ratios are exact sums of logs, so a
  rerun gives the same digits (v1).
"""

import re
from datetime import date, timedelta

import duckdb

from sentinel import db
from sentinel.config import Paths, risk_params, sources
from sentinel.reference.build import normalise
from sentinel.staging.sec_form4_daily import union_sql

WARMUP_DAYS = 400
TAIL_DAYS = 90
LATE_DAYS = 45
TRADING_DAYS = 30  # a listed ticker's series must reach within this many days of the SEC list
FAR_PAST, FAR_FUTURE = date(1900, 1, 1), date(2100, 1, 1)
STOPWORDS = {
    "inc", "corp", "corporation", "co", "company", "ltd", "limited", "holdings", "holding",
    "group", "the", "class", "plc", "lp", "llc", "sa", "nv", "new", "de", "and", "of",
}  # fmt: skip
STATE_SUFFIX = re.compile(r"\s*/[A-Za-z]{2,3}/?\s*$")  # "ACME CORP /DE/"


def words(name: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(w) > 1} - STOPWORDS


def same_name(tiingo_name: str | None, sec_names: list[str]) -> bool:
    """Names equal once spaces, punctuation and stop words go ("SigmaAldrich Corp")."""

    def squeeze(name: str | None) -> str:
        return "".join(w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
                       if w not in STOPWORDS)  # fmt: skip

    target = squeeze(tiingo_name)
    return len(target) >= 4 and any(squeeze(n) == target for n in sec_names)


def identity(meta: tuple | None, sec_names: list[str], span: tuple[date, date]) -> str:
    """`ok`, or why a Tiingo series is not this company's: `no_data`, `dates`, `name`."""
    if meta is None or meta[1] is None:
        return "no_data"
    name, start, end = meta
    if start > span[1] or (end is not None and end < span[0]):
        return "dates"
    if not words(name) & set().union(*(words(n) for n in sec_names)) and not same_name(
        name, sec_names
    ):
        return "name"
    return "ok"


def listed_identity(stats: tuple | None, list_day: date) -> str:
    """`ok` when a series of a company's own SEC-listed ticker is still trading (reaches within
    `TRADING_DAYS` of the SEC list), else `no_data` or `dates`."""
    if stats is None or not stats[2]:
        return "no_data"
    return "ok" if stats[1] >= list_day - timedelta(days=TRADING_DAYS) else "dates"


def listing_start(entries: list[tuple], list_day: date) -> date | None:
    """The start of a ticker's current listing in Tiingo's list: the latest-starting entry that
    reaches the SEC list's day (or has no end); None when Tiingo has no such entry."""
    trading = list_day - timedelta(days=TRADING_DAYS)
    current = [a for a, b, _ex in entries if a is not None and (b is None or b >= trading)]
    return max(current) if current else None


def search_queries(names: list[str]) -> list[str]:
    """The name-search queries asked for a company: current and latest former name, no state
    suffix (v1's `universe.search_queries`, so the stored searches are found again)."""
    queries = [STATE_SUFFIX.sub("", n).strip() for n in names[:2] if n]
    return list(dict.fromkeys(q for q in queries if q))


def _companies(con) -> dict[str, dict]:
    rows = con.execute(
        """
        select c.cik, c.name, [n.name for n in coalesce(c.former_names, [])] as former,
               c.filer_type, c.tickers, c.exchanges,
               least(c.first_form4, c.first_periodic, (select min(valid_from)
                     from ref.ticker_history t where t.cik = c.cik)) as first_seen,
               greatest(c.last_form4, c.last_filing, (select max(coalesce(valid_to, today()))
                        from ref.ticker_history t where t.cik = c.cik)) as last_seen
        from ref.company c where not c.is_fund and not c.is_blank_check
        """
    ).fetchall()
    form4_names: dict[str, list[str]] = {}
    for cik, name in con.execute(
        f"select distinct issuercik, issuername from {union_sql(con, 'submission')} "
        "where issuercik is not null and issuername is not null"
    ).fetchall():
        form4_names.setdefault(cik, []).append(name)
    out = {}
    for cik, name, former, filer_type, tickers, exchanges, first, last in rows:
        out[cik] = {"names": [n for n in [name, *(former or [])] if n],
                    "all_names": [n for n in [name, *(former or []), *form4_names.get(cik, [])]
                                  if n],
                    "filer_type": filer_type, "tickers": tickers or [], "exchanges": exchanges
                    or [], "first": first, "last": last}  # fmt: skip
    return out


def build_candidates(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["ref.company", "ref.ticker_history", "stg_yahoo.price", "stg_tiingo.price",
                     "stg_tiingo.meta", "stg_tiingo.listing", "stg_tiingo.search",
                     "stg_sec_tickers.snapshot"], "core.price_candidate")  # fmt: skip
    settings = sources(p)
    exchanges = set(settings["tiingo"]["us_exchanges"])
    companies = _companies(con)
    ystats = {t: (a, b, n) for t, a, b, n in con.execute(
        "select ticker, min(session), max(session), count(distinct session) from stg_yahoo.price "
        "where close is not null group by 1").fetchall()}  # fmt: skip
    tstats = {t: (a, b, n) for t, a, b, n in con.execute(
        "select ticker, min(session), max(session), count(distinct session) from stg_tiingo.price "
        "where close is not null group by 1").fetchall()}  # fmt: skip
    meta = {t: (n, a, b) for t, n, a, b in con.execute(
        "select ticker, name, start_date, end_date from stg_tiingo.meta").fetchall()}  # fmt: skip
    listing: dict[str, list[tuple]] = {}
    for t, ex, a, b in con.execute(
        "select ticker, exchange, start_date, end_date from stg_tiingo.listing "
        "where asset_type = 'Stock' and currency = 'USD'"
    ).fetchall():
        if ex in exchanges and (n := normalise(t)):
            listing.setdefault(n, []).append((a, b, ex))
    form4 = {}
    for cik, t, a, b in con.execute(
        "select cik, ticker, valid_from, valid_to from ref.ticker_history where evidence = 'form4'"
    ).fetchall():
        form4.setdefault(cik, []).append((t, a, b))
    hits: dict[str, list[str]] = {}
    for q, t, kind in con.execute(
        "select query, ticker, asset_type from stg_tiingo.search order by query, hit_rank"
    ).fetchall():
        if kind == "Stock" and (n := normalise(t)):
            hits.setdefault(q.lower(), []).append(n)
    list_day = (
        con.execute("select max(snapshot_date) from stg_sec_tickers.snapshot").fetchone()[0]
        or FAR_PAST
    )  # no list: no company is listed
    rows = []
    for cik, c in companies.items():
        first = c["first"] or FAR_PAST
        last = c["last"] or FAR_FUTURE
        span = (first, last)

        def add(source, ticker, role, ev_from, ev_to, overlap=None, cik=cik, c=c, span=span):
            stats = (ystats if source == "yahoo" else tstats).get(ticker, (None, None, 0))
            if source == "yahoo":
                ident = "not_checked"
            elif role == "tiingo_listed":
                ident = listed_identity(stats, list_day)
            else:
                ident = identity(meta.get(ticker), c["all_names"], span)
            if ident == "ok" and not stats[2]:
                ident = "no_data"
            start = listing_start(listing.get(ticker, []), list_day) if ev_to is None else None
            rows.append((cik, source, ticker, role, ev_from, ev_to, *stats, ident, overlap, start))

        if c["tickers"]:  # listed today
            for rank, t in enumerate(c["tickers"]):
                t = normalise(t)
                if t and t in ystats:
                    add("yahoo", t, "yahoo" if rank == 0 else "yahoo_other", first, None)
                if t and t in tstats:
                    add("tiingo", t, "tiingo_listed", first, None)
            continue
        best = None  # disappeared: Form 4 tickers first, else the name search
        for t, vf, vt in form4.get(cik, []):
            for cand in (t, f"{t}Q"):
                for a, b, _ex in listing.get(cand, []):
                    ov = (min(vt, b or FAR_FUTURE) - max(vf, a or FAR_PAST)).days
                    if ov >= 0 and (best is None or ov > best[0]):
                        best = (ov, cand, "tiingo_form4", vf, vt)
        if best is None:
            for q in search_queries(c["names"]):
                for t in hits.get(q.lower(), []):
                    for a, b, _ex in listing.get(t, []):
                        ov = (min(last, b or FAR_FUTURE) - max(first, a or FAR_PAST)).days
                        if ov >= 0 and (best is None or ov > best[0]):
                            best = (ov, t, "tiingo_search", first, last)
        if best is not None:
            add("tiingo", best[1], best[2], best[3], best[4], best[0])
    with db.transaction(con):
        con.execute(
            "create or replace table core.price_candidate (cik VARCHAR, source VARCHAR, "
            "ticker VARCHAR, role VARCHAR, evidence_from DATE, evidence_to DATE, "
            "first_session DATE, last_session DATE, n_sessions INTEGER, identity VARCHAR, "
            "overlap_days INTEGER, listing_start DATE)"
        )
        if rows:
            con.executemany(
                "insert into core.price_candidate values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    n = db.count(con, "core.price_candidate")
    echo(f"  price candidates: {n:,} for {len(companies):,} companies")
    return {"candidate": n, "companies": len(companies)}


def choose(candidates: list[tuple], first_seen: date | None, listed: bool, start: date) -> tuple:
    """(source, ticker, reason) for one company from its candidates
    (source, ticker, role, first_session, n_sessions, identity)."""
    need = max(start, (first_seen or start) - timedelta(days=WARMUP_DAYS))
    y = next((c for c in candidates if c[0] == "yahoo" and c[2] == "yahoo" and c[4]), None)
    t = next((c for c in candidates if c[0] == "tiingo" and c[5] == "ok"), None)
    if listed:
        if y and y[3] <= need + timedelta(days=LATE_DAYS):
            return ("yahoo", y[1], "yahoo_primary")
        if t and not y:
            return ("tiingo", t[1], "yahoo_missing→tiingo")
        if t and t[3] is not None and t[3] < y[3]:
            return ("tiingo", t[1], "yahoo_starts_late→tiingo")
        if y:
            return ("yahoo", y[1], "yahoo_primary_late")
        return (None, None, "no_price")
    if t:
        return ("tiingo", t[1], "tiingo_resolved")
    rejected = next((c for c in candidates if c[0] == "tiingo"), None)
    return (None, None, f"rejected_{rejected[5]}" if rejected else "no_ticker_found")


def _other_use_ends(con) -> dict[tuple[str, str], date]:
    """(cik, ticker) → the last day another company used the ticker before (closed spans of
    `ref.ticker_history`, from Form 4 symbols and the SEC's lists)."""
    rows = con.execute(
        """
        select a.cik, a.ticker, max(b.valid_to) from ref.ticker_history a
        join ref.ticker_history b on b.ticker = a.ticker and b.cik <> a.cik
             and b.valid_to is not null
        group by 1, 2
        """
    ).fetchall()
    return {(cik, ticker): end for cik, ticker, end in rows}


def build_choice(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.price_candidate", "ref.ticker_history"], "core.price_choice")
    start = sources(p)["prices"]["history_start"]
    companies = _companies(con)
    by_cik: dict[str, list[tuple]] = {}
    listing: dict[tuple[str, str, str], date | None] = {}
    for cik, source, ticker, role, first, n, ident, list_start in con.execute(
        "select cik, source, ticker, role, first_session, n_sessions, identity, listing_start "
        "from core.price_candidate order by cik, source desc, role"
    ).fetchall():
        by_cik.setdefault(cik, []).append((source, ticker, role, first, n, ident))
        listing[(cik, source, ticker)] = list_start or first
    others = _other_use_ends(con)
    rows = []
    for cik, c in companies.items():
        source, ticker, reason = choose(by_cik.get(cik, []), c["first"], bool(c["tickers"]), start)
        if c["tickers"]:  # listed today: back to the ticker's current listing (research R12)
            bounds = [start, listing.get((cik, source, ticker)) or start]
            if (cik, ticker) in others:
                bounds.append(others[(cik, ticker)] + timedelta(days=1))
            trim_from, trim_to = max(bounds), None
        else:
            first = c["first"] or start
            trim_from = max(start, first - timedelta(days=WARMUP_DAYS))
            trim_to = c["last"] + timedelta(days=TAIL_DAYS) if c["last"] else None
        rows.append((cik, source, ticker, reason, trim_from, trim_to, bool(c["tickers"])))
    with db.transaction(con):
        con.execute(
            "create or replace table core.price_choice (cik VARCHAR, source VARCHAR, "
            "ticker VARCHAR, reason VARCHAR, trim_from DATE, trim_to DATE, listed BOOLEAN)"
        )
        con.executemany("insert into core.price_choice values (?, ?, ?, ?, ?, ?, ?)", rows)
    counts = dict(
        con.execute("select reason, count(*) from core.price_choice group by 1").fetchall()
    )
    echo(f"  price choice: {counts}")
    return {"companies": len(rows), "priced": sum(1 for r in rows if r[1])}


def _significant(expr: str, digits: int = 10) -> str:
    """Round to `digits` significant digits, so a rerun gives identical values (v1)."""
    return (f"case when ({expr}) is null or ({expr}) = 0 then ({expr}) else round(({expr}), "
            f"{digits} - 1 - cast(floor(log10(abs({expr}))) as INTEGER)) end")  # fmt: skip


def build_daily(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.price_choice", "ref.calendar"], "core.price_daily")
    glitch = risk_params(p)["prices"]["glitch"]
    con.execute(
        """
        create or replace temp table _rows as
        with provider as (
            select 'yahoo' as source, ticker, session, open, high, low, close, volume, adj_close,
                   coalesce(dividend, 0) as dividend,
                   case when coalesce(split_ratio, 0) = 0 then 1.0 else split_ratio end
                       as split_ratio, true as split_adjusted
            from stg_yahoo.price where close is not null
            qualify row_number() over (partition by ticker, session order by raw_file desc,
                                       close) = 1
            union all
            select 'tiingo', ticker, session, open, high, low, close, volume, adj_close,
                   coalesce(dividend, 0), coalesce(split_factor, 1.0), false
            from stg_tiingo.price where close is not null
            qualify row_number() over (partition by ticker, session order by raw_file desc,
                                       close) = 1
        )
        select c.cik, r.* from provider r
        join core.price_choice c on c.source = r.source and c.ticker = r.ticker
        where r.session >= c.trim_from and (c.trim_to is null or r.session <= c.trim_to)
        """
    )
    with db.transaction(con):
        con.execute(
            """
            create or replace table core.price_issue as
            select cik, source, ticker, session,
                   case when close <= 0 then 'nonpositive_close'
                        when high < low then 'high_below_low' else 'not_a_session' end as issue
            from _rows
            where close <= 0 or high < low or session not in (select session from ref.calendar)
            """
        )
        con.execute(
            f"""
            create or replace table core.price_daily as
            with valid as (
                select *, coalesce(exp(cast(sum(cast(ln(
                               case when split_ratio > 0 then split_ratio else 1.0 end
                           ) as DECIMAL(38, 18))) over (partition by cik order by session
                               rows between 1 following and unbounded following) as DOUBLE)),
                           1.0) as cum
                from _rows
                where close > 0 and not coalesce(high < low, false)
                  and session in (select session from ref.calendar)
            ),
            traded as (
                select cik, session, source, ticker,
                       case when split_adjusted then {_significant("open * cum")} else open end
                           as open,
                       case when split_adjusted then {_significant("high * cum")} else high end
                           as high,
                       case when split_adjusted then {_significant("low * cum")} else low end
                           as low,
                       case when split_adjusted then {_significant("close * cum")} else close end
                           as close,
                       case when split_adjusted then round(volume / cum, 2) else volume end
                           as volume,
                       adj_close, {_significant("cum")} as cum_split_after, split_ratio, dividend
                from valid
            ),
            moves as (
                select *, adj_close / lag(adj_close) over w - 1 as r,
                       lead(adj_close) over w / adj_close - 1 as r_next
                from traded window w as (partition by cik order by session)
            )
            select cik, session, source, ticker, open, high, low, close, volume, adj_close,
                   cum_split_after, split_ratio, dividend, close * volume as dollar_volume,
                   coalesce((r > $up and r_next < -$up_reversal)
                            or (r < -$down and r_next > $down_reversal), false) as glitch
            from moves
            order by cik, session
            """,
            glitch,
        )
    counts = dict(zip(["rows", "companies", "glitches"], con.execute(
        "select count(*), count(distinct cik), count(*) filter (where glitch) "
        "from core.price_daily").fetchone(), strict=True))  # fmt: skip
    counts["issues"] = db.count(con, "core.price_issue")
    echo(f"  daily prices: {counts}")
    return counts


def build_check(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """Yahoo against Tiingo for listed companies with both: the share of shared days whose daily
    returns differ by more than 2 points (agree: at most 2%; mismatch: at least 10%; v1's rule)."""
    db.require(con, ["core.price_candidate", "core.price_choice"], "core.price_check")
    with db.transaction(con):
        con.execute(
            """
            create or replace table core.price_check as
            with pairs as (
                select y.cik, y.ticker as yahoo_ticker, t.ticker as tiingo_ticker
                from core.price_candidate y join core.price_candidate t using (cik)
                where y.source = 'yahoo' and y.role = 'yahoo' and t.source = 'tiingo'
                  and t.role = 'tiingo_listed'
            ),
            yr as (select ticker, session, adj_close / lag(adj_close) over (partition by ticker
                          order by session) - 1 as r from stg_yahoo.price
                   where ticker in (select yahoo_ticker from pairs) and adj_close > 0),
            tr as (select ticker, session, adj_close / lag(adj_close) over (partition by ticker
                          order by session) - 1 as r from stg_tiingo.price
                   where ticker in (select tiingo_ticker from pairs) and adj_close > 0),
            joined as (
                select p.cik, p.yahoo_ticker, p.tiingo_ticker, abs(yr.r - tr.r) > 0.02 as differ
                from pairs p join yr on yr.ticker = p.yahoo_ticker
                join tr on tr.ticker = p.tiingo_ticker and tr.session = yr.session
                where yr.r is not null and tr.r is not null
            )
            select cik, yahoo_ticker, tiingo_ticker, count(*) as shared_days,
                   count(*) filter (where differ) as differ_days,
                   count(*) filter (where differ) / count(*) as differ_share,
                   case when count(*) < 20 then 'too_few_days'
                        when count(*) filter (where differ) / count(*) <= 0.02 then 'agree'
                        when count(*) filter (where differ) / count(*) >= 0.10 then 'mismatch'
                        else 'partly' end as verdict
            from joined group by 1, 2, 3
            """
        )
    counts = dict(
        con.execute("select verdict, count(*) from core.price_check group by 1").fetchall()
    )
    echo(f"  Yahoo-Tiingo check: {counts}")
    return counts


def build_security(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """`ref.security`: one traded line per priced company (its chosen series), with its span and
    coverage level: `full` (US filer), `foreign` (20-F or 40-F filer), `price_only` (files
    nothing periodic with the SEC). Market value needs share counts of the same line, so a foreign
    filer's line, often an ADR whose ratio is unknown, gets none (`market_value_known`)."""
    db.require(con, ["core.price_daily", "ref.company"], "ref.security")
    with db.transaction(con):
        con.execute(
            """
            create or replace table ref.security as
            select d.cik as security_id, d.cik, ch.ticker, ch.source, ch.listed,
                   min(d.session) as first_session, max(d.session) as last_session,
                   count(*) as n_sessions,
                   case c.filer_type when 'us' then 'full' when 'foreign' then 'foreign'
                        else 'price_only' end as coverage,
                   c.filer_type = 'us' as market_value_known
            from core.price_daily d
            join core.price_choice ch using (cik) join ref.company c using (cik)
            group by d.cik, ch.ticker, ch.source, ch.listed, c.filer_type
            """
        )
    counts = dict(con.execute("select coverage, count(*) from ref.security group by 1").fetchall())
    echo(f"  securities: {counts}")
    return counts


def build_coverage(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """`core.price_coverage`: one row per listed company (funds and blank-check companies left
    out, as the spec does): its price source, or why it has none; where its prices start; and
    whether only Tiingo prices it (those stop updating when the paid plan ends)."""
    db.require(con, ["ref.company", "ref.security", "core.price_choice", "core.price_candidate",
                     "ref.calendar"], "core.price_coverage")  # fmt: skip
    with db.transaction(con):
        con.execute(
            """
            create or replace table core.price_coverage as
            with listed as (
                select cik, tickers[1] as ticker, filer_type from ref.company
                where tickers is not null and not is_fund and not is_blank_check
            ),
            cand as (
                select cik, bool_or(n_sessions > 0) as any_data,
                       bool_or(source = 'yahoo' and n_sessions > 0) as yahoo_data,
                       min(first_session) filter (where n_sessions > 0) as first_data,
                       min(identity) filter (where source = 'tiingo'
                                             and identity not in ('ok', 'no_data')) as rejected
                from core.price_candidate group by cik
            )
            select l.cik, l.ticker, l.filer_type, coalesce(s.source, 'none') as source,
                   case when s.security_id is not null then 'priced'
                        when not coalesce(c.any_data, false) then 'no data in any source'
                        when c.first_data > (select max(session) from ref.calendar)
                            then 'listed after the calendar''s end'
                        when c.rejected is not null then 'rejected: ' || c.rejected
                        else 'not chosen: ' || ch.reason end as reason,
                   s.first_session as priced_from,
                   coalesce(s.source = 'tiingo' and not c.yahoo_data, false) as tiingo_only
            from listed l
            left join ref.security s on s.security_id = l.cik
            left join cand c on c.cik = l.cik
            left join core.price_choice ch on ch.cik = l.cik
            order by l.cik
            """
        )
    counts = dict(
        con.execute(
            "select reason, count(*) from core.price_coverage group by 1 order by 2 desc"
        ).fetchall()
    )
    tiingo_only = con.execute(
        "select count(*) from core.price_coverage where tiingo_only"
    ).fetchone()[0]
    echo(f"  price coverage of listed companies: {counts}; Tiingo only: {tiingo_only:,}")
    return {"listed": sum(counts.values()), "priced": counts.get("priced", 0),
            "tiingo_only": tiingo_only}  # fmt: skip
