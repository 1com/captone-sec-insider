"""Price histories as chains of segments (feature 027; research of `specs/027-*`).

`build_choice` (prices.py) picks each company's main series as before; this module turns it into
the company's history, for every company at once, in set-based passes:

1. **Cuts** of a segment: after the last use of the ticker by a company that used it before the
   company's own first use (an earlier holder, R4), unless the series' daily moves there are not
   that company's own (the provider re-filed the history under the new holder: Gardner Denver's
   under IR); before a hole of over a year that the company's own evidence does not cover (R6);
   through every blank-check (SPAC) period (R7, V2-66).
2. **Joins** (R2, R3): where a company's earliest segment starts late, its own other tickers are
   tried; a series that ends at most `SWITCH_DAYS` before the segment starts, within a factor of
   `LEVEL` of its first as-traded price (a split recorded at the switch allowed for), whose
   provider's name is the company's (or whose ticker the SEC listed for it), becomes an earlier
   segment and is cut in turn. A disappeared company's latest segment is joined forward the same
   way. At most `MAX_SEGMENTS` segments.
3. **One ticker-day, one company** (R5): two companies claiming the same series over overlapping
   days: the one the SEC's list names for the ticker keeps them, else the one with more own Form 4
   filings printing it during the overlap, else the lower CIK.
4. **Adjustment factors** (R10): each earlier segment's adjusted prices are scaled so the adjusted
   return across a switch equals the as-traded move.

Every decision is a row of `core.price_decision`.
"""

import math
from datetime import date, timedelta

import duckdb

GAP_DAYS = 365  # a hole longer than this ends the earlier part (R6)
WARMUP_DAYS, TAIL_DAYS = 400, 90  # own evidence covers this long before and after (prices.py)
SWITCH_DAYS = 15  # the old series must end at most about 10 trading days before the new one
LEVEL = 1.5  # ... within this factor of its as-traded price (R3)
MAX_SEGMENTS = 5
LATE_START_DAYS = 30  # a segment starting this long after the history start is tried for a join
MOVES_DIFFER = 0.02  # two daily returns differ when they are more than 2 points apart
SAME_SERIES = 0.05  # at most this share of shared days differ: the same prices (one company's)
MIN_SHARED = 20  # fewer shared days: cut, as before
OVERLAP_DAYS, MIN_OVERLAP = 90, 10  # two tickers' series that overlap near a switch (R3)
# R7 (V2-66): a former name of a blank-check company, as whole words; it counts when it lasted at
# most SPAC_YEARS or the price sat between $9 and $11 on at least SPAC_NEAR_10 of its days
SPAC_NAME = (r"\b(ACQUISITIONS?|MERGER)\s+(CORP|CORPORATION|CO|COMPANY|INC|LTD|LIMITED|HOLDINGS?"
             r"|GROUP|TRUST)\b|\bSPAC\b|\bBLANK\s+CHECK\b")  # fmt: skip
SPAC_YEARS = 3.5
SPAC_NEAR_10 = 0.5
FAR = date(2100, 1, 1)
FAR_SQL = "DATE '2100-01-01'"

PROVIDER = """
    create or replace temp view _prov as
    select 'yahoo' as source, ticker, session, close, adj_close,
           case when coalesce(split_ratio, 0) = 0 then 1.0 else split_ratio end as split
    from stg_yahoo.price where close > 0
    union all
    select 'tiingo', ticker, session, close, adj_close, coalesce(split_factor, 1.0)
    from stg_tiingo.price where close > 0
"""


def _decide(decisions: list, cik, kind, ticker, source, day_from, day_to, other=None, detail=""):
    decisions.append((cik, kind, ticker, source, day_from, day_to, other, detail))


# --- evidence ----------------------------------------------------------------------------------


