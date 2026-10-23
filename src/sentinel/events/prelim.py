"""Step 5: preliminary events, used to choose which symbols to price (research.md R6; FR-014).

At each date T on which an issuer has a clean purchase, the window is the clean purchases filed in
[T − (cluster_window − 1), T]. Every purchase's buyer is its entity as of T, with the entity's
seniority as of T, so owners who merged on or before T count once and a promotion on or before T
counts. The window's buyers and total value decide the group:
- A: at least 2 entities, at least one of them an officer or director (seniority ≥ 2);
- B1: one entity whose seniority is CEO/CFO (4);
- B2: one entity whose seniority is officer or director (3 or 2);
each with a total of at least `registered.cluster_min_value`. After an event, the issuer cannot
have another event in the same group for `rules.prelim_cooldown_calendar_days`.
"""

from datetime import date

import duckdb
import pyarrow as pa

from sentinel.config import registered_value
from sentinel.core import entities
from sentinel.warehouse import exact_sum, scope

DIRECTOR = entities.SENIORITY["director"]
CEO_CFO = entities.SENIORITY["ceo_cfo"]
PRELIM_COOLDOWN = object()  # `keep` default: the preliminary calendar-day cooldown


def _cooldown(candidates: list[tuple[str, str, date]], days: int) -> list[tuple[str, str, date]]:
    """Keep (issuer, group, T) in date order unless the issuer's last kept event in the group is
    less than `days` earlier. Suppressed candidates do not restart the cooldown."""
    kept, last = [], {}
    for issuer, group, t in sorted(candidates, key=lambda c: (c[0], c[1], c[2])):
        previous = last.get((issuer, group))
        if previous is None or (t - previous).days >= days:
            kept.append((issuer, group, t))
            last[(issuer, group)] = t
    return kept


def find_events(
    con: duckdb.DuckDBPyConnection,
    params: dict,
    purchases: str = "core.clean_purchase",
    cutoff=None,
    issuers=None,
    officer_or_director: bool = True,
    keep=PRELIM_COOLDOWN,
    start=None,
) -> int:
    """Detect events in `purchases` into temp tables `_events` and `_event_members`.

    `purchases` needs `accession`, `issuer_cik`, `filing_date`, `owner_ciks` and `value_usd`.
    `officer_or_director=False` drops the A rule's officer/director condition (comparison only).
    `keep` chooses which (issuer, group, T) candidates become events: by default the preliminary
    cooldown; None keeps every candidate (final detection applies its own, feature 004); or a
    function of the candidate list. `start` is the earliest T (earlier purchases still count in
    the window).
    """
    where, args = scope(cutoff, issuers, alias="p")
    window = registered_value(params, "cluster_window")
    min_value = registered_value(params, "cluster_min_value")
    con.execute(
        f"""
        create or replace temp table _window as
        with p as (
            select accession, issuer_cik, filing_date, value_usd, owner_ciks[1] as owner_cik
            from {purchases} p where {where}
        ),
        dates as (
            select distinct issuer_cik, filing_date as t from p
            where $start is null or filing_date >= cast($start as DATE)
        )
        select d.issuer_cik, d.t, p.accession, p.filing_date, p.value_usd, p.owner_cik
        from dates d
        join p on p.issuer_cik = d.issuer_cik
              and p.filing_date between d.t - {window - 1} and d.t
        """,
        args | {"start": None if start is None else str(start)},
    )
    entities.resolve_entities(con, "_window", "_window_entity")
    a_seniority = DIRECTOR if officer_or_director else 0
    candidates = con.execute(
        f"""
        select issuer_cik, case
                   when n >= 2 and top >= {a_seniority} then 'A'
                   when n = 1 and top = {CEO_CFO} then 'B1'
                   when n = 1 and top >= {DIRECTOR} then 'B2' end as grp, t
        from (
            select issuer_cik, t, count(distinct entity_id) as n, {exact_sum("value_usd")} as total,
                   max(entity_seniority) as top
            from _window_entity group by issuer_cik, t
        )
        where total >= $min_value and grp is not null
        """,
        {"min_value": min_value},
    ).fetchall()
    if keep is PRELIM_COOLDOWN:
        kept = _cooldown(candidates, params["rules"]["prelim_cooldown_calendar_days"])
    elif keep is None:
        kept = sorted(candidates)
    else:
        kept = keep(candidates)
    con.register(
        "_kept",
        pa.table(
            {
                "issuer_cik": pa.array([k[0] for k in kept], pa.string()),
                "grp": pa.array([k[1] for k in kept], pa.string()),
                "t": pa.array([k[2] for k in kept], pa.date32()),
            }
        ),
    )
    role = " ".join(f"when {n} then '{r}'" for r, n in entities.SENIORITY.items())
    try:
        con.execute(
            f"""
            create or replace temp table _event_members as
            select k.issuer_cik || ':' || k.grp || ':' || cast(k.t as VARCHAR) as event_id,
                   k.issuer_cik, k.grp, k.t, w.accession, w.filing_date,
                   w.entity_id as entity_id_at_t,
                   case w.entity_seniority {role} end as entity_role_at_t,
                   w.entity_seniority, w.value_usd
            from _kept k join _window_entity w using (issuer_cik, t)
            """
        )
    finally:
        con.unregister("_kept")
    con.execute(
        f"""
        create or replace temp table _events as
        with priced as (
            select accession, bool_and(coalesce(price >= $floor, false)) as ok
            from core.transaction
            where passes_lines and accession in (select accession from _event_members)
            group by accession
        )
        select m.event_id, any_value(m.issuer_cik) as issuer_cik, any_value(m.grp) as "group",
               any_value(m.t) as signal_date,
               max(m.accession) filter (where m.filing_date = m.t) as signal_accession,
               count(distinct m.entity_id_at_t) as n_entities,
               {exact_sum("m.value_usd")} as total_value_usd,
               max(m.entity_seniority) as max_seniority,
               any_value(m.t) >= cast($start as DATE) as in_labelled_window,
               bool_and(coalesce(pr.ok, false)) as passes_price_standin
        from _event_members m left join priced pr using (accession)
        group by m.event_id
        """,
        {
            "floor": params["provisional"]["price_standin_floor"],
            "start": str(registered_value(params, "labelled_window_start")),
        },
    )
    return len(kept)


def detect_prelim(
    con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None
) -> dict[str, int]:
    """Recreate `evt.prelim_event` and `evt.prelim_event_member`; returns events per group."""
    con.execute("begin transaction")
    try:
        find_events(con, params, cutoff=cutoff, issuers=issuers)
        con.execute("create or replace table evt.prelim_event as select * from _events")
        con.execute(
            "create or replace table evt.prelim_event_member as "
            "select event_id, accession, entity_id_at_t, entity_role_at_t, value_usd "
            "from _event_members"
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    for name in ("_window", "_window_entity", "_events", "_event_members"):
        con.execute(f"drop table if exists {name}")
    return dict(con.execute('select "group", count(*) from evt.prelim_event group by 1').fetchall())
