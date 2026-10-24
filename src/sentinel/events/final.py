"""Step 7: G8 and final events A, B1 and B2 (feature 004, research R6–R7; plan §6.2, §6.4–6.5).

G8 checks each purchase line's reported price against the as-traded range of the last session on
or before its trade date, widened by `registered.g8_tolerance`; purchases are then rebuilt from the
lines that pass, with the G6 minimum applied again (`core.priced_purchase`). Issuers without prices
skip G8, and so do lines traded before `rules.price_history_start`, for which no prices are fetched.

Candidates are feature 002's (issuer, group, T) windows on those purchases, with entities and roles
as of T, from `rules.final_detection_start`. Per issuer and group, in date order, each candidate
gets the first outcome that applies:
1. `cooldown`: the last kept event is fewer than `registered.cooldown` sessions earlier;
2. G7 from the signal filing's header: `needs_header`, `g7_issuer_type` (SIC 6770, 6722, 6726) or
   `g7_no_sic` (D45; `rules.g7_no_sic = current_sic` uses the issuer's current SIC instead);
3. `unpriced`: no price row in the 20 sessions to T;
4. the floors at the last session on or before T, from rows up to it only: `floor_price`,
   `floor_liquidity`, `floor_activity`;
5. otherwise `event`.
`event` and `unpriced` are kept and start a cooldown; floor failures do not. Entry is the session
after T.
"""

from dataclasses import dataclass, field

import duckdb
import pyarrow as pa

from sentinel.config import registered_value
from sentinel.core import gates
from sentinel.events import prelim
from sentinel.warehouse import MissingInput, exact_sum, require_tables, scope, table_exists

KEPT = ("event", "unpriced")
NO_SIC = {"", "0000"}  # EDGAR's "0000" means no industry code assigned (D45)
EPS = 1e-9  # float slack at the G8 boundaries
G8_FAILS = (
    "not exists (select 1 from core.price_check pc where pc.accession = t.accession "
    "and pc.line_sk = t.line_sk and not pc.passes_g8)"
)


@dataclass
class DetectReport:
    g8_checked: int = 0
    g8_passed: int = 0
    candidates: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    events: dict[str, int] = field(default_factory=dict)
    needs_header: list[str] = field(default_factory=list)
    coverage: dict[str, tuple[int, int]] = field(default_factory=dict)


def _prices(con: duckdb.DuckDBPyConnection, cutoff=None, issuers=None) -> str:
    """The price rows a run may use: all of `core.price_daily`, or for truncation tests only rows up
    to the last session on or before `cutoff` (and of `issuers`), copied into a temp table."""
    if cutoff is None and issuers is None:
        return "core.price_daily"
    clauses, args = ["true"], {}
    if cutoff is not None:
        clauses.append(
            "session <= (select max(session) from core.session "
            "where session <= cast($cutoff as DATE))"
        )
        args["cutoff"] = cutoff
    if issuers is not None:
        clauses.append("list_contains($issuers::VARCHAR[], issuer_cik)")
        args["issuers"] = list(issuers)
    con.execute(
        f"create or replace temp table _prices as select * from core.price_daily "
        f"where {' and '.join(clauses)}",
        args,
    )
    return "_prices"


def _series(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "create or replace temp table _series as select issuer_cik, "
        "any_value(price_source) filter (where role <> 'fill_in') as price_source "
        "from core.price_series where chosen group by 1"
    )