def setup(con: duckdb.DuckDBPyConnection, today: date) -> None:
    """Temporary tables every pass reads: provider rows, own evidence and its coverage, Form 4
    counts, blank-check periods."""
    con.execute(PROVIDER)
    con.execute(
        """
        create or replace temp table _own as
        select cik, ticker, min(valid_from) as first_use from ref.ticker_history group by 1, 2
        """
    )
    con.execute(
        f"""
        create or replace temp table _cover as   -- own evidence widened as prices.py does
        select cik, ticker,
               case when evidence = 'form4' then valid_from - interval {WARMUP_DAYS} day
                    else valid_from end :: DATE as c0,
               case when evidence = 'form4' then valid_to + interval {TAIL_DAYS} day
                    else coalesce(valid_to, DATE '{today}') end :: DATE as c1
        from ref.ticker_history
        """
    )
    con.execute(
        f"""
        create or replace temp table _spac_name as
        select c.cik, f.name as former_name, try_cast(f.valid_from as DATE) as valid_from,
               try_cast(f.valid_to as DATE) as valid_to
        from ref.company c, unnest(coalesce(c.former_names, [])) u(f)
        where regexp_matches(upper(f.name), '{SPAC_NAME}')
          and try_cast(f.valid_to as DATE) is not null
        """
    )


def spac_periods(con, main: list[tuple]) -> list[tuple]:
    """`core.blank_check_period` rows: each SPAC-like former name with its length and its share
    of priced days between $9 and $11 on the company's main series; `counted` per R7."""
    con.execute("create or replace temp table _main (cik VARCHAR, source VARCHAR, ticker VARCHAR)")
    con.executemany("insert into _main values (?, ?, ?)", [m[:3] for m in main if m[1]])
    con.execute(
        """
        create or replace temp table _traded as   -- as-traded closes of the companies' series
        with own as (   -- the main series and every series of the company's own tickers
            select cik, source, ticker from _main where cik in (select cik from _spac_name)
            union
            select h.cik, x.source, h.ticker from ref.ticker_history h
            join (select distinct source, ticker from _prov) x on x.ticker = h.ticker
            where h.cik in (select cik from _spac_name))
        select o.cik, p.session,
               p.close * case when p.source = 'yahoo' then coalesce(exp(sum(ln(p.split)) over (
                   partition by o.cik, o.source, o.ticker order by p.session
                   rows between 1 following and unbounded following)), 1.0) else 1.0 end
                   as traded
        from own o join _prov p on p.source = o.source and p.ticker = o.ticker
        """
    )
    return con.execute(
        """
        select s.cik, s.former_name, s.valid_from, s.valid_to,
               round(datediff('day', s.valid_from, s.valid_to) / 365.25, 2) as years,
               (select avg(case when p.traded between 9 and 11 then 1.0 else 0.0 end)
                from _traded p where p.cik = s.cik
                and p.session between s.valid_from and s.valid_to) as near_10
        from _spac_name s
        order by s.cik, s.valid_from, s.former_name
        """
    ).fetchall()


def counted(years: float, near_10: float | None) -> bool:
    return years <= SPAC_YEARS or (near_10 is not None and near_10 >= SPAC_NEAR_10)


# --- pass 1: cuts ------------------------------------------------------------------------------


