"""Step 10: spreads and round-trip trading costs per event (feature 004, research R14; plan §6.8).

    cost = S + 2 · k · σ · √(Q ÷ ADDV20)

- S: the Abdi–Ranaldo (2017) spread from daily close, high and low over the 20 sessions to T —
  the mean of the two-day estimates 4·(c_t − η_t)·(c_t − η_{t+1}), with c the log close and η the
  mean of log high and log low, then √max(mean, 0) — floored at one tick relative to the as-traded
  close at T ($0.05 for a Tick Size Pilot stock-day, else $0.01). Split-adjusted prices are used,
  so a split inside the window does not look like a jump. Corwin–Schultz (2012) is a cross-check.
- σ: the standard deviation of daily log returns of the adjusted close over the 63 sessions to T;
  at least `rules.min_volatility_returns` returns, or the cost is left null.
- Q = `registered.position_size`, k = `registered.impact_coefficient`, ADDV20 as for the floors.
Only rows up to the last session on or before T are used.
"""

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

from sentinel.config import registered_value
from sentinel.warehouse import exact_sum, require_tables, table_exists

K_CS = 3 - 2 * math.sqrt(2)
BUCKETS = [(None, 2.0, "below $2"), (2.0, 3.0, "$2–3"), (3.0, 5.0, "$3–5"), (5.0, 10.0, "$5–10"),
           (10.0, 20.0, "$10–20"), (20.0, 50.0, "$20–50"), (50.0, None, "$50+")]  # fmt: skip
COLUMNS = (
    "event_id VARCHAR, spread_ar DOUBLE, spread_cs DOUBLE, tick DOUBLE, tick_floor DOUBLE, "
    "spread DOUBLE, volatility DOUBLE, addv20 DOUBLE, impact DOUBLE, cost DOUBLE, "
    "n_returns INTEGER, price_source VARCHAR"
)


# --- Reference formulas (tests check the SQL against them) --------------------------------------


def ar_two_day(c, h, low, h1, l1) -> float:
    eta, eta1 = (math.log(h) + math.log(low)) / 2, (math.log(h1) + math.log(l1)) / 2
    return 4 * (math.log(c) - eta) * (math.log(c) - eta1)


def ar_spread(closes, highs, lows) -> float | None:
    """Abdi–Ranaldo over consecutive rows: √max(mean of two-day estimates, 0)."""
    pairs = [
        ar_two_day(closes[i], highs[i], lows[i], highs[i + 1], lows[i + 1])
        for i in range(len(closes) - 1)
    ]
    return math.sqrt(max(sum(pairs) / len(pairs), 0.0)) if pairs else None


def cs_two_day(c, h, low, h1, l1) -> float:
    """Corwin–Schultz two-day spread, with the overnight adjustment, floored at 0."""
    if c < l1:
        h1, l1 = h1 - (l1 - c), c
    elif c > h1:
        h1, l1 = c, l1 + (c - h1)
    beta = math.log(h / low) ** 2 + math.log(h1 / l1) ** 2
    gamma = math.log(max(h, h1) / min(low, l1)) ** 2
    alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / K_CS - math.sqrt(gamma / K_CS)
    return max(2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha)), 0.0)


def round_trip_cost(spread: float, sigma: float, addv: float, q: float, k: float) -> float:
    return spread + 2 * k * sigma * math.sqrt(q / addv)


# --- Warehouse --------------------------------------------------------------------------------


@dataclass
class CostReport:
    events: int = 0
    with_cost: int = 0
    pilot_days: int = 0
    median_cost: float | None = None
    by_source: dict[str, int] = field(default_factory=dict)


def _windows(con, source: str) -> None:
    """`_w`: the 64 sessions to T of each row of `source` (id, issuer_cik, t_session), priced."""
    con.execute(
        f"""
        create or replace temp table _w as
        select x.id, t.session_no as t_no, s.session_no, p.session,
               p.close / p.cum_split_after as c, p.high / p.cum_split_after as h,
               p.low / p.cum_split_after as l, p.adj_close
        from {source} x
        join core.session t on t.session = x.t_session
        join core.session s on s.session_no between t.session_no - 63 and t.session_no
        join core.price_daily p on p.issuer_cik = x.issuer_cik and p.session = s.session
        """
    )


