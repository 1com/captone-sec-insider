"""Hand-audit sheets for entities and gates, and their summary (contracts/audit-sheets.md;
FR-025, SC-004).

Each sheet is a random sample drawn in Python with a fixed seed from keys sorted in SQL, so the
same warehouse always gives the same sheets. The researcher fills in `verdict` and `notes`;
existing sheets are never replaced without `force`, so completed verdicts are not lost.
"""

import csv
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa

from sentinel.core.gates import FILING_GATE, LINE_GATES

SEED = 2002
SIZE = 50
VERDICTS = ("correct", "wrong", "unclear")
FOOTNOTE_CHARS = 500
MAX_LINKING = 10  # linking filings listed per entity
EDGAR = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"

_HEAD, _TAIL = ["seed", "n"], ["edgar_link", "verdict", "notes"]
COLUMNS = {
    "entities": [*_HEAD, "issuer_cik", "issuer_name", "entity_id", "as_of", "members",
                 "linking_accessions", *_TAIL],
    "gates_excluded": [*_HEAD, "accession", "line_sk", "issuer_name", "filing_date",
                       "security_title", "shares", "price", "deciding_gate", "cited_footnotes",
                       *_TAIL],
    "gates_kept": [*_HEAD, "accession", "issuer_name", "filing_date", "entity_role", "value_usd",
                   "shares_before", "shares_after", "cited_footnotes", *_TAIL],
}  # fmt: skip

# Strata of the excluded sheet, in order: the deciding gate, with G4a and G4b together.
STRATA = {
    "g3_common": "G3",
    "g4a_no_checkbox": "G4",
    "g4b_no_plan_fn": "G4",
    "g5_no_offering_fn": "G5",
    "g6a_timely_valued": "G6a",
    FILING_GATE: "G6b",
}


class SheetsExist(Exception):
    """Audit sheets already exist; `force=True` replaces them, verdicts included."""


def _sample(rng: random.Random, keys: list, k: int) -> list:
    return rng.sample(keys, min(k, len(keys)))


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _link(issuer_cik: str, accession: str | None) -> str:
    return EDGAR.format(cik=issuer_cik, acc=accession.replace("-", "")) if accession else ""


def _footnotes(fn_ids: str) -> str:
    """SQL: the cited footnotes of a row with columns `accession`, `quarter` and `fn_ids`."""
    text = (
        f"case when length(n.footnote_txt) > {FOOTNOTE_CHARS} "
        f"then left(n.footnote_txt, {FOOTNOTE_CHARS - 1}) || '…' else n.footnote_txt end"
    )
    return f"""(
        select string_agg(n.footnote_id || ': ' || {text}, ' | ' order by n.footnote_id)
        from stg.footnotes n
        where n.accession_number = x.accession and n.quarter = x.quarter
          and list_contains({fn_ids}, n.footnote_id)
    )"""