def cut(con, segs: list[dict], spac: dict[str, list[tuple]], decisions: list) -> None:
    """Raise each segment's `lo` by the reuse, hole and blank-check rules (in place)."""
    if not segs:
        return
    con.execute(
        "create or replace temp table _todo (sid INTEGER, cik VARCHAR, source VARCHAR, "
        "ticker VARCHAR, lo DATE, hi DATE)"
    )
    con.executemany(
        "insert into _todo values (?, ?, ?, ?, ?, ?)",
        [(i, s["cik"], s["source"], s["ticker"], s["lo"], s["hi"]) for i, s in enumerate(segs)],
    )
    # reuse: a company that used the ticker before this company's own first use is an earlier
    # holder: the history starts after its last use (Old Safehold before the new one, even with a
    # few days of overlap at the handover); one that began using it after is a sister company or a
    # typo and cuts nothing (Digital Realty's partnership; DoorDash's "FN": V2-63, widened)
    rows = con.execute(
        f"""
        with uses as (
            select t.sid, b.cik as other, b.valid_from, b.valid_to, o.first_use
            from _todo t join ref.ticker_history b on b.ticker = t.ticker and b.cik <> t.cik
                 and b.valid_to is not null and b.valid_to >= t.lo
                 and b.valid_from <= coalesce(t.hi, DATE '2100-01-01')
            left join _own o on o.cik = t.cik and o.ticker = t.ticker
        )
        select sid,
               arg_max(other, valid_to) filter (where valid_from < coalesce(first_use, {FAR_SQL})),
               max(valid_to) filter (where valid_from < coalesce(first_use, {FAR_SQL})),
               arg_max(other, valid_to) filter (where valid_from >= coalesce(first_use, {FAR_SQL})),
               max(valid_to) filter (where valid_from >= coalesce(first_use, {FAR_SQL}))
        from uses group by 1
        """
    ).fetchall()
    reuse = {}
    for sid, other, end, o_other, o_end in rows:
        s = segs[sid]
        if o_other is not None:
            _decide(decisions, s["cik"], "kept_overlap", s["ticker"], s["source"], s["lo"], o_end,
                    o_other, "another company began using the ticker after this "
                    "one did")  # fmt: skip
        if other is not None:
            reuse[sid] = (other, end)
    if reuse:
        _cut_reuse(con, segs, reuse, decisions)
    _cut_holes(con, segs, decisions)
    for s in segs:  # blank-check days (R7)
        for name, v0, v1 in spac.get(s["cik"], []):
            if v1 >= s["lo"] and v0 <= (s["hi"] or FAR):
                _decide(decisions, s["cik"], "cut_blank_check", s["ticker"], s["source"], s["lo"],
                        v1, None, name)  # fmt: skip
                s["lo"] = v1 + timedelta(days=1)


def compare(con, items: list[tuple]) -> dict:
    """key → (shared days, days whose daily returns differ by more than `MOVES_DIFFER`) for each
    (key, source a, ticker a, source b, ticker b, from, to): are two series the same prices?"""
    if not items:
        return {}
    con.execute(
        "create or replace temp table _cmp (k INTEGER, sa VARCHAR, ta VARCHAR, sb VARCHAR, "
        "tb VARCHAR, lo DATE, hi DATE)"
    )
    con.executemany("insert into _cmp values (?, ?, ?, ?, ?, ?, ?)", items)
    return dict(
        (k, (n, d))
        for k, n, d in con.execute(
            f"""
            with a as (
                select c.k, x.session, x.adj_close as pa
                from _cmp c join _prov x on x.source = c.sa and x.ticker = c.ta
                     and x.session between c.lo and c.hi),
            b as (
                select c.k, x.session, x.adj_close as pb
                from _cmp c join _prov x on x.source = c.sb and x.ticker = c.tb
                     and x.session between c.lo and c.hi),
            r as (   -- returns over the days both series have, so a skipped day misleads neither
                select k, pa / lag(pa) over w - 1 as ra, pb / lag(pb) over w - 1 as rb
                from a join b using (k, session)
                window w as (partition by k order by session))
            select k, count(*), count(*) filter (where abs(ra - rb) > {MOVES_DIFFER})
            from r where ra is not null and rb is not null
            group by 1
            """
        ).fetchall()
    )


