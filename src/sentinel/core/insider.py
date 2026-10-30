"""Layer 3b: the insider tracker's tables, from the Form 4 data sets (`stg_sec_form4`) and the
filings fetched since the last set (`stg_sec_form4_daily`), read as one (`union_sql`).

The rules are v1's, now in `config/tracker.yaml`. v2 drops the study they were written for (V2-4),
so here they decide what the tracker shows: who bought or sold, in which role, how much, when, and
when several insiders bought together.

- `core.insider_filing`: one row per Form 3/4/5 accession, from the first quarter that lists it,
  with `known_at` (the `core.filing` rule, the acceptance time from the filing's header or its
  daily copy).
- `core.form4_reconciliation`: accessions in both a data set and the daily filings whose two
  versions differ (owners, line counts, values), which checks the daily parser.
- `core.insider_entity_member`: owners who appear together on any filing for an issuer (a fund and
  its general partner, a person and their trust) are one entity from that filing's date on.
  Components only merge, so the history is a short list of changes per issuer: a row whenever an
  owner's entity id is created or changes. The id is `"{issuer}:{lowest owner CIK}"`, and an
  owner's entity at T is its latest row with `valid_from <= T`.
- `core.insider_owner_role`: role intervals per owner and issuer (CEO/CFO, officer, director, 10%
  owner, other), from each filing's relationship flags and title.
- `core.insider_trade`: every non-derivative line with v1's gate flags: G1 an original Form 4; G2
  an open-market purchase (`g2_sale`: an open-market sale); G3 common stock; G4a no 10b5-1
  checkbox; G4b no plan footnote; G5 no offering footnote; G6a filed on time, with a value.
  Footnote screens read only the footnotes the line itself cites. A line has a typo in its price
  or shares when its price per share is more than 10 times above or below the stock's as-traded
  close on or before the filing date, or when it is worth more than the whole company (that close
  times the share count known by the filing date): its `value_usd` is missing and `value_typo` is
  set (V2-24); the line itself stays.
- `core.insider_activity`: per filing and side (buy or sell), its open-market lines (G1, G2, G3,
  G6a): value, shares, trade dates, whether any line was planned or part of an offering, the
  entity and its role at the filing date, and the holdings before and after the filing. `clean`
  marks v1's clean purchases: the buy lines passing every gate total at least
  `purchase.min_value_usd` (G6b).
- `core.insider_funnel`: per quarter, lines through each purchase gate in order, then filings.
- `core.insider_cluster`: each day on which an issuer's clean purchases filed in the window ending
  that day form a group: A, at least `min_entities` buyers, one an officer or director; B1, one
  CEO or CFO; B2, one officer or director; each with at least `min_value_usd` in total. Buyers are
  entities as of that day. `starts_event` marks the days with no event of the same group in the
  `cooldown_days` before (later days of a run do not restart the cooldown).
"""

from datetime import date
from itertools import groupby
from operator import itemgetter

import duckdb
import pyarrow as pa

from sentinel import db
from sentinel.config import Paths, tracker
from sentinel.core.filings import same_day_or_next
from sentinel.staging.sec_form4 import TABLE_SPECS
from sentinel.staging.sec_form4_daily import has_daily, union_sql

BATCH_ROWS = 200_000  # input rows turned into Python objects at a time
FLUSH_ROWS = 500_000  # membership rows buffered before an insert
SENIORITY = {"ceo_cfo": 4, "officer": 3, "director": 2, "ten_pct": 1, "other": 0}
DIRECTOR, CEO_CFO = SENIORITY["director"], SENIORITY["ceo_cfo"]
ROLE = " ".join(f"when {n} then '{r}'" for r, n in SENIORITY.items())  # SQL: seniority → role
LINE_GATES = (
    "g1_form4",
    "g2_purchase",
    "g3_common",
    "g4a_no_checkbox",
    "g4b_no_plan_fn",
    "g5_no_offering_fn",
    "g6a_timely_valued",
)
FILING_GATE = "g6b_min_value"
_FN_COLUMNS = [c.lower() for c in TABLE_SPECS["NONDERIV_TRANS"].columns if c.endswith("_FN")]


def _filing_owners(con) -> str:
    return f"""
        select f.issuer_cik, f.filing_date, f.accession, o.rptownercik as owner_cik,
               o.rptowner_relationship as relationship, o.rptowner_title as title
        from core.insider_filing f
        join {union_sql(con, "reportingowner")} o
          on o.accession_number = f.accession and o.quarter = f.quarter
        where o.rptownercik is not null and f.filing_date is not null and f.issuer_cik is not null
    """


