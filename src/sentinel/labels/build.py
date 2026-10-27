"""`sentinel labels` (Step 11): `lab.event_label` and `lab.purchase_outcome` (feature 006).

Development labels only: windows end by 31 December 2022 (constitution III). Holdout labels are
written by the guarded Step 18 job, into `hold`, never here.
"""

from dataclasses import dataclass, field

import duckdb

from sentinel.config import registered_value
from sentinel.events import costs
from sentinel.labels.returns import development_end, window_returns
from sentinel.warehouse import exact_sum, require_tables

INPUTS = ["evt.event", "evt.event_cost", "evt.event_member", "core.price_daily", "core.session",
          "stg.price_yahoo", "core.ff_industry_daily", "core.ff_factor_daily",
          "core.sic_industry", "core.priced_purchase", "core.entity_member"]  # fmt: skip
LABEL_COLUMNS = (
    'event_id VARCHAR, horizon INTEGER, measure VARCHAR, issuer_cik VARCHAR, "group" VARCHAR, '
    "signal_date DATE, entry_session DATE, exit_session DATE, end_session DATE, "
    "entry_at_close BOOLEAN, stock_return DOUBLE, bench_return DOUBLE, gross DOUBLE, "
    "delisted BOOLEAN, delisting_class VARCHAR, delisting_return DOUBLE, gross_dl_zero DOUBLE, "
    "gross_dl_wipeout DOUBLE, cost DOUBLE, net DOUBLE, price_source VARCHAR"
)


@dataclass
class LabelReport:
    events: int = 0
    rows: int = 0
    no_entry_price: int = 0
    by_measure: dict[str, int] = field(default_factory=dict)
    delisted_windows: int = 0
    entry_at_close: int = 0
    null_net: int = 0
    purchase_outcomes: int = 0