def _entities(con: duckdb.DuckDBPyConnection, rng: random.Random) -> list[list]:
    """Multi-member entities at their latest membership date."""
    con.execute(
        """
        create or replace temp view _current as
        select issuer_cik, owner_cik, entity_id from core.entity_member
        qualify row_number() over (partition by issuer_cik, owner_cik order by valid_from desc) = 1
        """
    )
    keys = [
        r[0]
        for r in con.execute(
            "select entity_id from _current group by 1 having count(*) >= 2 order by 1"
        ).fetchall()
    ]
    con.register("_pick", pa.table({"entity_id": pa.array(_sample(rng, keys, SIZE), pa.string())}))
    try:
        rows = con.execute(
            """
            with members as (select c.* from _current c join _pick using (entity_id)),
            as_of as (
                select entity_id, max(valid_from) as as_of
                from core.entity_member join _pick using (entity_id) group by 1
            ),
            named as (
                select f.issuer_cik, o.rptownercik as owner_cik,
                       list(o.rptownername order by f.filing_date desc, o.rptownername)[1]
                           as name
                from core.filing f
                join stg.reportingowner o
                  on o.accession_number = f.accession and o.quarter = f.quarter
                join members m on m.issuer_cik = f.issuer_cik and m.owner_cik = o.rptownercik
                group by all
            ),
            roled as (
                select ma.*, r.role
                from (select * from members join as_of using (entity_id)) ma
                asof left join core.owner_role r
                  on ma.issuer_cik = r.issuer_cik and ma.owner_cik = r.owner_cik
                 and ma.as_of >= r.valid_from
            ),
            listed as (
                select r.entity_id, any_value(r.issuer_cik) as issuer_cik,
                       any_value(r.as_of) as as_of,
                       string_agg(r.owner_cik || ': ' || coalesce(n.name, '?')
                                  || ' (' || coalesce(r.role, '?') || ')', ' | '
                                  order by length(r.owner_cik), r.owner_cik) as members
                from roled r left join named n using (issuer_cik, owner_cik)
                group by r.entity_id
            ),
            changes as (  -- dates on which any member's entity was created or changed
                select distinct e.issuer_cik, m.entity_id, e.valid_from
                from core.entity_member e
                join members m using (issuer_cik, owner_cik)
            ),
            joint as (  -- multi-owner filings on those dates that include a member
                select distinct c.entity_id, f.accession, f.filing_date
                from changes c
                join core.filing f on f.issuer_cik = c.issuer_cik and f.filing_date = c.valid_from
                join stg.reportingowner o
                  on o.accession_number = f.accession and o.quarter = f.quarter
                join members m
                  on m.entity_id = c.entity_id and m.owner_cik = o.rptownercik
                where (select count(distinct o2.rptownercik) from stg.reportingowner o2
                       where o2.accession_number = f.accession and o2.quarter = f.quarter) >= 2
            ),
            linking as (
                select entity_id, count(*) as n_linking,
                       list(accession || ' (' || cast(filing_date as VARCHAR) || ')'
                            order by filing_date, accession) as linking,
                       list(accession order by filing_date desc, accession desc)[1] as latest
                from joint group by entity_id
            ),
            issuer as (
                select issuer_cik,
                       list(issuer_name order by filing_date desc, accession desc)[1]
                           as issuer_name
                from core.filing where issuer_cik in (select issuer_cik from members)
                group by 1
            )
            select l.issuer_cik, i.issuer_name, l.entity_id, l.as_of, l.members,
                   k.linking, k.n_linking, k.latest
            from listed l
            left join linking k using (entity_id)
            left join issuer i using (issuer_cik)
            order by l.entity_id
            """
        ).fetchall()
    finally:
        con.unregister("_pick")
    out = []
    for issuer_cik, name, entity_id, as_of, members, linking, n_linking, latest in rows:
        shown = " | ".join((linking or [])[:MAX_LINKING])
        if (n_linking or 0) > MAX_LINKING:
            shown += f" | … and {n_linking - MAX_LINKING} more"
        out.append([issuer_cik, name, entity_id, as_of, members, shown, _link(issuer_cik, latest)])
    return out