def _cut_reuse(con, segs, reuse: dict, decisions: list) -> None:
    """Cut after another company's last use, unless the series' daily moves there differ from
    that company's own series (the provider re-filed the history under the new holder)."""
    others = dict(
        ((c, (s, t)) for c, s, t in con.execute("select cik, source, ticker from _main").fetchall())
    )
    items = []
    for sid, (other, end) in reuse.items():
        osource, oticker = others.get(other) or (None, None)
        if osource:
            x = segs[sid]
            items.append((sid, x["source"], x["ticker"], osource, oticker, x["lo"], end))
    differ = compare(con, items)
    steady = _continuous(con, segs, reuse, differ)
    for sid, (other, end) in reuse.items():
        x = segs[sid]
        shared, diff = differ.get(sid, (0, 0))
        if shared >= MIN_SHARED and diff / shared > SAME_SERIES:
            _decide(decisions, x["cik"], "kept_remapped", x["ticker"], x["source"], x["lo"], end,
                    other, f"daily moves differ from the other company's on {diff} of "
                           f"{shared} days")  # fmt: skip
            continue
        if sid in steady:
            _decide(decisions, x["cik"], "kept_continuous", x["ticker"], x["source"], x["lo"],
                    end, other, "the series trades on across the other company's last use while "
                    "this company's own filings under another ticker show it then")  # fmt: skip
            continue
        _decide(decisions, x["cik"], "cut_reuse", x["ticker"], x["source"], x["lo"], end, other,
                f"another company used the ticker until {end}")  # fmt: skip
        x["lo"] = max(x["lo"], end + timedelta(days=1))


def _continuous(con, segs, reuse: dict, differ: dict) -> set[int]:
    """Segments whose earlier holder could not be compared (no prices of its own) but whose
    series trades on across that holder's last use (no gap over `SWITCH_DAYS`, no jump over
    `LEVEL`) while the company's own filings under another ticker cover that day: the provider
    filed the company's own history under its new ticker (Gen Digital's GEN holds NortonLifeLock's
    prices; Genesis Healthcare, GEN's earlier holder, has none)."""
    todo = [(sid, segs[sid]["cik"], segs[sid]["source"], segs[sid]["ticker"], end)
            for sid, (_, end) in reuse.items()
            if differ.get(sid, (0, 0))[0] < MIN_SHARED]  # fmt: skip
    if not todo:
        return set()
    con.execute(
        "create or replace temp table _cont (sid INTEGER, cik VARCHAR, source VARCHAR, "
        "ticker VARCHAR, day DATE)"
    )
    con.executemany("insert into _cont values (?, ?, ?, ?, ?)", todo)
    rows = con.execute(
        f"""
        with around as (
            select t.sid, arg_max(x.close, x.session) filter (where x.session <= t.day) as c0,
                   max(x.session) filter (where x.session <= t.day) as d0,
                   arg_min(x.close, x.session) filter (where x.session > t.day) as c1,
                   min(x.session) filter (where x.session > t.day) as d1
            from _cont t join _prov x on x.source = t.source and x.ticker = t.ticker
                 and x.session between t.day - interval {SWITCH_DAYS} day
                 and t.day + interval {SWITCH_DAYS} day
            group by 1)
        select a.sid from around a join _cont t using (sid)
        where a.d0 is not null and a.d1 is not null
          and datediff('day', a.d0, a.d1) <= {SWITCH_DAYS}
          and a.c0 > 0 and a.c1 > 0 and abs(ln(a.c1 / a.c0)) <= ln({LEVEL})
          and exists (select 1 from _cover c where c.cik = t.cik and c.ticker <> t.ticker
                      and c.c0 <= t.day and c.c1 >= t.day)
        """
    ).fetchall()
    return {sid for (sid,) in rows}


def _cut_holes(con, segs, decisions: list) -> None:
    con.execute("delete from _todo")
    con.executemany(
        "insert into _todo values (?, ?, ?, ?, ?, ?)",
        [(i, s["cik"], s["source"], s["ticker"], s["lo"], s["hi"]) for i, s in enumerate(segs)],
    )
    rows = con.execute(
        f"""
        with days as (
            select t.sid, x.session,
                   lag(x.session) over (partition by t.sid order by x.session) as before
            from _todo t join _prov x on x.source = t.source and x.ticker = t.ticker
                 and x.session >= t.lo and x.session <= coalesce(t.hi, DATE '2100-01-01')),
        holes as (select sid, before, session as after from days
                  where datediff('day', before, session) > {GAP_DAYS})
        select h.sid, max(h.after), arg_max(h.before, h.after)
        from holes h join _todo t using (sid)
        where not exists (select 1 from _cover c where c.cik = t.cik and c.ticker = t.ticker
                          and c.c0 <= h.before and c.c1 >= t.lo)
        group by 1
        """
    ).fetchall()
    for sid, after, before in rows:
        s = segs[sid]
        _decide(decisions, s["cik"], "cut_hole", s["ticker"], s["source"], s["lo"], before, None,
                f"no prices from {before} to {after}; no own evidence before")  # fmt: skip
        s["lo"] = max(s["lo"], after)