def _estimates(con, params: dict, source: str) -> None:
    """`_est`: spread, volatility and cost for each row of `source`, which needs id, issuer_cik,
    t_session, close_t, addv20 and price_source."""
    _windows(con, source)
    window = registered_value(params, "spread_addv_window")
    q, k = registered_value(params, "position_size"), registered_value(params, "impact_coefficient")
    rules = params["rules"]
    tickers = ["select issuer_cik, ticker from core.price_series"]
    if table_exists(con, "core.symbol_map"):
        tickers.append("select issuer_cik, ticker from core.symbol_map")
    pilot = (
        f"""select x.id from {source} x
            join ({" union ".join(tickers)}) k on k.issuer_cik = x.issuer_cik
            join core.tick_pilot tp on tp.ticker = k.ticker and x.t_session >= tp.valid_from
             and (tp.valid_to is null or x.t_session < tp.valid_to)
            group by 1"""
        if table_exists(con, "core.tick_pilot")
        else "select null as id where false"
    )
    con.execute(
        f"""
        create or replace temp table _est as
        with pairs as (
            select id, c, h, l,
                   lead(h) over w as h1, lead(l) over w as l1
            from _w where session_no > t_no - {window}
            window w as (partition by id order by session)
        ),
        adj as (
            select *, case when c < l1 then l1 - c when c > h1 then -(c - h1) else 0 end as shift
            from pairs where h1 is not null and h > 0 and l > 0 and h1 > 0 and l1 > 0 and c > 0
        ),
        cs as (
            select id, c, h, l, h1 - shift as h1s, l1 - shift as l1s,
                   4 * (ln(c) - (ln(h) + ln(l)) / 2) * (ln(c) - (ln(h1) + ln(l1)) / 2) as ar2
            from adj
        ),
        cs2 as (
            select id, ar2,
                   ln(h / l) ^ 2 + ln(h1s / l1s) ^ 2 as beta,
                   ln(greatest(h, h1s) / least(l, l1s)) ^ 2 as gamma
            from cs
        ),
        spreads as (  -- means and the standard deviation below use order-free exact sums
            select id, sqrt(greatest({exact_sum("ar2", 18)} / count(ar2), 0)) as spread_ar,
                   {exact_sum("cs2", 18)} / count(cs2) as spread_cs
            from (select id, ar2, greatest(2 * (exp(a) - 1) / (1 + exp(a)), 0) as cs2
                  from (select *, (sqrt(2 * beta) - sqrt(beta)) / {K_CS}
                                  - sqrt(gamma / {K_CS}) as a from cs2))
            group by 1
        ),
        rets as (
            select id, ln(adj_close / lag(adj_close) over (partition by id order by session)) as r
            from _w where adj_close > 0
        ),
        mean as (select id, {exact_sum("r", 18)} / count(r) as mu, count(r) as n
                 from rets group by 1),
        vol as (
            select m.id, sqrt({exact_sum("(r.r - m.mu) ^ 2", 18)} / nullif(m.n - 1, 0)) as sigma,
                   m.n
            from rets r join mean m using (id) group by m.id, m.n
        ),
        pilot as ({pilot})
        select x.id, sp.spread_ar, sp.spread_cs,
               cast(case when x.id in (select id from pilot) then {rules["tick_size_pilot_usd"]}
                         else {rules["tick_size_usd"]} end as DOUBLE) as tick,
               x.close_t, x.addv20, x.price_source, v.sigma, coalesce(v.n, 0) as n_returns
        from {source} x
        left join spreads sp on sp.id = x.id
        left join vol v on v.id = x.id
        """
    )
    con.execute(
        """
        create or replace temp table _est as
        select *, greatest(coalesce(spread_ar, 0), tick_floor) as spread
        from (select *, tick / close_t as tick_floor from _est)
        """
    )
    con.execute(
        f"""
        create or replace temp table _est as
        select *, case when ok then {k} * sigma * sqrt({q} / addv20) end as impact,
               case when ok then spread + 2 * {k} * sigma * sqrt({q} / addv20) end as cost
        from (select *, n_returns >= {rules["min_volatility_returns"]} and addv20 > 0 as ok
              from _est)
        """
    )


def estimate(con: duckdb.DuckDBPyConnection, params: dict, source: str) -> None:
    """`_est` for any positions, not only events: `source` needs id, issuer_cik, t_session,
    close_t, addv20 and price_source (feature 006 uses it for past purchases, F10)."""
    _estimates(con, params, source)