def _excluded(con: duckdb.DuckDBPyConnection, rng: random.Random) -> list[list]:
    """Code-P acquisitions on original Form 4s that failed G3–G6b, stratified by deciding gate."""
    deciding = " ".join(f"when not t.{g} then '{g}'" for g in LINE_GATES[2:])
    con.execute(
        f"""
        create or replace temp view _excluded as
        select * from (
            select t.*, case {deciding}
                        when c.accession is null then '{FILING_GATE}' end as deciding_gate
            from core.transaction t left join core.clean_purchase c using (accession)
            where t.g1_form4 and t.g2_purchase
        ) where deciding_gate is not null
        """
    )
    keys = con.execute(
        "select deciding_gate, accession, line_sk from _excluded order by all"
    ).fetchall()
    strata = list(dict.fromkeys(STRATA.values()))
    pools = {s: [k[1:] for k in keys if STRATA[k[0]] == s] for s in strata}
    picked = {s: _sample(rng, pools[s], SIZE // len(strata)) for s in strata}
    chosen = {k for ks in picked.values() for k in ks}
    rest = sorted(k for s in strata for k in pools[s] if k not in chosen)
    extra = _sample(rng, rest, SIZE - len(chosen))
    order = [(s, k) for s in strata for k in sorted(picked[s])] + [(None, k) for k in extra]
    con.register(
        "_pick",
        pa.table(
            {
                "rank": pa.array(range(len(order)), pa.int64()),
                "accession": pa.array([k[0] for _, k in order], pa.string()),
                "line_sk": pa.array([k[1] for _, k in order], pa.string()),
            }
        ),
    )
    try:
        rows = con.execute(
            f"""
            select x.accession, x.line_sk, f.issuer_name, x.filing_date, x.security_title,
                   x.shares, x.price, x.deciding_gate, {_footnotes("x.fn_ids")}, x.issuer_cik
            from _pick p join _excluded x using (accession, line_sk)
            join core.filing f using (accession)
            order by p.rank
            """
        ).fetchall()
    finally:
        con.unregister("_pick")
    return [[*r[:9], _link(r[9], r[0])] for r in rows]


def _kept(con: duckdb.DuckDBPyConnection, rng: random.Random) -> list[list]:
    keys = [
        r[0] for r in con.execute("select accession from core.clean_purchase order by 1").fetchall()
    ]
    con.register("_pick", pa.table({"accession": pa.array(_sample(rng, keys, SIZE), pa.string())}))
    try:
        rows = con.execute(
            f"""
            with x as (
                select c.*, (
                    select list_sort(list_distinct(flatten(list(t.fn_ids))))
                    from core.transaction t where t.accession = c.accession and t.passes_lines
                ) as fn_ids
                from core.clean_purchase c join _pick using (accession)
            )
            select x.accession, f.issuer_name, x.filing_date, x.entity_role, x.value_usd,
                   x.shares_before, x.shares_after, {_footnotes("x.fn_ids")}, x.issuer_cik
            from x join core.filing f using (accession)
            order by x.filing_date, x.accession
            """
        ).fetchall()
    finally:
        con.unregister("_pick")
    return [[*r[:8], _link(r[8], r[0])] for r in rows]


def make_sheets(
    con: duckdb.DuckDBPyConnection, out_dir: Path, seed: int = SEED, force: bool = False
) -> dict[str, int]:
    """Write the three sheets; returns the rows per sheet. Raises SheetsExist unless `force`."""
    paths = {sheet: out_dir / f"{sheet}.csv" for sheet in COLUMNS}
    existing = [p.name for p in paths.values() if p.exists()]
    if existing and not force:
        raise SheetsExist(f"{', '.join(existing)} in {out_dir} (use --force to replace)")
    builders = {"entities": _entities, "gates_excluded": _excluded, "gates_kept": _kept}
    sheets = {sheet: build(con, random.Random(seed)) for sheet, build in builders.items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    for sheet, rows in sheets.items():
        with paths[sheet].open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS[sheet])
            for n, row in enumerate(rows, start=1):
                writer.writerow([seed, n, *(_cell(v) for v in row), "", ""])
    return {sheet: len(rows) for sheet, rows in sheets.items()}


@dataclass(frozen=True)
class SheetSummary:
    rows: int
    correct: int
    wrong: int
    unclear: int
    blank: int
    invalid: int  # anything other than the three verdicts

    @property
    def agreement(self) -> float | None:
        judged = self.correct + self.wrong
        return self.correct / judged if judged else None


def summarize(out_dir: Path) -> dict[str, SheetSummary]:
    """Verdict counts per sheet. A missing sheet raises FileNotFoundError."""
    out = {}
    for sheet in COLUMNS:
        with (out_dir / f"{sheet}.csv").open(
            newline="", encoding="utf-8-sig"
        ) as f:  # Excel adds a BOM
            verdicts = [(row["verdict"] or "").strip().lower() for row in csv.DictReader(f)]
        counts = {v: verdicts.count(v) for v in (*VERDICTS, "")}
        out[sheet] = SheetSummary(
            rows=len(verdicts),
            correct=counts["correct"],
            wrong=counts["wrong"],
            unclear=counts["unclear"],
            blank=counts[""],
            invalid=len(verdicts) - sum(counts.values()),
        )
    return out


# --- D45: issuers whose signal-filing header has no SIC code ----------------------------------

NO_SIC_SHEET = "d45_no_sic"
NO_SIC_SIZE = 30  # D45: 30 companies are checked by hand
NO_SIC_FALLBACK_AT = 3  # D45: this many operating companies or more → current-SIC fallback (§11)
NO_SIC_VERDICTS = ("investment_vehicle", "operating_company", "unclear")
NO_SIC_COLUMNS = [*_HEAD, "issuer_cik", "issuer_name", "events", "first_signal", "last_signal",
                  "groups", *_TAIL]  # fmt: skip
COMPANY_LINK = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&owner=include"


def _no_sic_events(start: str) -> str:
    return f"""
        select e.*, h.sic from evt.prelim_event e
        join core.filing_header h on h.accession = e.signal_accession
        where e.signal_date >= DATE '{start}'
    """


def no_sic_counts(con: duckdb.DuckDBPyConnection, start: str) -> list[tuple[int, str, int, int]]:
    """(year, group, events with a header, of which without SIC) from the labelled start."""
    return con.execute(
        f"""
        select year(signal_date), "group", count(*), count(*) filter (where sic is null)
        from ({_no_sic_events(start)}) group by all order by all
        """
    ).fetchall()


def make_no_sic_sheet(
    con: duckdb.DuckDBPyConnection, out_dir: Path, start: str, seed: int = SEED, force=False
) -> int:
    """`d45_no_sic.csv`: 30 random companies with a no-SIC signal filing, to classify by hand."""
    path = out_dir / f"{NO_SIC_SHEET}.csv"
    if path.exists() and not force:
        raise SheetsExist(f"{path.name} in {out_dir} (use --force to replace)")
    keys = [
        r[0]
        for r in con.execute(
            f"select distinct issuer_cik from ({_no_sic_events(start)}) "
            "where sic is null order by 1"
        ).fetchall()
    ]
    picked = _sample(random.Random(seed), keys, NO_SIC_SIZE)
    con.register("_pick", pa.table({"issuer_cik": pa.array(picked, pa.string())}))
    try:
        rows = con.execute(
            f"""
            with ev as (select * from ({_no_sic_events(start)}) where sic is null),
            names as (
                select issuer_cik,
                       list(issuer_name order by filing_date desc, accession desc)[1] as name
                from core.filing where issuer_cik in (select issuer_cik from _pick) group by 1
            )
            select e.issuer_cik, n.name, count(*), min(e.signal_date), max(e.signal_date),
                   string_agg(distinct e."group", ', ' order by e."group")
            from ev e join _pick using (issuer_cik) left join names n using (issuer_cik)
            group by e.issuer_cik, n.name order by e.issuer_cik
            """
        ).fetchall()
    finally:
        con.unregister("_pick")
    out_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(NO_SIC_COLUMNS)
        for n, (cik, *rest) in enumerate(rows, start=1):
            link = COMPANY_LINK.format(cik=cik)
            writer.writerow([seed, n, cik, *(_cell(v) for v in rest), link, "", ""])
    return len(rows)


def summarize_no_sic(out_dir: Path) -> dict[str, int] | None:
    """Verdict counts of the D45 sheet, or None if it does not exist yet."""
    path = out_dir / f"{NO_SIC_SHEET}.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8-sig") as f:
        verdicts = [(row["verdict"] or "").strip().lower() for row in csv.DictReader(f)]
    counts = {v: verdicts.count(v) for v in (*NO_SIC_VERDICTS, "")}
    counts["invalid"] = len(verdicts) - sum(counts.values())
    counts["blank"] = counts.pop("")
    return counts


# --- Feature 004: the golden set of final events (FR-016, SC-003) ------------------------------

GOLDEN_SHEET = "golden_set"
GOLDEN_SEED = 20261025
GOLDEN_SIZE = 30
GOLDEN_PER_GROUP = 10
GOLDEN_CHECKS = ("insiders_ok", "dates_ok", "amounts_ok")
GOLDEN_VERDICTS = ("yes", "no", "unclear")
GOLDEN_COLUMNS = [*_HEAD, "event_id", "group", "issuer_cik", "issuer_name", "signal_date",
                  "entry_session", "accession", "filing_date", "entity_id_at_t",
                  "entity_role_at_t", "owner_names", "value_usd", "trade_dates", "prices",
                  "edgar_link", *GOLDEN_CHECKS, "notes"]  # fmt: skip


def _golden_pick(con: duckdb.DuckDBPyConnection, seed: int) -> list[str]:
    """10 events per group from the labelled window; a shortfall is filled from A, then any."""
    rng = random.Random(seed)
    by_group: dict[str, list[str]] = {}
    for event_id, group in con.execute(
        'select event_id, "group" from evt.event where in_labelled_window order by 2, 1'
    ).fetchall():
        by_group.setdefault(group, []).append(event_id)
    picked = []
    for group in ("A", "B1", "B2"):
        picked += _sample(rng, by_group.get(group, []), GOLDEN_PER_GROUP)
    for pool in (by_group.get("A", []), sorted(e for es in by_group.values() for e in es)):
        rest = [e for e in pool if e not in picked]
        picked += _sample(rng, rest, max(0, GOLDEN_SIZE - len(picked)))
    return picked


def make_golden_sheet(
    con: duckdb.DuckDBPyConnection, out_dir: Path, seed: int = GOLDEN_SEED, force: bool = False
) -> int:
    """`golden_set.csv`: 30 final events, one row per member purchase; returns the events."""
    path = out_dir / f"{GOLDEN_SHEET}.csv"
    if path.exists() and not force:
        raise SheetsExist(f"{path.name} in {out_dir} (use --force to replace)")
    picked = _golden_pick(con, seed)
    order = {e: i for i, e in enumerate(sorted(picked, key=lambda e: (e.split(":")[1], e)))}
    con.register("_pick", pa.table({"event_id": pa.array(picked, pa.string())}))
    try:
        rows = con.execute(
            """
            with names as (
                select issuer_cik,
                       list(issuer_name order by filing_date desc, accession desc)[1] as name
                from core.filing
                where issuer_cik in (select issuer_cik from evt.event
                                     where event_id in (select event_id from _pick))
                group by 1
            ),
            owners as (
                select accession_number as accession,
                       string_agg(distinct rptownername, '; ' order by rptownername) as owner_names
                from stg.reportingowner
                where accession_number in (select accession from evt.event_member
                                           where event_id in (select event_id from _pick))
                group by 1
            ),
            lines as (
                select t.accession,
                       string_agg(distinct cast(t.trans_date as VARCHAR), '; ') as trade_dates,
                       string_agg(cast(t.price as VARCHAR), '; ' order by t.line_sk) as prices
                from core.transaction t
                where t.passes_lines and t.accession in (
                    select accession from evt.event_member
                    where event_id in (select event_id from _pick))
                group by 1
            )
            select e.event_id, e."group", e.issuer_cik, n.name, e.signal_date, e.entry_session,
                   m.accession, f.filing_date, m.entity_id_at_t, m.entity_role_at_t,
                   o.owner_names, m.value_usd, l.trade_dates, l.prices
            from evt.event e join _pick using (event_id)
            join evt.event_member m using (event_id)
            join core.filing f on f.accession = m.accession
            left join names n on n.issuer_cik = e.issuer_cik
            left join owners o on o.accession = m.accession
            left join lines l on l.accession = m.accession
            order by e.event_id, f.filing_date, m.accession
            """
        ).fetchall()
    finally:
        con.unregister("_pick")
    rows.sort(key=lambda r: (order[r[0]], r[7], r[6]))
    out_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(GOLDEN_COLUMNS)
        for row in rows:
            link = _link(row[2], row[6])
            blanks = [""] * (len(GOLDEN_CHECKS) + 1)
            writer.writerow([seed, order[row[0]] + 1, *(_cell(v) for v in row), link, *blanks])
    return len(picked)


@dataclass(frozen=True)
class GoldenSummary:
    events: int
    all_yes: int
    with_no: int
    unclear: int
    blank: int  # events whose checks are not all filled in

    @property
    def agreement(self) -> float | None:
        judged = self.events - self.blank
        return self.all_yes / judged if judged else None


def summarize_golden(out_dir: Path) -> GoldenSummary:
    """Per event (its first row holds the checks): all three `yes`, any `no`, unclear, blank."""
    with (out_dir / f"{GOLDEN_SHEET}.csv").open(newline="", encoding="utf-8-sig") as f:
        first: dict[str, dict] = {}
        for row in csv.DictReader(f):
            first.setdefault(row["event_id"], row)
    counts = {"all_yes": 0, "with_no": 0, "unclear": 0, "blank": 0}
    for row in first.values():
        values = [(row[c] or "").strip().lower() for c in GOLDEN_CHECKS]
        if any(v not in GOLDEN_VERDICTS for v in values):
            counts["blank"] += 1
        elif "no" in values:
            counts["with_no"] += 1
        elif "unclear" in values:
            counts["unclear"] += 1
        else:
            counts["all_yes"] += 1
    return GoldenSummary(events=len(first), **counts)


# --- Feature 004: delisting classifications (FR-020, SC-004) -----------------------------------

DELISTING_SHEET = "delisting_audit"
DELISTING_SEED = 20261024
DELISTING_PER_CLASS = 10
DELISTING_CLASSES = ("acquired", "performance", "unknown")
DELISTING_VERDICTS = ("agree", "disagree", "unclear")
FILINGS_LINK = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    "&type=&dateb=&owner=include&count=100"
)
DELISTING_COLUMNS = [*_HEAD, "issuer_cik", "issuer_name", "last_session", "class", "venue",
                     "delisting_return", "evidence_form", "evidence_date", "evidence_link",
                     "filings_link", "verdict", "true_class", "notes"]  # fmt: skip