def build_price_check(con, params: dict, cutoff=None, issuers=None) -> tuple[int, int]:
    """`core.price_check` (one row per line passing G1–G6a at a priced issuer, traded on or after
    `rules.price_history_start`) and `audit.g8_rate`. Returns (lines checked, lines passed)."""
    where, args = scope(cutoff, issuers, alias="t")
    args["price_start"] = str(params["rules"]["price_history_start"])
    prices = _prices(con, cutoff, issuers)
    _series(con)
    tol = registered_value(params, "g8_tolerance")
    ok = (
        f"m.price >= m.low * (1 - {tol}) * (1 - {EPS}) "
        f"and m.price <= m.high * (1 + {tol}) * (1 + {EPS})"
    )
    con.execute(
        f"""
        create or replace table core.price_check as
        with lines as (
            select t.accession, t.line_sk, t.issuer_cik, t.trans_date as trade_date, t.price
            from core.transaction t
            where t.passes_lines and {where}
              and t.trans_date >= cast($price_start as DATE)
              and t.issuer_cik in (select issuer_cik from _series)
        ),
        matched as (
            select l.*, p.session as ref_session, p.low, p.high, p.price_source as row_source
            from lines l asof left join {prices} p
              on l.issuer_cik = p.issuer_cik and l.trade_date >= p.session
        )
        select m.accession, m.line_sk, m.issuer_cik, m.trade_date, m.price, m.ref_session,
               m.low, m.high, coalesce(m.ref_session is not null and {ok}, false) as passes_g8,
               case when m.ref_session is null then 'no_session'
                    when {ok} then 'ok' else 'outside_range' end as reason,
               coalesce(m.row_source, s.price_source) as price_source
        from matched m join _series s using (issuer_cik)
        """,
        args,
    )
    con.execute(
        """
        create or replace table audit.g8_rate as
        with rates as (
            select cast(year(trade_date) as VARCHAR) as year, count(*) as lines_checked,
                   count(*) filter (where passes_g8) as lines_passed
            from core.price_check group by 1
            union all
            select 'total', count(*), count(*) filter (where passes_g8) from core.price_check
        )
        select *, lines_passed / nullif(lines_checked, 0) as rate from rates order by year
        """
    )
    checked, passed = con.execute(
        "select count(*), count(*) filter (where passes_g8) from core.price_check"
    ).fetchone()
    return checked, passed


def build_priced_purchase(con, params: dict, cutoff=None, issuers=None) -> int:
    """`core.priced_purchase`: clean purchases rebuilt from lines that pass G8 (or were not
    checked), with the G6 minimum applied again; `g8_status` says whether G8 applied."""
    n = gates.build_clean_purchases(
        con, params, cutoff, issuers, target="core.priced_purchase", line_filter=G8_FAILS
    )
    con.execute(
        "create or replace table core.priced_purchase as select *, case when issuer_cik not in "
        "(select issuer_cik from core.price_series where chosen) then 'skipped_unpriced' "
        "when max_trade_date < cast(? as DATE) then 'skipped_before_prices' else 'checked' end "
        "as g8_status from core.priced_purchase",
        [str(params["rules"]["price_history_start"])],
    )
    return n


def _inputs(con, params: dict, prices: str) -> list[dict]:
    """Every candidate in `_events` with its header, calendar position and floor inputs."""
    window = registered_value(params, "liquidity_floor")["addv_window_sessions"]
    issuer = (
        "i.sic as current_sic"
        if table_exists(con, "core.issuer")
        else "cast(null as VARCHAR) as current_sic"
    )
    join_issuer = (
        "left join core.issuer i on i.issuer_cik = c.issuer_cik" if "i.sic" in issuer else ""
    )
    failed = (
        "c.signal_accession in (select accession from core.header_failure)"
        if table_exists(con, "core.header_failure")
        else "false"
    )
    con.execute(
        f"""
        create or replace temp table _cand as
        with placed as (
            select e.*, s.session as t_session, s.session_no as t_no
            from _events e asof left join core.session s on e.signal_date >= s.session
        ),
        win as (
            select c.event_id, count(p.session) as n_rows,
                   {exact_sum("coalesce(p.dollar_volume, 0)")} / {window} as addv20,
                   count(*) filter (where p.volume > 0) as active,
                   arg_max(p.close, p.session) as close_t
            from placed c
            join core.session w on w.session_no between c.t_no - {window - 1} and c.t_no
            left join {prices} p on p.issuer_cik = c.issuer_cik and p.session = w.session
            group by 1
        ),
        span as (
            select p.issuer_cik, min(s.session_no) as first_no, max(s.session_no) as last_no
            from {prices} p join core.session s using (session) group by 1
        )
        select c.event_id, c.issuer_cik, c."group", c.signal_date, c.signal_accession,
               c.n_entities, c.total_value_usd, c.max_seniority, c.t_session, c.t_no,
               nx.session as entry_session, h.accession is not null as header_found,
               h.sic, h.accepted_at_et, {issuer}, {failed} as header_failed,
               se.price_source, coalesce(w.n_rows, 0) as n_rows, w.addv20, w.active, w.close_t,
               sp.first_no, sp.last_no
        from placed c
        left join core.session nx on nx.session_no = c.t_no + 1
        left join core.filing_header h on h.accession = c.signal_accession
        {join_issuer}
        left join _series se on se.issuer_cik = c.issuer_cik
        left join win w on w.event_id = c.event_id
        left join span sp on sp.issuer_cik = c.issuer_cik
        """
    )
    cursor = con.execute('select * from _cand order by issuer_cik, "group", signal_date')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _known(sic: str | None) -> str | None:
    return None if sic is None or sic.strip() in NO_SIC else sic


