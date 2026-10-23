"""Step 3: point-in-time entities and roles (FR-006 – FR-008, W7, W8)."""

import pytest
from conftest import owner, sub

from sentinel.core import entities


def entity(con, issuer, owner_cik, t):
    row = con.execute(
        "select entity_id from core.entity_member where issuer_cik = ? and owner_cik = ? "
        "and valid_from <= ? order by valid_from desc limit 1",
        [issuer, owner_cik, t],
    ).fetchone()
    return row and row[0]


def role(con, issuer, owner_cik, t):
    row = con.execute(
        "select role, seniority from core.owner_role where issuer_cik = ? and owner_cik = ? "
        "and valid_from <= ? order by valid_from desc limit 1",
        [issuer, owner_cik, t],
    ).fetchone()
    return row and row[0]


def filing(acc, date, cik, owners, doc="4"):
    """A filing with no transaction lines: entities and roles use filings of every form."""
    return [sub(acc, date=date, cik=cik, doc=doc)], [
        owner(acc, ocik=o, rel=rel, title=title) for o, rel, title in owners
    ]


@pytest.fixture
def built(archives, pipeline):
    def make(filings):
        subs, owners = [], []
        for f in filings:
            s, o = filing(*f)
            subs += s
            owners += o
        archives({"2019q1": {"SUBMISSION": subs, "REPORTINGOWNER": owners}})
        return pipeline(until="entities")

    return make


D = ("Director", "")


def test_joint_filers_are_one_entity_from_that_filing(built):
    con = built([("a1", "01-MAR-2019", "100", [("9001", *D), ("9002", *D)])])
    assert entity(con, "100", "9001", "2019-03-01") == "100:9001"
    assert entity(con, "100", "9002", "2019-03-01") == "100:9001"
    assert entity(con, "100", "9002", "2019-02-28") is None


def test_later_merge_changes_membership_only_from_its_date(built):
    con = built(
        [
            ("b1", "01-JUN-2018", "200", [("9001", *D)]),
            ("b2", "01-JUL-2018", "200", [("9002", *D)]),
            ("b3", "01-MAY-2019", "200", [("9001", *D), ("9002", *D)], "5"),
        ]
    )
    assert entity(con, "200", "9001", "2019-04-30") == "200:9001"
    assert entity(con, "200", "9002", "2019-04-30") == "200:9002"
    assert entity(con, "200", "9002", "2019-05-01") == "200:9001"
    rows_9001 = con.execute(
        "select count(*) from core.entity_member where issuer_cik = '200' and owner_cik = '9001'"
    ).fetchone()[0]
    assert rows_9001 == 1  # its entity id never changed


def test_same_day_filings_are_applied_together(built):
    con = built(
        [
            ("c1", "03-JUN-2019", "300", [("9002", *D), ("9003", *D)]),
            ("c2", "03-JUN-2019", "300", [("9001", *D), ("9002", *D)]),
        ]
    )
    for o in ("9001", "9002", "9003"):
        assert entity(con, "300", o, "2019-06-03") == "300:9001"
    assert con.execute(
        "select list(entity_id) from core.entity_member where issuer_cik = '300' "
        "and owner_cik = '9003'"
    ).fetchone()[0] == ["300:9001"]


def test_entities_are_per_issuer(built):
    con = built(
        [
            ("d1", "01-MAR-2019", "100", [("9001", *D), ("9002", *D)]),
            ("d2", "02-MAR-2019", "400", [("9001", *D)]),
            ("d3", "03-MAR-2019", "400", [("9002", *D)]),
        ]
    )
    assert entity(con, "400", "9001", "2019-12-31") == "400:9001"
    assert entity(con, "400", "9002", "2019-12-31") == "400:9002"


def test_membership_is_monotonic_and_covers_every_filing(built):
    con = built(
        [
            ("e1", "01-FEB-2018", "100", [("9003", *D)]),
            ("e2", "01-MAR-2018", "100", [("9002", *D), ("9003", *D)]),
            ("e3", "01-APR-2018", "100", [("9001", *D), ("9004", *D)]),
            ("e4", "01-MAY-2018", "100", [("9004", *D), ("9002", *D)]),
        ]
    )
    assert entities.check_monotonic(con) == []
    assert entities.check_filings_map_to_one_entity(con) == []
    assert {entity(con, "100", o, "2018-05-01") for o in ("9001", "9002", "9003", "9004")} == {
        "100:9001"
    }
    assert entity(con, "100", "9003", "2018-04-15") == "100:9002"


def test_promotion_and_departure_change_the_role_from_their_filing(built):
    con = built(
        [
            ("r1", "01-MAR-2019", "500", [("9101", "Director", "")]),
            ("r2", "01-MAR-2019", "500", [("9102", "Officer", "Chief Executive Officer")]),
            ("r3", "02-MAR-2020", "500", [("9102", "Director", "")]),
            ("r4", "01-MAR-2021", "500", [("9101", "Director, Officer", "CEO")]),
        ]
    )
    assert role(con, "500", "9101", "2020-06-01") == "director"
    assert role(con, "500", "9101", "2021-03-01") == "ceo_cfo"
    assert role(con, "500", "9102", "2020-03-01") == "ceo_cfo"
    assert role(con, "500", "9102", "2020-03-02") == "director"