def build(con: duckdb.DuckDBPyConnection, params: dict) -> LabelReport:
    """Rebuild `lab.event_label` (every priced event from the labelled-window start, every
    horizon and measure whose window ends by the development end) and `lab.purchase_outcome`."""
    require_tables(con, INPUTS, "detect")
    start = registered_value(params, "labelled_window_start")
    con.execute(
        "create or replace temp table _src as select event_id as id, issuer_cik, t_session, "
        "g7_sic as sic from evt.event where priced and signal_date >= cast(? as DATE)",
        [str(start)],
    )
    skipped = window_returns(con, params, "_src", list(registered_value(params, "horizons")))
    con.execute("begin transaction")
    try:
        con.execute(f"create or replace table lab.event_label ({LABEL_COLUMNS})")
        con.execute(
            """
            insert into lab.event_label
            select r.id, r.horizon, r.measure, e.issuer_cik, e."group", e.signal_date,
                   r.entry_session, r.exit_session, r.end_session, r.entry_at_close,
                   r.stock_return, r.bench_return, r.gross, r.delisted, r.delisting_class,
                   r.delisting_return, r.gross_dl_zero, r.gross_dl_wipeout, c.cost,
                   r.gross - c.cost, e.price_source
            from _res r join evt.event e on e.event_id = r.id
            left join evt.event_cost c on c.event_id = r.id
            order by r.id, r.horizon, r.measure
            """
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    report = LabelReport(no_entry_price=skipped.no_entry_price)
    report.events, report.rows = con.execute(
        "select count(distinct event_id), count(*) from lab.event_label"
    ).fetchone()
    report.by_measure = dict(
        con.execute(
            "select measure, count(gross) from lab.event_label group by 1 order by 1"
        ).fetchall()
    )
    report.delisted_windows, report.entry_at_close, report.null_net = con.execute(
        "select count(*) filter (where delisted), count(*) filter (where entry_at_close), "
        "count(*) filter (where net is null) from lab.event_label "
        "where measure = 'ind_ew' and horizon = 63"
    ).fetchone()
    report.purchase_outcomes = build_purchase_outcomes(con, params)
    return report


def _cost_inputs(con, params: dict, source: str) -> None:
    """`_csrc`: close and ADDV20 at each position's T, as final detection computes them."""
    window = registered_value(params, "liquidity_floor")["addv_window_sessions"]
    con.execute(
        f"""
        create or replace temp table _csrc as
        select x.id, x.issuer_cik, x.t_session,
               arg_max(p.close, p.session) as close_t,
               {exact_sum("coalesce(p.dollar_volume, 0)")} / {window} as addv20,
               arg_max(p.price_source, p.session) as price_source
        from {source} x
        join core.session t on t.session = x.t_session
        join core.session w on w.session_no between t.session_no - {window - 1} and t.session_no
        left join core.price_daily p on p.issuer_cik = x.issuer_cik and p.session = w.session
        group by 1, 2, 3
        """
    )


def build_purchase_outcomes(con: duckdb.DuckDBPyConnection, params: dict) -> int:
    """`lab.purchase_outcome` (research R8): for each development event, its buyers' earlier
    priced clean purchases at the issuer whose 63-session window ended before T, with the
    equal-weighted industry BHAR (the event's industry at T), the cost at the purchase date and
    the net. The input of F10."""
    end = development_end(params)
    primary = registered_value(params, "primary_horizon")
    con.execute(
        """
        create or replace temp table _buyers as
        with members as (
            select m.event_id, m.entity_id_at_t, e.issuer_cik, e.signal_date, e.g7_sic
            from evt.event_member m join evt.event e using (event_id)
            where e.priced and e.signal_date >= cast($start as DATE)
              and e.signal_date <= cast($end as DATE)
        ),
        events as (select distinct event_id, issuer_cik, signal_date from members),
        owners as (  -- each owner's entity at T, once per event
            select v.event_id, em.owner_cik, arg_max(em.entity_id, em.valid_from) as entity_at_t
            from events v join core.entity_member em
              on em.issuer_cik = v.issuer_cik and em.valid_from <= v.signal_date
            group by 1, 2
        )
        select distinct b.event_id, b.entity_id_at_t, b.issuer_cik, b.signal_date, b.g7_sic,
               p.accession, p.filing_date
        from members b
        join owners o on o.event_id = b.event_id and o.entity_at_t = b.entity_id_at_t
        join core.priced_purchase p on p.issuer_cik = b.issuer_cik
             and p.filing_date < b.signal_date and list_contains(p.owner_ciks, o.owner_cik)
             and p.g8_status <> 'skipped_unpriced'
        """,
        {"start": str(registered_value(params, "labelled_window_start")), "end": str(end)},
    )
    con.execute(
        """
        create or replace temp table _psrc as
        select b.event_id || '|' || b.accession || '|' || b.entity_id_at_t as id,
               b.event_id, b.accession, b.entity_id_at_t, b.issuer_cik, b.signal_date,
               b.filing_date, s.session as t_session, b.g7_sic as sic
        from _buyers b asof join core.session s on b.filing_date >= s.session
        """
    )
    window_returns(con, params, "_psrc", [primary], measures=("ind_ew",), end=end)
    _cost_inputs(con, params, "_psrc")
    costs.estimate(con, params, "_csrc")
    con.execute("begin transaction")
    try:
        con.execute(
            """
            create or replace table lab.purchase_outcome as
            select x.event_id, x.accession, x.entity_id_at_t, x.issuer_cik, x.filing_date,
                   r.entry_session, r.exit_session, r.gross, c.cost, r.gross - c.cost as net,
                   c.price_source
            from _res r join _psrc x on x.id = r.id
            left join _est c on c.id = r.id
            where r.exit_session < x.signal_date
            order by x.event_id, x.accession, x.entity_id_at_t
            """
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    for name in ("_src", "_psrc", "_csrc", "_buyers", "_res", "_est", "_w", "_win", "_px",
                 "_pos", "_dl", "_bench", "_etf", "_ind", "_fac", "_rets", "_part"):  # fmt: skip
        con.execute(f"drop table if exists {name}")
    return con.execute("select count(*) from lab.purchase_outcome").fetchone()[0]


def check_labels(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """W30: unique keys; every window inside the development period; entry after T."""
    end = development_end(params)
    problems = []
    dup = con.execute(
        "select count(*) from (select event_id, horizon, measure from lab.event_label "
        "group by all having count(*) > 1)"
    ).fetchone()[0]
    if dup:
        problems.append(f"{dup} duplicate label keys")
    late = con.execute(
        "select count(*) from lab.event_label where exit_session > cast(? as DATE)", [str(end)]
    ).fetchone()[0]
    if late:
        problems.append(f"{late} label windows end after {end}")
    early = con.execute(
        "select count(*) from lab.event_label l join evt.event e using (event_id) "
        "where l.entry_session <= e.t_session"
    ).fetchone()[0]
    if early:
        problems.append(f"{early} labels enter on or before T")
    f10 = con.execute(
        "select count(*) from lab.purchase_outcome o join evt.event e using (event_id) "
        "where o.exit_session >= e.signal_date or o.exit_session > cast(? as DATE)",
        [str(end)],
    ).fetchone()[0]
    if f10:
        problems.append(f"{f10} purchase outcomes end on or after their event's T")
    return problems