def make_delisting_sheet(
    con: duckdb.DuckDBPyConnection, out_dir: Path, seed: int = DELISTING_SEED, force: bool = False
) -> int:
    """`delisting_audit.csv`: 10 issuers per class (remap counts towards the fill-in pool); a
    shortfall is filled from the other classes. No prices: `last_session` is a date."""
    path = out_dir / f"{DELISTING_SHEET}.csv"
    if path.exists() and not force:
        raise SheetsExist(f"{path.name} in {out_dir} (use --force to replace)")
    rng = random.Random(seed)
    by_class: dict[str, list[str]] = {}
    for cik, cls in con.execute(
        "select issuer_cik, class from core.delisting order by 2, 1"
    ).fetchall():
        by_class.setdefault(cls, []).append(cik)
    picked = []
    for cls in DELISTING_CLASSES:
        picked += _sample(rng, by_class.get(cls, []), DELISTING_PER_CLASS)
    rest = sorted(c for cs in by_class.values() for c in cs if c not in picked)
    picked += _sample(rng, rest, max(0, DELISTING_PER_CLASS * 3 - len(picked)))
    con.register("_pick", pa.table({"issuer_cik": pa.array(picked, pa.string())}))
    try:
        rows = con.execute(
            """
            with names as (
                select issuer_cik,
                       list(issuer_name order by filing_date desc, accession desc)[1] as name
                from core.filing where issuer_cik in (select issuer_cik from _pick) group by 1
            )
            select d.issuer_cik, n.name, d.last_session, d.class, d.venue, d.delisting_return,
                   d.evidence_form, d.evidence_date, d.evidence_accession
            from core.delisting d join _pick using (issuer_cik)
            left join names n on n.issuer_cik = d.issuer_cik
            order by d.class, d.issuer_cik
            """
        ).fetchall()
    finally:
        con.unregister("_pick")
    out_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(DELISTING_COLUMNS)
        for n, (cik, name, last, cls, venue, ret, form, filed, acc) in enumerate(rows, start=1):
            writer.writerow([
                seed, n, cik, _cell(name), _cell(last), cls, venue, f"{ret:.2f}", _cell(form),
                _cell(filed), _link(cik, acc), FILINGS_LINK.format(cik=cik), "", "", "",
            ])  # fmt: skip
    return len(rows)