def build_insider_filing(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["stg_sec_form4.submission", "stg_sec_headers.header", "ref.calendar"],
               "core.insider_filing")  # fmt: skip
    accepted = "select accession, accepted_at_et from stg_sec_headers.header"
    if has_daily(con):
        accepted += (" union all select accession_number, accepted_at_et "
                     "from stg_sec_form4_daily.submission")  # fmt: skip
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table core.insider_filing as
            with f as (
                select accession_number as accession, quarter, filing_date, document_type,
                       issuercik as issuer_cik, issuername as issuer_name,
                       issuertradingsymbol as symbol_raw, aff10b5one
                from {union_sql(con, "submission")}
                where accession_number is not null
                qualify row_number() over (partition by accession_number
                                           order by quarter, src_row) = 1
            ),
            h as (select accession, min(accepted_at_et) as accepted_at_et
                  from ({accepted}) group by 1),
            base as (select f.*, h.accepted_at_et from f left join h using (accession))
            select b.*,
                   {same_day_or_next("b.filing_date", "b.accepted_at_et", "c.session")} as known_at
            from base b asof left join ref.calendar c on c.session > b.filing_date
            """
        )
    n = db.count(con, "core.insider_filing")
    echo(f"  insider filings: {n:,}")
    return {"insider_filing": n}


# --- Entities and roles ----------------------------------------------------------------------


class _Components:
    """Union-find over one issuer's owner CIKs, keeping each component's member list."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.members: dict[str, list[str]] = {}

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x
            self.members[x] = [x]

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] += self.members.pop(rb)


def _cik_order(cik: str) -> tuple[int, str]:
    """Numeric order for unpadded CIKs, without failing on a stray non-digit."""
    return len(cik), cik


def _rows(table: pa.Table):
    for batch in table.to_batches(BATCH_ROWS):
        yield from zip(*(column.to_pylist() for column in batch.columns), strict=True)