def _sic_number(sic) -> int | None:
    try:
        return int(sic)
    except TypeError, ValueError:
        return None


def decide(candidates: list[dict], params: dict, floors: bool = True) -> dict[str, dict]:
    """event_id → {outcome, sic, sic_source}, by the sequential pass in the module docstring.
    `candidates` must be ordered by issuer, group and signal date."""
    rules = params["rules"]
    cooldown = registered_value(params, "cooldown")
    excluded = set(rules["g7_excluded_sic"])
    price_floor = registered_value(params, "price_floor")
    min_addv = registered_value(params, "liquidity_floor")["min_addv_usd"]
    min_active = registered_value(params, "activity_floor")["min_active_sessions"]
    last: dict[tuple, int] = {}
    decided = {}
    for c in candidates:
        key = (c["issuer_cik"], c["group"])
        sic, source = None, None
        if key in last and c["t_no"] - last[key] < cooldown:
            outcome = "cooldown"
        elif not c["header_found"]:
            outcome = "needs_header"
        else:
            sic, source = _known(c["sic"]), "header"
            if sic is None and rules["g7_no_sic"] == "current_sic":
                sic, source = _known(c["current_sic"]), "current"
            if sic is None:
                outcome, source = "g7_no_sic", None
            elif _sic_number(sic) in excluded:
                outcome = "g7_issuer_type"
            elif c["price_source"] is None or not c["n_rows"]:
                outcome = "unpriced"
            elif floors and c["close_t"] < price_floor:
                outcome = "floor_price"
            elif floors and c["addv20"] < min_addv:
                outcome = "floor_liquidity"
            elif floors and c["active"] < min_active:
                outcome = "floor_activity"
            else:
                outcome = "event"
        if outcome in KEPT:
            last[key] = c["t_no"]
        decided[c["event_id"]] = {"outcome": outcome, "sic": sic, "sic_source": source}
    return decided


def _table(rows: list[dict], schema: list[tuple[str, pa.DataType]]) -> pa.Table:
    return pa.table({n: pa.array([r[n] for r in rows], t) for n, t in schema})


CANDIDATE_SCHEMA = [
    ("candidate_id", pa.string()), ("issuer_cik", pa.string()), ("group", pa.string()),
    ("signal_date", pa.date32()), ("signal_accession", pa.string()),
    ("t_session", pa.date32()), ("t_session_no", pa.int32()), ("outcome", pa.string()),
    ("close_t", pa.float64()), ("addv20", pa.float64()), ("active_sessions_20", pa.int32()),
    ("price_source", pa.string()),
]  # fmt: skip
EVENT_SCHEMA = [
    ("event_id", pa.string()), ("issuer_cik", pa.string()), ("group", pa.string()),
    ("signal_date", pa.date32()), ("signal_accession", pa.string()),
    ("accepted_at_et", pa.timestamp("s")), ("t_session", pa.date32()),
    ("entry_session", pa.date32()), ("n_entities", pa.int64()),
    ("total_value_usd", pa.float64()), ("max_seniority", pa.int32()), ("g7_sic", pa.string()),
    ("g7_sic_source", pa.string()), ("priced", pa.bool_()), ("close_t", pa.float64()),
    ("addv20", pa.float64()), ("active_sessions_20", pa.int32()),
    ("shares_outstanding", pa.float64()), ("shares_filed", pa.date32()),
    ("market_cap", pa.float64()), ("in_labelled_window", pa.bool_()),
    ("price_source", pa.string()),
]  # fmt: skip