def summarize_delistings(out_dir: Path) -> dict[str, dict[str, int]]:
    """Verdict counts per class, plus an `all` row."""
    with (out_dir / f"{DELISTING_SHEET}.csv").open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        verdict = (row["verdict"] or "").strip().lower()
        verdict = (
            verdict if verdict in DELISTING_VERDICTS else ("blank" if not verdict else "invalid")
        )
        for key in (row["class"], "all"):
            counts = out.setdefault(
                key, dict.fromkeys((*DELISTING_VERDICTS, "blank", "invalid"), 0)
            )
            counts[verdict] += 1
    return out


# --- Feature 004: market capitalisation check (SC-005) -----------------------------------------

MARKET_CAP_SHEET = "market_caps"
MARKET_CAP_COLUMNS = ["ticker", "issuer_cik", "session", "shares_outstanding", "shares_filed",
                      "market_cap_pipeline", "market_cap_yahoo", "fetched_at", "ratio",
                      "within_5pct"]  # fmt: skip


def _yahoo_market_cap(ticker: str) -> float | None:
    import yfinance

    value = yfinance.Ticker(ticker).fast_info["market_cap"]
    return float(value) if value else None


def make_market_cap_sheet(
    con: duckdb.DuckDBPyConnection, paths, params: dict, fetch=None
) -> list[list]:
    """`market_caps.csv`: this pipeline's market cap at the latest session (as-traded close ×
    latest shares filed on or before it) against Yahoo's, for `ops.market_cap_examples`. Yahoo's
    value is fetched once and stored under `data/raw/yahoo/market_cap/`; later runs are offline.
    Values are rounded to $1 million; no prices are written."""
    import json
    import os
    from datetime import UTC, datetime

    from sentinel.ingest import manifest

    fetch = fetch or _yahoo_market_cap
    book = manifest.Manifest(paths.manifest)
    store = paths.yahoo / "market_cap"
    out = []
    for ticker in params["ops"]["market_cap_examples"]:
        row = con.execute(
            """
            with s as (select issuer_cik from core.price_series
                       where chosen and price_source = 'yahoo' and ticker = $t),
            last as (select d.issuer_cik, d.session, d.close from core.price_daily d
                     join s using (issuer_cik) order by d.session desc limit 1)
            select l.issuer_cik, l.session, l.close, f.value, f.filed from last l
            left join lateral (
                select value, filed from core.xbrl_fact x
                where x.issuer_cik = l.issuer_cik and x.concept = 'shares_outstanding'
                  and x.filed <= l.session
                order by x.filed desc, x.period_end desc limit 1
            ) f on true
            """,
            {"t": ticker},
        ).fetchone()
        if row is None:
            continue
        cik, session, close, shares, filed = row
        path = store / f"{ticker}.json"
        if not path.exists():
            store.mkdir(parents=True, exist_ok=True)
            now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            payload = json.dumps({"ticker": ticker, "market_cap": fetch(ticker), "fetched_at": now})
            part = path.with_name(path.name + ".part")
            part.write_text(payload, encoding="utf-8")
            os.replace(part, path)
            os.chmod(path, 0o444)
            book.add(
                manifest.ManifestEntry(
                    path=path.relative_to(paths.data_raw).as_posix(), source="yahoo",
                    key=f"market_cap/{ticker}", role="original",
                    url=f"yfinance.Ticker({ticker}).fast_info['market_cap']", fetched_at=now,
                    bytes=path.stat().st_size, sha256=manifest.sha256_file(path),
                    http_last_modified=None, http_etag=None, tool="sentinel",
                )
            )  # fmt: skip
        stored = json.loads(path.read_text(encoding="utf-8"))
        ours = close * shares if shares else None
        theirs = stored["market_cap"]
        ratio = ours / theirs if ours and theirs else None
        out.append([
            ticker, cik, session, shares, filed,
            round(ours, -6) if ours else None, round(theirs, -6) if theirs else None,
            stored["fetched_at"], round(ratio, 4) if ratio else None,
            None if ratio is None else abs(ratio - 1) <= 0.05,
        ])  # fmt: skip
    out_dir = paths.audits_004
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{MARKET_CAP_SHEET}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(MARKET_CAP_COLUMNS)
        writer.writerows([[_cell(v) for v in r] for r in out])
    return out