# --- pass 2: joins -----------------------------------------------------------------------------


def _as_traded(con, rows: list[tuple]) -> dict:
    """(source, ticker, day) → (as-traded close, adjusted ÷ as-traded, split on the day): Yahoo's
    closes are split-adjusted, so later splits of the same series are undone."""
    if not rows:
        return {}
    con.execute("create or replace temp table _pt (source VARCHAR, ticker VARCHAR, day DATE)")
    con.executemany("insert into _pt values (?, ?, ?)", rows)
    out = con.execute(
        """
        select p.source, p.ticker, p.day,
               x.close * case when p.source = 'yahoo' then coalesce((
                   select exp(sum(ln(y.split))) from _prov y where y.source = p.source
                   and y.ticker = p.ticker and y.session > p.day and y.split > 0), 1.0)
                   else 1.0 end as traded,
               x.adj_close, x.split
        from _pt p join _prov x on x.source = p.source and x.ticker = p.ticker
             and x.session = p.day
        """
    ).fetchall()
    return {(s, t, d): (c, (a / c) if c and a else 1.0, sp) for s, t, d, c, a, sp in out}


def edges(con, segs: list[dict]) -> None:
    """Each segment's first and last provider day within its bounds (`first`, `last`), in one
    query; a segment without a day gets None."""
    con.execute(
        "create or replace temp table _e (sid INTEGER, source VARCHAR, ticker VARCHAR, lo DATE, "
        "hi DATE)"
    )
    con.executemany(
        "insert into _e values (?, ?, ?, ?, ?)",
        [(i, x["source"], x["ticker"], x["lo"], x["hi"]) for i, x in enumerate(segs)],
    )
    got = dict(
        (sid, (a, b))
        for sid, a, b in con.execute(
            """
            select e.sid, min(x.session), max(x.session) from _e e
            join _prov x on x.source = e.source and x.ticker = e.ticker
                 and x.session >= e.lo and x.session <= coalesce(e.hi, DATE '2100-01-01')
            group by 1
            """
        ).fetchall()
    )
    for i, x in enumerate(segs):
        x["first"], x["last"] = got.get(i, (None, None))


