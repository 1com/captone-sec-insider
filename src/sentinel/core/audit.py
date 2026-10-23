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