def _write(con, params: dict, candidates: list[dict], decided: dict[str, dict]) -> None:
    start = registered_value(params, "labelled_window_start")
    cand_rows, event_rows = [], []
    for c in candidates:
        d = decided[c["event_id"]]
        priced = c["price_source"] is not None and bool(c["n_rows"])
        inputs = {
            "close_t": c["close_t"] if priced else None,
            "addv20": c["addv20"] if priced else None,
            "active_sessions_20": c["active"] if priced else None,
            "price_source": c["price_source"] if priced else None,
        }
        cand_rows.append(
            {
                "candidate_id": c["event_id"],
                "issuer_cik": c["issuer_cik"],
                "group": c["group"],
                "signal_date": c["signal_date"],
                "signal_accession": c["signal_accession"],
                "t_session": c["t_session"],
                "t_session_no": c["t_no"],
                "outcome": d["outcome"],
                **inputs,
            }  # fmt: skip
        )
        if d["outcome"] in KEPT:
            event_rows.append(
                {
                    "event_id": c["event_id"],
                    "issuer_cik": c["issuer_cik"],
                    "group": c["group"],
                    "signal_date": c["signal_date"],
                    "signal_accession": c["signal_accession"],
                    "accepted_at_et": c["accepted_at_et"],
                    "t_session": c["t_session"],
                    "entry_session": c["entry_session"],
                    "n_entities": c["n_entities"],
                    "total_value_usd": c["total_value_usd"],
                    "max_seniority": c["max_seniority"],
                    "g7_sic": d["sic"],
                    "g7_sic_source": d["sic_source"],
                    "priced": priced,
                    "shares_outstanding": None,
                    "shares_filed": None,
                    "market_cap": None,
                    "in_labelled_window": c["signal_date"] >= start,
                    **inputs,
                }  # fmt: skip
            )
    con.register("_cand_out", _table(cand_rows, CANDIDATE_SCHEMA))
    con.register("_event_out", _table(event_rows, EVENT_SCHEMA))
    try:
        con.execute("begin transaction")
        try:
            con.execute("create or replace table evt.event_candidate as select * from _cand_out")
            con.execute("create or replace table evt.event as select * from _event_out")
            con.execute(
                "create or replace table evt.event_member as "
                "select m.event_id, m.accession, m.entity_id_at_t, m.entity_role_at_t, m.value_usd "
                "from _event_members m where m.event_id in (select event_id from evt.event)"
            )
            con.execute(
                "create or replace table audit.event_funnel as select cast(year(signal_date) as "
                'INTEGER) as year, "group", outcome, count(*) as n from evt.event_candidate '
                "group by all order by all"
            )
        except BaseException:
            con.execute("rollback")
            raise
        con.execute("commit")
    finally:
        con.unregister("_cand_out")
        con.unregister("_event_out")


def _market_caps(con: duckdb.DuckDBPyConnection, cutoff=None) -> None:
    """Shares outstanding with the latest `filed` on or before T (then the latest period end), and
    market capitalisation = as-traded close at T × those shares (FR-022)."""
    if not table_exists(con, "core.xbrl_fact"):
        return
    con.execute(
        """
        create or replace temp table _caps as
        select e.event_id, f.value as shares, f.filed
        from evt.event e join core.xbrl_fact f
          on f.issuer_cik = e.issuer_cik and f.concept = 'shares_outstanding'
         and f.filed <= e.signal_date and ($cutoff is null or f.filed <= cast($cutoff as DATE))
        qualify row_number() over (
            partition by e.event_id order by f.filed desc, f.period_end desc, f.value desc) = 1
        """,
        {"cutoff": None if cutoff is None else str(cutoff)},
    )
    con.execute(
        """
        update evt.event set shares_outstanding = c.shares, shares_filed = c.filed,
               market_cap = case when priced then close_t * c.shares end
        from _caps c where c.event_id = evt.event.event_id
        """
    )
    con.execute("drop table _caps")