def join(con, segs_by_cik: dict[str, list[dict]], names: dict, meta: dict, identity,
         spac: dict, start: date, decisions: list) -> int:  # fmt: skip
    """One round of backward joins (and forward joins for disappeared companies); returns how many
    segments were added. Segments carry `first` and `last` (`edges`)."""
    wanted = []  # (cik, direction, segment, boundary day: the segment's own first or last day)
    for cik, segs in segs_by_cik.items():
        if len(segs) >= MAX_SEGMENTS:
            continue
        first, last = segs[0], segs[-1]
        if (
            first["first"]
            and first["first"] > start + timedelta(days=LATE_START_DAYS)
            and not first.get("no_back")
        ):
            wanted.append((cik, "back", first, first["first"]))
        if (
            not last["in_list"]
            and last["last"]
            and last["hi"]
            and not last.get("no_fwd")
            and last["last"] < last["hi"] - timedelta(days=LATE_START_DAYS)
        ):
            wanted.append((cik, "forward", last, last["last"]))  # fmt: skip
    if not wanted:
        return 0
    con.execute(
        "create or replace temp table _want (wid INTEGER, cik VARCHAR, dir VARCHAR, day DATE, "
        "ticker VARCHAR)"
    )
    con.executemany(
        "insert into _want values (?, ?, ?, ?, ?)",
        [(i, c, d, b, s["ticker"]) for i, (c, d, s, b) in enumerate(wanted)],
    )
    used = {(c, x["ticker"]) for c, segs in segs_by_cik.items() for x in segs}
    cands = con.execute(
        f"""
        with own as (
            select w.wid, h.ticker, min(h.valid_from) vf,
                   max(coalesce(h.valid_to, DATE '2100-01-01')) vt,
                   bool_or(h.evidence = 'sec_list') as listed_for_it
            from _want w join ref.ticker_history h on h.cik = w.cik and h.ticker <> w.ticker
            group by 1, 2),
        fit as (
            select o.* from own o join _want w using (wid)
            where (w.dir = 'back' and o.vf < w.day - interval {LATE_START_DAYS} day
                   and o.vt >= w.day - interval {WARMUP_DAYS} day)
               or (w.dir = 'forward' and o.vt > w.day + interval {LATE_START_DAYS} day))
        select f.wid, f.ticker, x.source, f.listed_for_it,
               case when w.dir = 'back' then max(x.session) filter (where x.session < w.day)
                    else min(x.session) filter (where x.session > w.day) end as edge,
               min(x.session) as s0, max(x.session) as s1
        from fit f join _want w using (wid) join _prov x on x.ticker = f.ticker
        group by 1, 2, 3, 4, w.dir
        having edge is not null
        order by 1, 2, 3
        """
    ).fetchall()
    points = {(src, t, edge) for _, t, src, _, edge, _, _ in cands}
    points |= {(x["source"], x["ticker"], day) for _, _, x, day in wanted}
    prices = _as_traded(con, sorted(points, key=str))
    # where the two series overlap and move alike on the shared days, they are the same shares,
    # whatever the price does at the switch (Hanger's HNGR holds HGR's last NYSE weeks)
    near = timedelta(days=OVERLAP_DAYS)
    overlap = compare(con, [(i, wanted[w][2]["source"], wanted[w][2]["ticker"], src, t,
                             wanted[w][3] - near, wanted[w][3] + near)
                            for i, (w, t, src, _, _, _, _) in enumerate(cands)])  # fmt: skip
    best: dict[int, tuple] = {}
    for i, (wid, ticker, src, listed_for_it, edge, s0, s1) in enumerate(cands):
        cik, d, seg, day = wanted[wid]
        if (cik, ticker) in used:
            continue
        gap = (day - edge).days if d == "back" else (edge - day).days
        why = None
        shared, diff = overlap.get(i, (0, 0))
        if shared >= MIN_OVERLAP and diff / shared <= SAME_SERIES:
            pass  # the same shares: no level check
        elif gap > SWITCH_DAYS:
            why = f"gap: {ticker} ends {gap} days from the switch"
        else:
            theirs, mine = (
                prices.get((src, ticker, edge)),
                prices.get((seg["source"], seg["ticker"], day)),
            )
            if not theirs or not mine or not theirs[0] or not mine[0]:
                why = "level: no price at the switch"
            else:
                before, after = (theirs, mine) if d == "back" else (mine, theirs)
                ratio = before[0] / after[0]
                split = after[2] or 1.0
                if min(abs(math.log(ratio)), abs(math.log(ratio / split))) > math.log(LEVEL):
                    why = f"level: {ratio:.2f} times across the switch"
        if why is None and not (listed_for_it and src == "yahoo"):
            name = (meta.get(ticker) or (None,))[0]
            if identity((name, s0, s1), names.get(cik, []), (s0, s1)) != "ok":
                why = f"identity: {name or 'no description'} is not this company"
        if why:
            _decide(decisions, cik, "join_failed", ticker, src, s0, s1, None, why)
            continue
        rank = (gap, 0 if src == "yahoo" else 1)
        if wid not in best or rank < best[wid][0]:
            best[wid] = (rank, ticker, src, edge, s0, s1)
    added = 0
    for wid, (_, ticker, src, edge, s0, _s1) in sorted(best.items()):
        cik, d, seg, day = wanted[wid]
        if d == "back":
            new = {"cik": cik, "source": src, "ticker": ticker, "reason": "joined",
                   "lo": max(start, s0), "hi": day - timedelta(days=1), "listed": seg["listed"],
                   "in_list": seg["in_list"]}  # fmt: skip
        else:
            new = {"cik": cik, "source": src, "ticker": ticker, "reason": "joined", "lo": edge,
                   "hi": seg["hi"], "listed": seg["listed"], "in_list": False}  # fmt: skip
        cut(con, [new], spac, decisions)
        edges(con, [new])
        if new["first"] is None:
            continue
        if d == "back":
            seg["lo"] = min(seg["lo"], day)
            segs_by_cik[cik].insert(0, new)
        else:
            seg["hi"] = new["first"] - timedelta(days=1)
            segs_by_cik[cik].append(new)
        side = "before" if d == "back" else "after"
        _decide(decisions, cik, "joined", ticker, src, new["first"], new["last"], None,
                f"{side} {seg['ticker']} (switch {day})")  # fmt: skip
        used.add((cik, ticker))
        added += 1
    for _, d, seg, _ in wanted:  # asked once: a segment is not tried again in that direction
        seg["no_back" if d == "back" else "no_fwd"] = True
    return added


