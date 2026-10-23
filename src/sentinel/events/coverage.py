"""`coverage.md`: the data-quality report of feature 004 (SC-001, SC-002, FR-007, FR-014).

Aggregates only (counts and shares), never prices, so the report is committed with the feature.
Sections for delistings and company financials appear once those steps have run.
"""

from datetime import date
from pathlib import Path

import duckdb

from sentinel.config import registered_value
from sentinel.warehouse import table_exists

COVERAGE_TARGET = 0.90  # plan §6.7
G8_TARGET = 0.95  # plan §6.7
STATUSES = ("listed", "delisted", "unpriced_issuer")


def _pct(num, den) -> str:
    return f"{num / den:.1%}" if den else "–"


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def _price_coverage(con) -> list[str]:
    rows = con.execute(
        "select year, delisting_status, sum(events), sum(covered) from audit.price_coverage "
        "group by all order by all"
    ).fetchall()
    by_year: dict[int, dict[str, tuple[int, int]]] = {}
    for year, status, n, k in rows:
        by_year.setdefault(year, {})[status] = (n, k)
    table, totals = [], {s: [0, 0] for s in STATUSES}
    for year, cells in sorted(by_year.items()):
        line, n_all, k_all = [year], 0, 0
        for s in STATUSES:
            n, k = cells.get(s, (0, 0))
            totals[s][0] += n
            totals[s][1] += k
            n_all, k_all = n_all + n, k_all + k
            line.append(f"{_pct(k, n)} of {n:,}" if n else "–")
        table.append([*line, f"**{_pct(k_all, n_all)}** of {n_all:,}"])
    n_all = sum(v[0] for v in totals.values())
    k_all = sum(v[1] for v in totals.values())
    table.append(["**All**", *(f"{_pct(k, n)} of {n:,}" if n else "–" for n, k in totals.values()),
                  f"**{_pct(k_all, n_all)}** of {n_all:,}"])  # fmt: skip
    verdict = "meets" if n_all and k_all / n_all >= COVERAGE_TARGET else "misses"
    return [
        "## Price coverage (SC-001)",
        "",
        "Share of A and B1 events from 2012, before the floors, whose price series spans sessions "
        f"T−19 to T+1. Target ≥ {COVERAGE_TARGET:.0%}: overall **{_pct(k_all, n_all)}** "
        f"({verdict} the target). A shortfall is reported, never fixed by moving the window.",
        "",
        *_table(["Year", "Listed", "Delisted", "Unpriced issuer", "All"], table),
        "",
    ]


def _g8(con) -> list[str]:
    rows = con.execute(
        "select year, lines_checked, lines_passed, rate from audit.g8_rate "
        "order by year = 'total', year"
    ).fetchall()
    total = next((r for r in rows if r[0] == "total"), None)
    verdict = "meets" if total and total[3] is not None and total[3] >= G8_TARGET else "misses"
    return [
        "## G8 price check (SC-002)",
        "",
        "Clean-purchase lines at priced issuers whose reported price lies within the day's "
        f"as-traded range ± 10%. Target ≥ {G8_TARGET:.0%}: "
        f"**{_pct(total[2], total[1]) if total else '–'}** ({verdict} the target).",
        "",
        *_table(
            ["Year", "Lines checked", "Passed", "Rate"],
            [[y, f"{c:,}", f"{p:,}", _pct(p, c)] for y, c, p, _ in rows],
        ),  # fmt: skip
        "",
    ]