def build(con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None) -> CostReport:
    """Rebuild `evt.event_cost` for priced events."""
    require_tables(con, ["evt.event", "core.price_daily", "core.session"], "detect")
    clauses = ["priced"]
    if cutoff is not None:
        clauses.append(f"signal_date <= cast('{cutoff}' as DATE)")
    if issuers is not None:
        clauses.append("issuer_cik in (" + ", ".join(f"'{c}'" for c in issuers) + ")")
    con.execute(
        "create or replace temp table _src as select event_id as id, issuer_cik, t_session, "
        f"close_t, addv20, price_source from evt.event where {' and '.join(clauses)}"
    )
    _estimates(con, params, "_src")
    con.execute("begin transaction")
    try:
        con.execute(
            "create or replace table evt.event_cost as select id as event_id, spread_ar, "
            "spread_cs, tick, tick_floor, spread, sigma as volatility, addv20, impact, cost, "
            "cast(n_returns as INTEGER) as n_returns, price_source from _est order by 1"
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    for name in ("_src", "_w", "_est"):
        con.execute(f"drop table if exists {name}")
    n, with_cost, pilot, median = con.execute(
        "select count(*), count(cost), count(*) filter (where tick > 0.01), median(cost) "
        "from evt.event_cost"
    ).fetchone()
    report = CostReport(events=n, with_cost=with_cost, pilot_days=pilot, median_cost=median)
    report.by_source = dict(
        con.execute("select price_source, count(*) from evt.event_cost group by 1").fetchall()
    )
    return report


def check_costs(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W24: cost ≥ spread ≥ tick ÷ close at T, where not null."""
    return [
        r[0]
        for r in con.execute(
            """
            select c.event_id from evt.event_cost c join evt.event e using (event_id)
            where c.spread < c.tick / e.close_t - 1e-12
               or (c.cost is not null and c.cost < c.spread - 1e-12)
            order by 1
            """
        ).fetchall()
    ]


def _quartiles(con, table: str, where: str) -> list[tuple]:
    out = []
    for low, high, label in BUCKETS:
        conds = [where]
        if low is not None:
            conds.append(f"close_t >= {low}")
        if high is not None:
            conds.append(f"close_t < {high}")
        row = con.execute(
            f"select count(*), quantile_cont(spread, [0.25, 0.5, 0.75]), "
            f"quantile_cont(cost, [0.25, 0.5, 0.75]) from {table} where {' and '.join(conds)}"
        ).fetchone()
        out.append((label, *row))
    return out


def write_report(con: duckdb.DuckDBPyConnection, params: dict, path: Path) -> list[str]:
    """`costs.md`: spread and cost by as-traded price bucket over development events (2012–2022),
    with a below-$2 bucket from candidates that failed only the price floor; flags any jump in
    the median cost of more than half at a boundary other than $2. Returns the flags."""
    start = registered_value(params, "labelled_window_start")
    dev = f"signal_date between cast('{start}' as DATE) and date '2022-12-31'"
    con.execute(
        f"""
        create or replace temp table _dev as
        select c.*, e.close_t from evt.event_cost c join evt.event e using (event_id)
        where e.{dev}
        """
    )
    floor = registered_value(params, "liquidity_floor")["min_addv_usd"]
    active = registered_value(params, "activity_floor")["min_active_sessions"]
    con.execute(
        f"""
        create or replace temp table _src as
        select candidate_id as id, issuer_cik, t_session, close_t, addv20, price_source
        from evt.event_candidate
        where outcome = 'floor_price' and addv20 >= {floor} and active_sessions_20 >= {active}
          and {dev}
        """
    )
    _estimates(con, params, "_src")
    con.execute(
        "create or replace temp table _all as "
        "select spread, cost, close_t from _dev union all select spread, cost, close_t from _est"
    )
    rows = _quartiles(con, "_all", "true")
    flags = []
    medians = [(label, q[1]) for label, _, _, q in rows if q is not None and q[1] is not None]
    for (a, ma), (b, mb) in zip(medians, medians[1:], strict=False):
        if a != "below $2" and ma and abs(mb - ma) / ma > 0.5:
            flags.append(f"median cost jumps from {ma:.2%} ({a}) to {mb:.2%} ({b})")
    agree = con.execute(
        "select median(spread_cs / nullif(spread_ar, 0)), corr(r_ar, r_cs) from ("
        "select spread_ar, spread_cs, rank() over (order by spread_ar) as r_ar, "
        "rank() over (order by spread_cs) as r_cs from _dev "
        "where spread_ar is not null and spread_cs is not null)"
    ).fetchone()

    def pct(x):
        return f"{x:.2%}" if x is not None else "–"

    lines = [
        "# Feature 004: trading costs by price",
        "",
        f"Generated by `sentinel costs` on {date.today()}. Development events (2012–2022); "
        "aggregates only. Cost = spread + 2 · k · σ · √(Q ÷ ADDV20), round trip, for a "
        f"${registered_value(params, 'position_size'):,} position (plan §6.8).",
        "",
        "| As-traded price at T | Events | Spread (median) | Spread (IQR) | Cost (median) | "
        "Cost (IQR) |",
        "|---|---|---|---|---|---|",
    ]
    for label, n, s, c in rows:
        if not n:
            lines.append(f"| {label} | 0 | – | – | – | – |")
            continue
        lines.append(
            f"| {label} | {n:,} | {pct(s[1])} | {pct(s[0])}–{pct(s[2])} | {pct(c[1])} | "
            f"{pct(c[0])}–{pct(c[2])} |"
        )
    lines += [
        "",
        "The below-$2 row holds candidates that failed only the price floor, for comparison.",
        "",
        "**Jumps at a price other than $2**: " + ("; ".join(flags) if flags else "none."),
        "",
        f"**Corwin–Schultz cross-check**: median CS ÷ AR = {agree[0]:.2f}"
        if agree[0] is not None
        else "**Corwin–Schultz cross-check**: –",
    ]
    if agree[1] is not None:
        lines[-1] += f"; rank correlation {agree[1]:.2f}."
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in ("_dev", "_src", "_w", "_est", "_all"):
        con.execute(f"drop table if exists {name}")
    return flags
