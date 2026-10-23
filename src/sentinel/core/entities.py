"""Step 3: filings, point-in-time insider entities and roles (research.md R3–R4; W7, W8).

Owners who appear together on any filing for an issuer are one entity from that filing's date on.
Components only merge, so the history is a short list of membership changes per issuer, and the
entity of an owner at T is its latest `core.entity_member` row with `valid_from <= T`. An owner's
role at T comes from its latest filing for the issuer dated on or before T.

Every builder takes `cutoff` (keep only filings dated on or before it) and `issuers` (keep only
these issuer CIKs), so the truncation test (W9) can rebuild from a prefix of the records.
"""

from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

import duckdb
import pyarrow as pa

from sentinel.warehouse import row_count, scope

BATCH_ROWS = 200_000  # input rows turned into Python objects at a time
FLUSH_ROWS = 500_000  # membership rows buffered before an insert

SENIORITY = {"ceo_cfo": 4, "officer": 3, "director": 2, "ten_pct": 1, "other": 0}


def _filing_owners(where: str) -> str:
    """Owner rows of each dated filing, from the same quarter's copy as `core.filing`."""
    return f"""
        select f.issuer_cik, f.filing_date, f.accession, o.rptownercik as owner_cik,
               o.rptowner_relationship as relationship, o.rptowner_title as title
        from core.filing f
        join stg.reportingowner o on o.accession_number = f.accession and o.quarter = f.quarter
        where o.rptownercik is not null and f.filing_date is not null
          and f.issuer_cik is not null and {where}
    """


def build_filing(con: duckdb.DuckDBPyConnection, cutoff=None, issuers=None) -> int:
    """`core.filing`: one row per accession, taken from the first quarter that lists it."""
    where, args = scope(cutoff, issuers)
    con.execute(
        f"""
        create or replace table core.filing as
        select * from (
            select accession_number as accession, quarter, filing_date, document_type,
                   issuercik as issuer_cik, issuername as issuer_name,
                   issuertradingsymbol as symbol_raw, aff10b5one
            from stg.submission
            where accession_number is not null
            qualify row_number() over (partition by accession_number order by quarter, src_row) = 1
        ) f
        where {where}
        """,
        args,
    )
    return row_count(con, "core.filing")


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
    data = pa.table(
        {
            "issuer_cik": pa.array(issuers, pa.string()),
            "owner_cik": pa.array(owners, pa.string()),
            "entity_id": pa.array(ids, pa.string()),
            "valid_from": pa.array(days, pa.date32()),
        }
    )
    con.register("_members", data)
    try:
        con.execute("insert into core.entity_member select * from _members")
    finally:
        con.unregister("_members")