def _outcomes(con, params: dict) -> list[str]:
    start = registered_value(params, "labelled_window_start")
    rows = con.execute(
        'select "group", outcome, sum(n) from audit.event_funnel '
        "where year >= year(cast(? as DATE)) group by all order by all",
        [str(start)],
    ).fetchall()
    outcomes = sorted({r[1] for r in rows})
    cells = {(g, o): n for g, o, n in rows}
    table = [[g, *(f"{cells.get((g, o), 0):,}" for o in outcomes)] for g in ("A", "B1", "B2")]
    unpriced = con.execute(
        "select year, \"group\", n from audit.event_funnel where outcome = 'unpriced' "
        "and year >= year(cast(? as DATE)) order by all",
        [str(start)],
    ).fetchall()
    years = sorted({y for y, _, _ in unpriced})
    upc = {(y, g): n for y, g, n in unpriced}
    return [
        "## Final-event candidates by outcome, from 2012",
        "",
        "Each candidate's first applicable outcome: cooldown → G7 → priced → floors (research R7).",
        "",
        *_table(["Group", *outcomes], table),
        "",
        "## Unpriced events by year and group (FR-014)",
        "",
        "Kept and counted; their results are bounded at −100% and zero net abnormal return.",
        "",
        *(
            _table(
                ["Year", "A", "B1", "B2"],
                [[y, *(upc.get((y, g), 0) for g in ("A", "B1", "B2"))] for y in years],
            )  # fmt: skip
            if years
            else ["None."]
        ),
        "",
    ]


def _delistings(con) -> list[str]:
    if not table_exists(con, "core.delisting"):
        return ["## Delistings", "", "Not built yet (`sentinel delistings`).", ""]
    rows = con.execute(
        "select class, venue, count(*), any_value(delisting_return) from core.delisting "
        "group by all order by all"
    ).fetchall()
    return [
        "## Delistings (FR-017 – FR-019)",
        "",
        *_table(
            ["Class", "Venue", "Issuers", "Delisting return"],
            [[c, v, f"{n:,}", f"{r:.0%}"] for c, v, n, r in rows],
        ),  # fmt: skip
        "",
    ]


def _financials(con, params: dict) -> list[str]:
    if not table_exists(con, "core.xbrl_fact"):
        return ["## Company financials", "", "Not built yet (`sentinel company-facts`).", ""]
    start = str(registered_value(params, "labelled_window_start"))
    rows = con.execute(
        """
        with ev as (select event_id, issuer_cik, signal_date, year(signal_date) as year
                    from evt.event where signal_date >= cast(? as DATE)),
        has as (
            select e.event_id, e.year, f.concept from ev e
            join core.xbrl_fact f on f.issuer_cik = e.issuer_cik and f.filed <= e.signal_date
            group by all
        )
        select ev.year, count(distinct ev.event_id) as events, h.concept,
               count(distinct h.event_id) as with_value
        from ev left join has h on h.event_id = ev.event_id and h.year = ev.year
        group by all order by all
        """,
        [start],
    ).fetchall()
    concepts = ["shares_outstanding", "equity", "assets", "liabilities", "cash", "net_income"]
    years: dict[int, dict] = {}
    for year, events, concept, n in rows:
        years.setdefault(year, {"events": events})[concept] = n
    table = [[y, f"{v['events']:,}", *(_pct(v.get(c, 0), v["events"]) for c in concepts)]
             for y, v in sorted(years.items())]  # fmt: skip
    caps = con.execute(
        "select count(*), count(market_cap) from evt.event "
        "where priced and signal_date >= cast(? as DATE)",
        [start],
    ).fetchone()
    return [
        "## Company financials (FR-021, FR-022)",
        "",
        "Share of events from 2012 with a value first filed on or before T. Market capitalisation "
        f"exists for {_pct(caps[1], caps[0])} of priced events.",
        "",
        *_table(["Year", "Events", *concepts], table),
        "",
    ]


def write_report(con: duckdb.DuckDBPyConnection, params: dict, path: Path) -> None:
    lines = [
        "# Feature 004: coverage and data quality",
        "",
        f"Generated by `sentinel coverage` on {date.today()}. Aggregates only: no prices.",
        "",
        *_price_coverage(con),
        *_g8(con),
        *_outcomes(con, params),
        *_delistings(con),
        *_financials(con, params),
    ]
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