@pytest.mark.parametrize(
    "rel,title,expected",
    [
        ("Officer", "President & CEO", "ceo_cfo"),
        ("Officer", "Chief Financial Officer", "ceo_cfo"),
        ("Officer", "Principal Executive Officer", "ceo_cfo"),
        ("Officer", "See Remarks", "officer"),
        ("Director, TenPercentOwner", "", "director"),
        ("TenPercentOwner", "", "ten_pct"),
        ("Other", "Former director", "other"),
        ("Director", "CEO", "director"),  # a title alone does not make an officer
        # Before 2023 the SEC files glue "Other" to the previous flag without a comma.
        ("DirectorOther", "", "director"),
        ("Director,OfficerOther", "CFO", "ceo_cfo"),
        ("TenPercentOwnerOther", "", "ten_pct"),
        ("Director,Other", "", "director"),
    ],
)
def test_role_ranking(built, rel, title, expected):
    con = built([("t1", "01-MAR-2019", "600", [("9201", rel, title)])])
    assert role(con, "600", "9201", "2019-03-01") == expected


def test_repeated_role_collapses_into_one_interval(built):
    con = built(
        [
            ("s1", "01-MAR-2019", "700", [("9301", *D)]),
            ("s2", "01-APR-2019", "700", [("9301", *D)]),
            ("s3", "01-MAY-2019", "700", [("9301", "Officer", "CFO")]),
        ]
    )
    rows = con.execute(
        "select valid_from::VARCHAR, role from core.owner_role where owner_cik = '9301' "
        "order by valid_from"
    ).fetchall()
    assert rows == [("2019-03-01", "director"), ("2019-05-01", "ceo_cfo")]


def test_entity_seniority_is_the_most_senior_member_at_t(built):
    con = built(
        [
            (
                "u1",
                "01-MAR-2019",
                "800",
                [("9401", "Director", ""), ("9402", "TenPercentOwner", "")],
            ),
            ("u2", "01-MAR-2019", "800", [("9403", "TenPercentOwner", "")]),
            ("u3", "01-JUN-2019", "800", [("9404", "TenPercentOwner", "")]),
            (
                "u4",
                "01-JUL-2019",
                "800",
                [("9404", "Officer", "CFO"), ("9403", "TenPercentOwner", "")],
            ),
        ]
    )
    con.execute(
        "create or replace temp table probe as select * from (values "
        "('800', '9402', DATE '2019-03-01'), ('800', '9403', DATE '2019-06-30'), "
        "('800', '9403', DATE '2019-07-01')) t(issuer_cik, owner_cik, t)"
    )
    entities.resolve_entities(con, "probe", "probe_out")
    got = con.execute(
        "select owner_cik, t::VARCHAR, entity_id, entity_seniority from probe_out order by t"
    ).fetchall()
    assert got == [
        ("9402", "2019-03-01", "800:9401", 2),
        ("9403", "2019-06-30", "800:9403", 1),
        ("9403", "2019-07-01", "800:9403", 4),
    ]


def test_lowest_cik_is_numeric_and_owners_without_filings_resolve_to_null(built):
    con = built([("n1", "01-MAR-2019", "900", [("10000", *D), ("9001", *D)])])
    assert entity(con, "900", "10000", "2019-03-01") == "900:9001"
    con.execute(
        "create or replace temp table probe as select * from (values "
        "('900', '9001', DATE '2019-02-28'), ('900', '7777', DATE '2019-03-01')) "
        "t(issuer_cik, owner_cik, t)"
    )
    entities.resolve_entities(con, "probe", "probe_out")
    assert con.execute(
        "select entity_id, entity_seniority from probe_out order by owner_cik"
    ).fetchall() == [(None, None), (None, None)]


def test_a_filing_listed_in_two_quarters_counts_once(archives, pipeline):
    rows = {
        "SUBMISSION": [sub("q1", date="30-MAR-2019", cik="100")],
        "REPORTINGOWNER": [owner("q1", ocik="9001")],
    }
    archives({"2019q1": rows, "2019q2": rows})
    con = pipeline(until="entities")
    assert con.execute("select quarter from core.filing").fetchall() == [("2019q1",)]
    assert con.execute("select count(*) from core.entity_member").fetchone()[0] == 1
    assert con.execute("select count(*) from core.owner_role").fetchone()[0] == 1


def test_cutoff_and_issuer_scope_match_the_full_build(built, params):
    con = built(
        [
            ("p1", "01-MAR-2019", "100", [("9001", *D)]),
            ("p2", "01-APR-2019", "100", [("9001", *D), ("9002", "Officer", "CFO")]),
            ("p3", "01-MAY-2019", "200", [("9003", *D)]),
        ]
    )

    def rows(table, where="true"):
        return con.execute(f"select * from {table} where {where} order by all").fetchall()

    full = {
        t: rows(t, "valid_from <= '2019-03-31'") for t in ("core.entity_member", "core.owner_role")
    }
    entities.build(con, params, cutoff="2019-03-31")
    assert {t: rows(t) for t in full} == full
    entities.build(con, params, issuers=["200"])
    assert {r[0] for r in rows("core.entity_member")} == {"200"}
    assert {r[4] for r in rows("core.filing")} == {"200"}