# --- pass 3: one ticker-day, one company -------------------------------------------------------


def resolve(con, segs_by_cik: dict[str, list[dict]], decisions: list) -> None:
    """Two companies claiming one series over overlapping days: the overlap goes to one (R5)."""
    for _ in range(5):
        flat = [s for segs in segs_by_cik.values() for s in segs if s["source"]]
        con.execute(
            "create or replace temp table _segs (sid INTEGER, cik VARCHAR, source VARCHAR, "
            "ticker VARCHAR, lo DATE, hi DATE)"
        )
        con.executemany(
            "insert into _segs values (?, ?, ?, ?, ?, ?)",
            [(i, s["cik"], s["source"], s["ticker"], s["lo"], s["hi"]) for i, s in enumerate(flat)],
        )
        pairs = con.execute(
            """
            select a.sid, b.sid, greatest(a.lo, b.lo), least(coalesce(a.hi, DATE '2100-01-01'),
                   coalesce(b.hi, DATE '2100-01-01')),
                   exists (select 1 from ref.ticker_history h where h.cik = a.cik
                           and h.ticker = a.ticker and h.evidence = 'sec_list') as a_listed,
                   exists (select 1 from ref.ticker_history h where h.cik = b.cik
                           and h.ticker = b.ticker and h.evidence = 'sec_list') as b_listed
            from _segs a join _segs b on a.ticker = b.ticker
                 and a.cik < b.cik and a.lo <= coalesce(b.hi, DATE '2100-01-01')
                 and b.lo <= coalesce(a.hi, DATE '2100-01-01')
            order by 1, 2
            """
        ).fetchall()
        # two providers' series of one ticker are the same prices only if their moves agree (a
        # provider may have re-filed another company's history under it: Chubb's CB)
        cross = [(i, flat[a]["source"], flat[a]["ticker"], flat[b]["source"], flat[b]["ticker"],
                  o0, o1) for i, (a, b, o0, o1, _, _) in enumerate(pairs)]  # fmt: skip
        moves = compare(con, cross)
        same = []
        for i, pair in enumerate(pairs):
            shared, diff = moves.get(i, (0, 0))
            if flat[pair[0]]["source"] == flat[pair[1]]["source"]:
                if shared or _has_days(con, flat[pair[0]], pair[2], pair[3]):
                    same.append(pair)
            elif shared >= MIN_SHARED and diff / shared <= SAME_SERIES:
                same.append(pair)
            elif shared < MIN_SHARED and pair[4] != pair[5]:
                same.append(pair)  # too few days to compare: the SEC-listed holder keeps them
        pairs = same
        if not pairs:
            return
        counts = _form4_counts(con, flat, pairs)
        changed = False
        for a, b, o0, o1, a_listed, b_listed in pairs:
            sa, sb = flat[a], flat[b]
            if a_listed != b_listed:
                win, lose = (sa, sb) if a_listed else (sb, sa)
            else:
                na, nb = counts.get((a, b), (0, 0))
                win, lose = (sa, sb) if na >= nb else (sb, sa)  # ties: the lower CIK (a)
            if not _trim(lose, o0, o1):
                continue
            changed = True
            _decide(decisions, lose["cik"], "lost_to", lose["ticker"], lose["source"], o0, o1,
                    win["cik"], "the same series, the other company holds the ticker")  # fmt: skip
        for cik in list(segs_by_cik):
            segs_by_cik[cik] = [s for s in segs_by_cik[cik]
                                if not s["source"] or s["lo"] <= (s["hi"] or FAR)]  # fmt: skip
        if not changed:
            return