def _coverage(con, params: dict, candidates: list[dict], decided: dict[str, dict]) -> None:
    """`audit.price_coverage` (SC-001): A and B1 events from the labelled start, before floors."""
    start = registered_value(params, "labelled_window_start")
    gap = params["rules"]["delisting_end_gap_sessions"]
    end_no = con.execute("select max(session_no) from core.session").fetchone()[0]
    counts: dict[tuple, list[int]] = {}
    for c in candidates:
        if (
            decided[c["event_id"]]["outcome"] not in KEPT
            or c["group"] not in ("A", "B1")
            or c["signal_date"] < start
        ):
            continue
        if c["price_source"] is None or c["last_no"] is None:
            status, covered = "unpriced_issuer", False
        else:
            status = "listed" if c["last_no"] >= end_no - gap else "delisted"
            covered = c["first_no"] <= c["t_no"] - 19 and c["last_no"] >= c["t_no"] + 1
        key = (c["signal_date"].year, c["group"], status)
        bucket = counts.setdefault(key, [0, 0])
        bucket[0] += 1
        bucket[1] += covered
    rows = [(y, g, s, n, k, k / n) for (y, g, s), (n, k) in sorted(counts.items())]
    con.execute(
        'create or replace table audit.price_coverage (year INTEGER, "group" VARCHAR, '
        "delisting_status VARCHAR, events BIGINT, covered BIGINT, share DOUBLE)"
    )
    if rows:
        con.executemany("insert into audit.price_coverage values (?, ?, ?, ?, ?, ?)", rows)


def detect(con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None) -> DetectReport:
    """G8, priced purchases, final events and the coverage report (see the module docstring)."""
    require_tables(con, ["core.transaction", "core.entity_member", "core.owner_role"], "gates")
    require_tables(con, ["core.price_daily", "core.price_series", "core.session"], "prices")
    if not table_exists(con, "core.filing_header"):
        raise MissingInput("run `sentinel fetch-headers` first: missing core.filing_header")
    report = DetectReport()
    report.g8_checked, report.g8_passed = build_price_check(con, params, cutoff, issuers)
    build_priced_purchase(con, params, cutoff, issuers)
    prelim.find_events(
        con, params, purchases="core.priced_purchase", cutoff=cutoff, issuers=issuers, keep=None,
        start=params["rules"]["final_detection_start"],
    )  # fmt: skip
    candidates = _inputs(con, params, _prices(con, cutoff, issuers))
    decided = decide(candidates, params)
    _write(con, params, candidates, decided)
    _market_caps(con, cutoff)
    _coverage(con, params, candidates, decide(candidates, params, floors=False))
    report.candidates = len(candidates)
    for c in candidates:
        d = decided[c["event_id"]]
        report.outcomes[d["outcome"]] = report.outcomes.get(d["outcome"], 0) + 1
        if d["outcome"] == "event":
            report.events[c["group"]] = report.events.get(c["group"], 0) + 1
        if d["outcome"] == "needs_header" and not c["header_failed"]:
            report.needs_header.append(c["signal_accession"])
    report.needs_header = sorted(set(report.needs_header))
    for (group,) in con.execute(
        'select distinct "group" from audit.price_coverage order by 1'
    ).fetchall():
        report.coverage[group] = con.execute(
            'select sum(events), sum(covered) from audit.price_coverage where "group" = ?', [group]
        ).fetchone()
    for name in ("_window", "_window_entity", "_events", "_event_members", "_cand", "_prices",
                 "_series"):  # fmt: skip
        con.execute(f"drop table if exists {name}")
    return report


# --- Invariants W16–W21 (contracts/warehouse-schema.md) ----------------------------------------