def build_entity_members(con: duckdb.DuckDBPyConnection, cutoff=None, issuers=None) -> int:
    """`core.entity_member`: a row whenever an owner's entity id is created or changes.

    Filings are applied per issuer in date order. All of a day's filings are unioned before any
    row is emitted, because "dated on or before T" includes T. The entity id is
    `"{issuer}:{lowest owner CIK in the component}"`.
    """
    where, args = scope(cutoff, issuers)
    con.execute(
        "create or replace table core.entity_member (issuer_cik VARCHAR, owner_cik VARCHAR, "
        "entity_id VARCHAR, valid_from DATE)"
    )
    # Fully materialised (compact in Arrow) so the inserts below can use the same connection.
    table = con.execute(
        f"select distinct issuer_cik, filing_date, accession, owner_cik "
        f"from ({_filing_owners(where)}) order by all",
        args,
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
    return row_count(con, "core.entity_member")


def build_owner_roles(con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None):
    """`core.owner_role`: role intervals per owner and issuer (research.md R4).

    Flags are substrings of the relationship: until 2022 the SEC files glue `Other` to the previous
    flag without a comma (`DirectorOther`), and no flag name contains another. CEO/CFO needs the
    Officer flag and a title
    matching `rules.role_ceo_cfo_title_regex`; a title alone never makes an officer. When an owner
    files more than once on one day, the most senior of that day's roles counts. Consecutive
    filings with the same role collapse into one interval.
    """
    where, args = scope(cutoff, issuers)
    seniority = " ".join(f"when '{role}' then {n}" for role, n in SENIORITY.items())
    con.execute(
        f"""
        create or replace table core.owner_role as
        with flags as (
            select issuer_cik, owner_cik, filing_date, accession, title,
                   contains(rel, 'director') as is_director,
                   contains(rel, 'officer') as is_officer,
                   contains(rel, 'tenpercentowner') as is_ten_pct,
                   contains(rel, 'other') as is_other
            from (
                select *, lower(coalesce(relationship, '')) as rel
                from ({_filing_owners(where)})
            )
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
        {**args, "ceo_re": params["rules"]["role_ceo_cfo_title_regex"]},
    )
    return row_count(con, "core.owner_role")


@dataclass(frozen=True)
class EntityReport:
    filings: int
    member_rows: int
    role_intervals: int
    owners: int  # (issuer, owner) pairs
    entities: int  # entities at the end of the history
    multi_member: int  # of which with more than one owner

    @property
    def rows_written(self) -> int:
        return self.filings + self.member_rows + self.role_intervals


def build(con: duckdb.DuckDBPyConnection, params: dict, cutoff=None, issuers=None) -> EntityReport:
    """Recreate `core.filing`, `core.entity_member` and `core.owner_role`, in one transaction."""
    con.execute("begin transaction")
    try:
        filings = build_filing(con, cutoff, issuers)
        member_rows = build_entity_members(con, cutoff, issuers)
        role_intervals = build_owner_roles(con, params, cutoff, issuers)
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")

    owners, ents, multi = con.execute(
        """
        with latest as (
            select entity_id from core.entity_member
            qualify row_number() over (
                partition by issuer_cik, owner_cik order by valid_from desc
            ) = 1
        ), sizes as (select entity_id, count(*) as n from latest group by entity_id)
        select (select count(*) from latest), count(*), count(*) filter (where n > 1) from sizes
        """
    ).fetchone()
    return EntityReport(filings, member_rows, role_intervals, owners, ents, multi)


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
            from keys k asof left join core.entity_member m
              on k.issuer_cik = m.issuer_cik and k.owner_cik = m.owner_cik
             and k.t >= m.valid_from
        ),
        members as (
            select distinct e.issuer_cik, e.entity_id, e.t, m.owner_cik
            from (select distinct issuer_cik, entity_id, t from owner_entity
                  where entity_id is not null) e
            join core.entity_member m
              on m.issuer_cik = e.issuer_cik and m.entity_id = e.entity_id
             and m.valid_from <= e.t
        ),
        entity_seniority as (
            select x.issuer_cik, x.entity_id, x.t, max(r.seniority) as entity_seniority
            from members x asof left join core.owner_role r
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


def check_monotonic(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    """W7: (issuer, entity_id) labels whose members do not all leave together, or that gain a
    member on or after the day they are retired. Empty when membership is monotonic."""
    return con.execute(
        """
        with spans as (
            select issuer_cik, entity_id, valid_from,
                   coalesce(lead(valid_from) over w, DATE '9999-12-31') as until,
                   coalesce(lead(entity_id) over w, '') as next_id
            from core.entity_member
            window w as (partition by issuer_cik, owner_cik order by valid_from)
        )
        select issuer_cik, entity_id from spans group by all
        having count(distinct until) > 1 or count(distinct next_id) > 1
            or max(valid_from) >= min(until)
        order by all
        """
    ).fetchall()


def check_filings_map_to_one_entity(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W8: accessions whose owners are not all in one entity at the filing date."""
    return [
        acc
        for (acc,) in con.execute(
            f"""
            with fo as ({_filing_owners("true")}),
            resolved as (
                select fo.accession, m.entity_id
                from fo asof left join core.entity_member m
                  on fo.issuer_cik = m.issuer_cik and fo.owner_cik = m.owner_cik
                 and fo.filing_date >= m.valid_from
            )
            select accession from resolved group by accession
            having count(distinct entity_id) <> 1 or count(entity_id) < count(*)
            order by accession
            """
        ).fetchall()
    ]