def _has_days(con, seg: dict, o0: date, o1: date) -> bool:
    return bool(
        con.execute(
            "select count(*) from _prov where source = ? and ticker = ? "
            "and session between ? and ?",
            [seg["source"], seg["ticker"], o0, o1],
        ).fetchone()[0]
    )


def _trim(seg: dict, o0: date, o1: date) -> bool:
    """Remove [o0, o1] from the segment, keeping its larger side; False if nothing changed."""
    lo, hi = seg["lo"], seg["hi"] or FAR
    if o1 < lo or o0 > hi:
        return False
    left = (o0 - lo).days if o0 > lo else 0
    right = (hi - o1).days if o1 < hi else 0
    if left <= 0 and right <= 0:
        seg["hi"] = lo - timedelta(days=1)  # all of it: the segment empties
    elif right >= left:
        seg["lo"] = o1 + timedelta(days=1)
    else:
        seg["hi"] = o0 - timedelta(days=1)
    return True


def _form4_counts(con, flat, pairs) -> dict:
    """(a, b) → own Form 4 filings printing the ticker during the overlap, per company."""
    from sentinel.staging.sec_form4_daily import union_sql

    con.execute(
        "create or replace temp table _ov (a INTEGER, b INTEGER, cik VARCHAR, ticker VARCHAR, "
        "o0 DATE, o1 DATE)"
    )
    rows = []
    for a, b, o0, o1, _, _ in pairs:
        for side in (a, b):
            rows.append((a, b, flat[side]["cik"], flat[side]["ticker"], o0, o1))
    con.executemany("insert into _ov values (?, ?, ?, ?, ?, ?)", rows)
    got = con.execute(
        f"""
        select o.a, o.b, o.cik, count(distinct s.accession_number)
        from _ov o left join {union_sql(con, "submission")} s on s.issuercik = o.cik
             and upper(replace(replace(trim(s.issuertradingsymbol), '.', '-'), '/', '-'))
                 = o.ticker
             and s.filing_date between o.o0 and o.o1
        group by 1, 2, 3
        """
    ).fetchall()
    out: dict = {}
    for a, b, cik, n in got:
        na, nb = out.get((a, b), (0, 0))
        out[(a, b)] = (n, nb) if cik == flat[a]["cik"] else (na, n)
    return out


# --- pass 4: adjustment factors ----------------------------------------------------------------


def factors(con, segs_by_cik: dict[str, list[dict]]) -> None:
    """Each earlier segment's adjusted prices × (later segment's adjusted ÷ as-traded on its
    first day) ÷ (its own on its last day), chained from the latest segment (R10)."""
    multi = [x for segs in segs_by_cik.values() if len(segs) > 1 for x in segs]
    for segs in segs_by_cik.values():
        for x in segs:
            x["adj_factor"] = 1.0
    if not multi:
        return
    edges(con, multi)
    points = [(x["source"], x["ticker"], x[k]) for x in multi for k in ("first", "last") if x[k]]
    prices = _as_traded(con, sorted(set(points), key=str))
    for segs in segs_by_cik.values():
        factor = 1.0
        for i in range(len(segs) - 2, -1, -1):
            later = prices.get((segs[i + 1]["source"], segs[i + 1]["ticker"], segs[i + 1]["first"]))
            mine = prices.get((segs[i]["source"], segs[i]["ticker"], segs[i]["last"]))
            if later and mine and mine[1]:
                factor *= later[1] / mine[1]
            segs[i]["adj_factor"] = factor