def check_price_check(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W16: G8 rows only at priced issuers; the rate table's total matches the rows."""
    stray = con.execute(
        "select count(*) from core.price_check where issuer_cik not in "
        "(select issuer_cik from core.price_series where chosen)"
    ).fetchone()[0]
    rows = con.execute(
        "select count(*), count(*) filter (where passes_g8) from core.price_check"
    ).fetchone()
    total = con.execute(
        "select lines_checked, lines_passed from audit.g8_rate where year = 'total'"
    ).fetchone()
    problems = [f"{stray} G8 rows at unpriced issuers"] if stray else []
    if total is not None and tuple(total) != tuple(rows):
        problems.append(f"g8_rate total {tuple(total)} != price_check {tuple(rows)}")
    return problems


def check_priced_minimum(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """W17: every priced purchase reaches the G6 minimum."""
    return [
        r[0]
        for r in con.execute(
            "select accession from core.priced_purchase where value_usd < ? order by 1",
            [registered_value(params, "g6_min_value")],
        ).fetchall()
    ]


def check_entry_sessions(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W18: t_session ≤ T < entry_session, and entry is the session after t_session."""
    return [
        r[0]
        for r in con.execute(
            """
            select e.event_id from evt.event e
            join core.session a on a.session = e.t_session
            left join core.session b on b.session_no = a.session_no + 1
            where not (e.t_session <= e.signal_date and e.entry_session > e.signal_date)
               or e.entry_session is distinct from b.session
            order by 1
            """
        ).fetchall()
    ]


def check_cooldown(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """W19: no two kept events of one issuer and group fewer than `cooldown` sessions apart."""
    return [
        r[0]
        for r in con.execute(
            """
            with e as (
                select e.event_id, e.issuer_cik, e."group", s.session_no from evt.event e
                join core.session s on s.session = e.t_session
            )
            select a.event_id from e a join e b
              on a.issuer_cik = b.issuer_cik and a."group" = b."group"
             and b.session_no < a.session_no and a.session_no - b.session_no < ?
            order by 1
            """,
            [registered_value(params, "cooldown")],
        ).fetchall()
    ]


def check_kept_events(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """W20: priced events meet the floors; every kept event passed G7."""
    excluded = params["rules"]["g7_excluded_sic"]
    return [
        r[0]
        for r in con.execute(
            """
            select event_id from evt.event
            where (priced and (close_t < ? or addv20 < ? or active_sessions_20 < ?))
               or g7_sic is null or list_contains(?::INTEGER[], try_cast(g7_sic as INTEGER))
            order by 1
            """,
            [
                registered_value(params, "price_floor"),
                registered_value(params, "liquidity_floor")["min_addv_usd"],
                registered_value(params, "activity_floor")["min_active_sessions"],
                excluded,
            ],
        ).fetchall()
    ]


def check_funnel(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W21: each event has one kept candidate, and the funnel matches the candidates."""
    problems = [
        f"{r[0]} has no kept candidate"
        for r in con.execute(
            "select event_id from evt.event where event_id not in (select candidate_id from "
            "evt.event_candidate where outcome in ('event', 'unpriced')) order by 1"
        ).fetchall()
    ]
    extra = con.execute(
        "select count(*) from evt.event_candidate where outcome in ('event', 'unpriced') "
        "and candidate_id not in (select event_id from evt.event)"
    ).fetchone()[0]
    if extra:
        problems.append(f"{extra} kept candidates without an event row")
    diff = con.execute(
        """
        select count(*) from (
            select year, "group", outcome, n from audit.event_funnel
            except
            select cast(year(signal_date) as INTEGER), "group", outcome, count(*)
            from evt.event_candidate group by all
        )
        """
    ).fetchone()[0]
    if diff:
        problems.append(f"{diff} funnel rows differ from the candidates")
    return problems


def check_market_caps(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W22 (part): market caps use only shares filed on or before T."""
    return [
        r[0]
        for r in con.execute(
            "select event_id from evt.event where shares_filed > signal_date "
            "or (market_cap is not null and not priced) order by 1"
        ).fetchall()
    ]