def _insert_members(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    issuers, owners, ids, days = zip(*rows, strict=True)
    data = pa.table({
        "issuer_cik": pa.array(issuers, pa.string()),
        "owner_cik": pa.array(owners, pa.string()),
        "entity_id": pa.array(ids, pa.string()),
        "valid_from": pa.array(days, pa.date32()),
    })  # fmt: skip
    con.register("_members", data)
    try:
        con.execute("insert into core.insider_entity_member select * from _members")
    finally:
        con.unregister("_members")


def _build_members(con: duckdb.DuckDBPyConnection) -> None:
    """Filings are applied per issuer in date order. All of a day's filings are unioned before any
    row is emitted, because "dated on or before T" includes T."""
    con.execute(
        "create or replace table core.insider_entity_member (issuer_cik VARCHAR, "
        "owner_cik VARCHAR, entity_id VARCHAR, valid_from DATE)"
    )
    # Fully materialised (compact in Arrow) so the inserts below can use the same connection.
    table = con.execute(
        f"select distinct issuer_cik, filing_date, accession, owner_cik "
        f"from ({_filing_owners(con)}) order by all"
    ).to_arrow_table()
    out: list[tuple] = []
    for issuer, by_issuer in groupby(_rows(table), key=itemgetter(0)):
        components = _Components()
        current: dict[str, str] = {}
        for day, by_day in groupby(by_issuer, key=itemgetter(1)):
            touched: set[str] = set()
            for _, filing_rows in groupby(by_day, key=itemgetter(2)):
                owners = [r[3] for r in filing_rows]
                for o in owners:
                    components.add(o)
                    components.union(owners[0], o)
                touched.update(owners)
            for root in {components.find(o) for o in touched}:
                members = components.members[root]
                entity_id = f"{issuer}:{min(members, key=_cik_order)}"
                for o in members:
                    if current.get(o) != entity_id:
                        current[o] = entity_id
                        out.append((issuer, o, entity_id, day))
        if len(out) >= FLUSH_ROWS:
            _insert_members(con, out)
            out = []
    if out:
        _insert_members(con, out)


def _build_roles(con: duckdb.DuckDBPyConnection, ceo_re: str) -> None:
    """Flags are substrings of the relationship: until 2022 the SEC glues `Other` to the previous
    flag without a comma (`DirectorOther`), and no flag name contains another. CEO/CFO needs the
    Officer flag and a matching title; a title alone never makes an officer. When an owner files
    more than once on one day, the most senior of that day's roles counts. Consecutive filings
    with the same role collapse into one interval."""
    seniority = " ".join(f"when '{role}' then {n}" for role, n in SENIORITY.items())
    con.execute(
        f"""
        create or replace table core.insider_owner_role as
        with flags as (
            select issuer_cik, owner_cik, filing_date, accession, title,
                   contains(rel, 'director') as is_director,
                   contains(rel, 'officer') as is_officer,
                   contains(rel, 'tenpercentowner') as is_ten_pct,
                   contains(rel, 'other') as is_other
            from (select *, lower(coalesce(relationship, '')) as rel from ({_filing_owners(con)}))
        ),
        roles as (
            select *, case role {seniority} end as seniority
            from (
                select *, case
                    when is_officer and coalesce(regexp_matches(title, $ceo_re, 'i'), false)
                        then 'ceo_cfo'
                    when is_officer then 'officer'
                    when is_director then 'director'
                    when is_ten_pct then 'ten_pct'
                    else 'other' end as role
                from flags
            )
        ),
        per_day as (
            select * from roles
            qualify row_number() over (
                partition by issuer_cik, owner_cik, filing_date
                order by seniority desc, accession desc
            ) = 1
        )
        select issuer_cik, owner_cik, filing_date as valid_from, role, seniority,
               is_director, is_officer, is_ten_pct, is_other, title
        from per_day
        qualify role is distinct from lag(role) over (
            partition by issuer_cik, owner_cik order by filing_date
        )
        """,
        {"ceo_re": ceo_re},
    )


def _entity_problems(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Entity ids whose members do not all leave together or that gain a member on or after the
    day they are retired (membership must only merge), and filings whose owners are not all in one
    entity at the filing date."""
    not_monotonic = con.execute(
        """
        with spans as (
            select issuer_cik, entity_id, valid_from,
                   coalesce(lead(valid_from) over w, DATE '9999-12-31') as until,
                   coalesce(lead(entity_id) over w, '') as next_id
            from core.insider_entity_member
            window w as (partition by issuer_cik, owner_cik order by valid_from)
        )
        select entity_id from spans group by issuer_cik, entity_id
        having count(distinct until) > 1 or count(distinct next_id) > 1
            or max(valid_from) >= min(until)
        order by 1 limit 5
        """
    ).fetchall()
    split = con.execute(
        f"""
        with resolved as (
            select fo.accession, m.entity_id
            from ({_filing_owners(con)}) fo asof left join core.insider_entity_member m
              on fo.issuer_cik = m.issuer_cik and fo.owner_cik = m.owner_cik
             and fo.filing_date >= m.valid_from
        )
        select accession from resolved group by accession
        having count(distinct entity_id) <> 1 or count(entity_id) < count(*)
        order by 1 limit 5
        """
    ).fetchall()
    return [f"entity not monotonic: {e}" for (e,) in not_monotonic] + [
        f"filing split across entities: {a}" for (a,) in split
    ]


def build_insider_entities(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """`core.insider_entity_member` and `core.insider_owner_role`, checked before commit."""
    db.require(con, ["core.insider_filing", "stg_sec_form4.reportingowner"],
               "core.insider_entity_member")  # fmt: skip
    ceo_re = tracker(p)["patterns"]["ceo_cfo_title"]
    with db.transaction(con):
        _build_members(con)
        _build_roles(con, ceo_re)
        problems = _entity_problems(con)
        if problems:
            raise db.StepFailed("; ".join(problems))
    owners, entities, multi = con.execute(
        """
        with latest as (
            select entity_id from core.insider_entity_member
            qualify row_number() over (
                partition by issuer_cik, owner_cik order by valid_from desc
            ) = 1
        ), sizes as (select entity_id, count(*) as n from latest group by entity_id)
        select (select count(*) from latest), count(*), count(*) filter (where n > 1) from sizes
        """
    ).fetchone()
    counts = {"owners": owners, "entities": entities, "multi_member_entities": multi,
              "role_intervals": db.count(con, "core.insider_owner_role")}  # fmt: skip
    echo(f"  insider entities: {counts}")
    return counts


def resolve_entities(con: duckdb.DuckDBPyConnection, source: str, target: str) -> None:
    """Temp table `target` = `source` plus `entity_id` and `entity_seniority` as of each row's t.

    `source` needs the columns `issuer_cik`, `owner_cik` and `t` (a date). The members of an entity
    at t are the owners with any row of its `entity_id` dated on or before t: components only
    merge, so a label still current at t holds everyone who ever carried it. Seniority is the
    highest among those members' roles at t. Owners with no filing on or before t get nulls.
    """
    con.execute(
        f"""
        create or replace temp table {target} as
        with keys as (select distinct issuer_cik, owner_cik, t from {source}),
        owner_entity as (
            select k.issuer_cik, k.owner_cik, k.t, m.entity_id
            from keys k asof left join core.insider_entity_member m
              on k.issuer_cik = m.issuer_cik and k.owner_cik = m.owner_cik
             and k.t >= m.valid_from
        ),
        members as (
            select distinct e.issuer_cik, e.entity_id, e.t, m.owner_cik
            from (select distinct issuer_cik, entity_id, t from owner_entity
                  where entity_id is not null) e
            join core.insider_entity_member m
              on m.issuer_cik = e.issuer_cik and m.entity_id = e.entity_id
             and m.valid_from <= e.t
        ),
        entity_seniority as (
            select x.issuer_cik, x.entity_id, x.t, max(r.seniority) as entity_seniority
            from members x asof left join core.insider_owner_role r
              on x.issuer_cik = r.issuer_cik and x.owner_cik = r.owner_cik
             and x.t >= r.valid_from
            group by all
        )
        select s.*, e.entity_id, sn.entity_seniority
        from {source} s
        left join owner_entity e
          on e.issuer_cik = s.issuer_cik and e.owner_cik = s.owner_cik and e.t = s.t
        left join entity_seniority sn
          on sn.issuer_cik = e.issuer_cik and sn.entity_id = e.entity_id and sn.t = e.t
        """
    )


# --- Trades, activity and the funnel -----------------------------------------------------------


def _common(column: str) -> str:
    """SQL: the security title is common stock (G3)."""
    return (
        f"coalesce(regexp_matches({column}, $common_re, 'i') "
        f"and not regexp_matches({column}, $excl_re, 'i'), false)"
    )


def _title_args(rules: dict) -> dict:
    return {"common_re": rules["patterns"]["common_title"],
            "excl_re": rules["patterns"]["excluded_title"]}  # fmt: skip


def build_insider_trade(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """`core.insider_trade`: every non-derivative line (first quarter per line), with gate flags,
    `side` (buy or sell), `open_market` (G1, G2, G3 and G6a) and `planned` (G4a or G4b fails)."""
    db.require(con, ["core.insider_filing", "stg_sec_form4.nonderiv_trans",
                     "stg_sec_form4.footnotes"], "core.insider_trade")  # fmt: skip
    rules = tracker(p)
    has_value = con.execute(
        "select count(*) = 2 from duckdb_tables() where schema_name = 'core' "
        "and table_name in ('price_daily', 'shares_outstanding')"
    ).fetchone()[0]
    company_value = (  # what was known when the line was filed
        "p.close as market_price, p.close * s.shares as company_value from lines l "
        "asof left join core.price_daily p on p.cik = l.issuer_cik and p.session <= l.filing_date "
        "asof left join core.shares_outstanding s on s.cik = l.issuer_cik "
        "and s.known_at <= l.filing_date"
        if has_value
        else "null::DOUBLE as market_price, null::DOUBLE as company_value from lines l"
    )
    args = _title_args(rules) | {
        "plan_re": rules["patterns"]["plan_footnote"],
        "offer_re": rules["patterns"]["offering_footnote"],
        "timely_days": int(rules["purchase"]["timeliness_days"]),
    }
    cited = ", ".join(f"t.{c}" for c in _FN_COLUMNS)
    with db.transaction(con):
        con.execute(
            f"""
            create or replace table core.insider_trade as
            with lines as materialized (
                select t.accession_number as accession, t.nonderiv_trans_sk as line_sk,
                       f.quarter, f.issuer_cik, f.filing_date, f.known_at, f.document_type,
                       f.aff10b5one, t.security_title, t.trans_date, t.trans_code,
                       t.trans_acquired_disp_cd as acq_disp, t.trans_shares as shares,
                       t.trans_pricepershare as price, t.shrs_ownd_folwng_trans as shares_after,
                       t.direct_indirect_ownership as direct_indirect, t.nature_of_ownership,
                       list_sort(list_distinct(list_filter(
                           list_transform(string_split(concat_ws(',', {cited}), ','),
                                          x -> trim(x)),
                           x -> x <> ''
                       ))) as fn_ids
                from {union_sql(con, "nonderiv_trans")} t
                join core.insider_filing f on f.accession = t.accession_number
                qualify row_number() over (
                    partition by t.accession_number, t.nonderiv_trans_sk
                    order by t.quarter, t.src_row
                ) = 1
            ),
            notes as (
                select n.accession_number as accession, n.footnote_id,
                       regexp_matches(n.footnote_txt, $plan_re, 'i') as plan_fn,
                       regexp_matches(n.footnote_txt, $offer_re, 'i') as offering_fn
                from {union_sql(con, "footnotes")} n
                join core.insider_filing f
                  on f.accession = n.accession_number and f.quarter = n.quarter
            ),
            valued as (
                select *, coalesce(price > 10 * market_price or price * 10 < market_price
                                   or shares * price > company_value, false) as typo
                from (select l.*, {company_value})
            ),
            hits as (
                select c.accession, c.line_sk,
                       bool_or(n.plan_fn) as plan_fn, bool_or(n.offering_fn) as offering_fn
                from (select accession, line_sk, unnest(fn_ids) as footnote_id from lines) c
                join notes n using (accession, footnote_id)
                group by all
            ),
            flagged as (
                select l.* exclude (aff10b5one, market_price, company_value, typo),
                       case when l.typo then null else l.shares * l.price end as value_usd,
                       l.typo as value_typo,
                       coalesce(l.document_type = '4', false) as g1_form4,
                       coalesce(l.trans_code = 'P' and l.acq_disp = 'A', false) as g2_purchase,
                       coalesce(l.trans_code = 'S' and l.acq_disp = 'D', false) as g2_sale,
                       {_common("l.security_title")} as g3_common,
                       not coalesce(l.aff10b5one, false) as g4a_no_checkbox,
                       not coalesce(h.plan_fn, false) as g4b_no_plan_fn,
                       not coalesce(h.offering_fn, false) as g5_no_offering_fn,
                       coalesce(date_diff('day', l.trans_date, l.filing_date)
                                between 0 and $timely_days and l.shares * l.price > 0, false)
                           as g6a_timely_valued
                from valued l left join hits h using (accession, line_sk)
            )
            select *, {" and ".join(LINE_GATES)} as passes_lines,
                   case when g2_purchase then 'buy' when g2_sale then 'sell' end as side,
                   g1_form4 and (g2_purchase or g2_sale) and g3_common and g6a_timely_valued
                       as open_market,
                   not (g4a_no_checkbox and g4b_no_plan_fn) as planned
            from flagged
            """,
            args,
        )
    row = con.execute(
        "select count(*), count(*) filter (where open_market and side = 'buy'), "
        "count(*) filter (where open_market and side = 'sell'), "
        "count(*) filter (where passes_lines) from core.insider_trade"
    ).fetchone()
    counts = dict(
        zip(["line", "open_market_buy", "open_market_sell", "passes_lines"], row, strict=True)
    )
    echo(f"  insider trade lines: {counts}")
    return counts


def _holdings_sql(con) -> str:
    """SQL: per accession in `_side`, the owners' common-stock holdings before and after the
    filing. Every common-stock line counts, whatever its code or gates: per holding
    (`direct_indirect`, `nature_of_ownership`), after = the last line's shares owned, and before =
    after − acquired + disposed. Untraded common-stock rows of `nonderiv_holding` add to both.
    Missing shares make the totals null; so does a negative "before" in any holding, for before."""
    return f"""
        with acc as (select distinct accession, quarter from _side),
        lines as (
            select t.accession, t.direct_indirect, t.nature_of_ownership, t.acq_disp, t.shares,
                   t.shares_after,
                   row_number() over (
                       partition by t.accession, t.direct_indirect, t.nature_of_ownership
                       order by try_cast(t.line_sk as BIGINT) desc nulls last, t.line_sk desc
                   ) as from_last
            from core.insider_trade t join acc using (accession)
            where t.g3_common
        ),
        per_holding as (
            select accession,
                   max(shares_after) filter (where from_last = 1) as after,
                   {db.exact_sum("case acq_disp when 'A' then shares when 'D' then -shares end")}
                       as net_bought,
                   bool_or(shares is null or acq_disp not in ('A', 'D')
                           or (from_last = 1 and shares_after is null)) as broken
            from lines
            group by accession, direct_indirect, nature_of_ownership
        ),
        traded as (
            select accession, {db.exact_sum("after - net_bought")} as before,
                   {db.exact_sum("after")} as after,
                   bool_or(broken) as broken, bool_or(after - net_bought < 0) as negative
            from per_holding group by accession
        ),
        untraded as (
            select h.accession_number as accession,
                   {db.exact_sum("h.shrs_ownd_folwng_trans")} as shares,
                   bool_or(h.shrs_ownd_folwng_trans is null) as broken
            from {union_sql(con, "nonderiv_holding")} h
            join acc a on a.accession = h.accession_number and a.quarter = h.quarter
            where {_common("h.security_title")}
            group by 1
        ),
        joined as (
            select a.accession,
                   coalesce(tr.broken, true) or coalesce(u.broken, false) as broken,
                   coalesce(tr.negative, false) as negative,
                   tr.before + coalesce(u.shares, 0) as before,
                   tr.after + coalesce(u.shares, 0) as after
            from acc a left join traded tr using (accession) left join untraded u using (accession)
        )
        select accession,
               case when not broken and not negative then before end as shares_before,
               case when not broken then after end as shares_after
        from joined
    """


def _build_funnel(con: duckdb.DuckDBPyConnection) -> None:
    passed = ["count(*)"] + [
        f"count(*) filter (where {' and '.join(LINE_GATES[: k + 1])})"
        for k in range(len(LINE_GATES))
    ]
    steps = [
        f"select quarter, {k} as step, '{gate}' as gate, 'lines' as unit, "
        f"n{k} as rows_in, n{k + 1} as rows_out from counts"
        for k, gate in enumerate(LINE_GATES)
    ]
    steps.append(
        f"select c.quarter, {len(LINE_GATES)}, '{FILING_GATE}', 'filings', c.filings, "
        "coalesce(k.clean, 0) from counts c left join clean k using (quarter)"
    )
    con.execute(
        f"""
        create or replace table core.insider_funnel as
        with counts as (
            select quarter, {", ".join(f"{expr} as n{k}" for k, expr in enumerate(passed))},
                   count(distinct accession) filter (where passes_lines) as filings
            from core.insider_trade group by quarter
        ),
        clean as (select quarter, count(*) as clean from core.insider_activity
                  where clean group by quarter)
        select quarter, step, gate, unit, rows_in, rows_out, rows_in - rows_out as rows_removed
        from ({" union all ".join(steps)})
        order by quarter, step
        """
    )


def build_insider_activity(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """`core.insider_activity` and `core.insider_funnel`."""
    db.require(con, ["core.insider_trade", "core.insider_entity_member",
                     "core.insider_owner_role", "stg_sec_form4.nonderiv_holding"],
               "core.insider_activity")  # fmt: skip
    rules = tracker(p)
    min_value = float(rules["purchase"]["min_value_usd"])
    with db.transaction(con):
        con.execute(
            f"""
            create or replace temp table _side as
            select accession, side, any_value(issuer_cik) as issuer_cik,
                   any_value(filing_date) as filing_date, any_value(known_at) as known_at,
                   any_value(quarter) as quarter, count(*) as n_lines,
                   {db.exact_sum("value_usd")} as value_usd, {db.exact_sum("shares")} as shares,
                   min(trans_date) as min_trade_date, max(trans_date) as max_trade_date,
                   bool_or(planned) as planned, bool_or(not g5_no_offering_fn) as offering,
                   {db.exact_sum("case when passes_lines then value_usd end")} as clean_value_usd
            from core.insider_trade where open_market
            group by accession, side
            """
        )
        con.execute(
            f"""
            create or replace temp table _side_owner as
            select a.accession, a.issuer_cik, a.filing_date as t,
                   min(o.rptownercik) as owner_cik,
                   list_sort(list_distinct(list(o.rptownercik))) as owner_ciks,
                   list_sort(list_distinct(list(o.rptownername))) as owner_names
            from (select distinct accession, issuer_cik, filing_date, quarter from _side) a
            left join {union_sql(con, "reportingowner")} o
              on o.accession_number = a.accession and o.quarter = a.quarter
            group by all
            """
        )
        resolve_entities(con, "_side_owner", "_side_entity")
        con.execute(f"create or replace temp table _holding as {_holdings_sql(con)}",
                    _title_args(rules))  # fmt: skip
        con.execute(
            f"""
            create or replace table core.insider_activity as
            select s.accession, s.issuer_cik, s.side, s.filing_date, s.known_at, s.quarter,
                   e.entity_id, case e.entity_seniority {ROLE} end as entity_role,
                   e.entity_seniority, e.owner_ciks, e.owner_names, s.n_lines, s.value_usd,
                   s.shares, s.value_usd / nullif(s.shares, 0) as avg_price,
                   s.min_trade_date, s.max_trade_date, s.planned, s.offering,
                   case when s.side = 'buy' then s.clean_value_usd end as clean_value_usd,
                   coalesce(s.side = 'buy' and s.clean_value_usd >= {min_value}, false) as clean,
                   h.shares_before, h.shares_after,
                   s.side = 'buy' and h.shares_before = 0 as opens_position,
                   s.side = 'sell' and h.shares_after = 0 as closes_position
            from _side s
            join _side_entity e using (accession)
            left join _holding h using (accession)
            order by s.issuer_cik, s.filing_date, s.accession, s.side
            """
        )
        _build_funnel(con)
        for name in ("_side", "_side_owner", "_side_entity", "_holding"):
            con.execute(f"drop table {name}")
    counts = dict(zip(["buy", "sell", "clean_buy"], con.execute(
        "select count(*) filter (where side = 'buy'), count(*) filter (where side = 'sell'), "
        "count(*) filter (where clean) from core.insider_activity").fetchone(),
        strict=True))  # fmt: skip
    echo(f"  insider activity (filings): {counts}")
    return counts


# --- Clusters ------------------------------------------------------------------------------------


def _cooldown(candidates: list[tuple[str, str, date]], days: int) -> set[tuple[str, str, date]]:
    """The (issuer, group, day) candidates that start an event: in date order, those whose issuer
    has no started event in the group in the `days` before. Suppressed days do not restart it."""
    kept, last = set(), {}
    for issuer, group, t in sorted(candidates):
        previous = last.get((issuer, group))
        if previous is None or (t - previous).days >= days:
            kept.add((issuer, group, t))
            last[(issuer, group)] = t
    return kept


def build_insider_cluster(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["core.insider_activity", "core.insider_entity_member",
                     "core.insider_owner_role"], "core.insider_cluster")  # fmt: skip
    rule = tracker(p)["cluster"]
    window, min_entities = int(rule["window_days"]), int(rule["min_entities"])
    min_value, cooldown = float(rule["min_value_usd"]), int(rule["cooldown_days"])
    with db.transaction(con):
        con.execute(
            f"""
            create or replace temp table _window as
            with b as (
                select accession, issuer_cik, filing_date, known_at, clean_value_usd as value_usd,
                       owner_ciks[1] as owner_cik
                from core.insider_activity where clean
            ),
            days as (select distinct issuer_cik, filing_date as t from b)
            select d.issuer_cik, d.t, b.accession, b.filing_date, b.known_at, b.value_usd,
                   b.owner_cik
            from days d
            join b on b.issuer_cik = d.issuer_cik
                  and b.filing_date between d.t - {window - 1} and d.t
            """
        )
        resolve_entities(con, "_window", "_window_entity")
        con.execute(
            f"""
            create or replace temp table _candidate as
            select * from (
                select issuer_cik, t as cluster_date, case
                           when n >= {min_entities} and top >= {DIRECTOR} then 'A'
                           when n = 1 and top = {CEO_CFO} then 'B1'
                           when n = 1 and top >= {DIRECTOR} then 'B2' end as grp,
                       known_at, n as n_entities, total as total_value_usd,
                       top as max_seniority, case top {ROLE} end as top_role,
                       accessions, entity_ids
                from (
                    select issuer_cik, t, count(distinct entity_id) as n,
                           {db.exact_sum("value_usd")} as total, max(entity_seniority) as top,
                           max(known_at) as known_at,
                           list_sort(list_distinct(list(accession))) as accessions,
                           list_sort(list_distinct(list(entity_id))) as entity_ids
                    from _window_entity group by issuer_cik, t
                )
            )
            where total_value_usd >= {min_value} and grp is not null
            """
        )
        candidates = con.execute("select issuer_cik, grp, cluster_date from _candidate").fetchall()
        starts = sorted(_cooldown(candidates, cooldown))
        con.register("_starts", pa.table({
            "issuer_cik": pa.array([s[0] for s in starts], pa.string()),
            "grp": pa.array([s[1] for s in starts], pa.string()),
            "cluster_date": pa.array([s[2] for s in starts], pa.date32()),
        }))  # fmt: skip
        try:
            con.execute(
                """
                create or replace table core.insider_cluster as
                select c.*, s.issuer_cik is not null as starts_event
                from _candidate c left join _starts s using (issuer_cik, grp, cluster_date)
                order by c.issuer_cik, c.cluster_date, c.grp
                """
            )
        finally:
            con.unregister("_starts")
        for name in ("_window", "_window_entity", "_candidate"):
            con.execute(f"drop table {name}")
    counts = dict(con.execute(
        "select grp, count(*) filter (where starts_event) from core.insider_cluster group by 1 "
        "order by 1").fetchall())  # fmt: skip
    echo(f"  insider events by group: {counts}")
    return {f"events_{g}": n for g, n in counts.items()}


# --- The daily parser against the data sets --------------------------------------------------

_LINE_TABLES = ("nonderiv_trans", "nonderiv_holding", "deriv_trans", "deriv_holding")


# The quarterly data sets keep shares and prices to two decimals (half up), the filings in full:
# values are compared at the data sets' precision.
_CENTS = "round(cast({} as DECIMAL(38, 6)), 2)"


def _version(schema: str, chosen: str) -> str:
    """SQL: per accession of `chosen` (accession, quarter), its owners, line count and the value of
    its non-derivative lines (shares × price) in `schema`, in full and at two decimals."""
    cents = _CENTS.format
    lines = " union all ".join(f"select accession_number, quarter from {schema}.{t}"
                               for t in _LINE_TABLES)  # fmt: skip
    on = "on x.accession_number = a.accession and x.quarter = a.quarter"
    return f"""
        select a.accession, a.quarter, coalesce(o.owners, []) as owners,
               coalesce(n.lines, 0) as lines, v.value, v.value_cents
        from {chosen} a
        left join (select a.accession, list_sort(list_distinct(list(x.rptownercik))) as owners
                   from {chosen} a join {schema}.reportingowner x {on} group by 1) o
          using (accession)
        left join (select a.accession, count(*) as lines
                   from {chosen} a join ({lines}) x {on} group by 1) n using (accession)
        left join (select a.accession, {db.exact_sum("x.trans_shares * x.trans_pricepershare")}
                          as value,
                          sum({cents("x.trans_shares")} * {cents("x.trans_pricepershare")})
                          as value_cents
                   from {chosen} a join {schema}.nonderiv_trans x {on} group by 1) v
          using (accession)
    """


def build_form4_reconciliation(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    """`core.form4_reconciliation`: the accessions in a quarterly data set (its first quarter) and
    in the daily filings whose versions differ in owners, line count or value (at the data sets'
    two decimals; `value_daily` is the filing's full-precision value)."""
    db.require(con, ["stg_sec_form4.submission"], "core.form4_reconciliation")
    columns = ("accession VARCHAR, quarter VARCHAR, owners_quarterly VARCHAR[], "
               "owners_daily VARCHAR[], lines_quarterly BIGINT, lines_daily BIGINT, "
               "value_quarterly DOUBLE, value_daily DOUBLE, owners_differ BOOLEAN, "
               "lines_differ BOOLEAN, value_differ BOOLEAN")  # fmt: skip
    with db.transaction(con):
        if not has_daily(con):
            con.execute(f"create or replace table core.form4_reconciliation ({columns})")
            echo("  form 4 reconciliation: no daily filings")
            return {"compared": 0, "differ": 0}
        con.execute(
            """
            create or replace temp table _both as
            select accession_number as accession, quarter from stg_sec_form4.submission
            where accession_number in (select accession_number from stg_sec_form4_daily.submission)
            qualify row_number() over (partition by accession_number order by quarter, src_row) = 1
            """
        )
        con.execute(
            "create or replace temp table _daily as select accession_number as accession, quarter "
            "from stg_sec_form4_daily.submission "
            "where accession_number in (select accession from _both)"
        )
        con.execute(
            f"""
            create or replace table core.form4_reconciliation as
            select accession, q.quarter, q.owners as owners_quarterly, d.owners as owners_daily,
                   q.lines as lines_quarterly, d.lines as lines_daily,
                   q.value as value_quarterly, d.value as value_daily,
                   q.owners <> d.owners as owners_differ, q.lines <> d.lines as lines_differ,
                   coalesce(q.value_cents, 0) <> coalesce(d.value_cents, 0) as value_differ
            from ({_version("stg_sec_form4", "_both")}) q
            join ({_version("stg_sec_form4_daily", "_daily")}) d using (accession)
            where q.owners <> d.owners or q.lines <> d.lines
               or coalesce(q.value_cents, 0) <> coalesce(d.value_cents, 0)
            order by accession
            """
        )
        compared = db.count(con, "_both")
        for name in ("_both", "_daily"):
            con.execute(f"drop table {name}")
    differ = db.count(con, "core.form4_reconciliation")
    echo(f"  form 4 reconciliation: {compared:,} accessions in both, {differ:,} differ")
    return {"compared": compared, "differ": differ}
