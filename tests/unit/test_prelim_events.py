"""Step 5: preliminary events A, B1 and B2 (FR-014, FR-015; research.md R6)."""

import pytest
from conftest import line, owner, sub

D, T10, CEO, VP, OTHER = (
    ("Director", ""),
    ("TenPercentOwner", ""),
    ("Officer", "Chief Executive Officer"),
    ("Officer", "VP Sales"),
    ("Other", ""),
)


def buy(acc, date, cik, owners, value=60_000, price="50"):
    """A Form 4 filed on `date` for a purchase traded that day; `owners` = [(cik, (rel, title))]."""
    shares = str(value / float(price))
    return (
        [sub(acc, date=date, cik=cik)],
        [owner(acc, ocik=o, rel=rel, title=title) for o, (rel, title) in owners],
        [line(acc, "1", tdate=date, shares=shares, price=price)],
    )


def joins(acc, date, cik, owners):
    """A Form 3 with no transactions: it only updates entities and roles."""
    return (
        [sub(acc, date=date, cik=cik, doc="3")],
        [owner(acc, ocik=o, rel=rel, title=title) for o, (rel, title) in owners],
        [],
    )


@pytest.fixture
def events(archives, pipeline):
    def run(*filings, quarter="2019q1"):
        tables = {"SUBMISSION": [], "REPORTINGOWNER": [], "NONDERIV_TRANS": []}
        for subs, owners, lines in filings:
            tables["SUBMISSION"] += subs
            tables["REPORTINGOWNER"] += owners
            tables["NONDERIV_TRANS"] += lines
        archives({quarter: tables})
        con = pipeline(until="prelim")
        return con, {
            r[0]: r[1:]
            for r in con.execute(
                'select event_id, "group", n_entities, total_value_usd, max_seniority '
                "from evt.prelim_event"
            ).fetchall()
        }

    return run


def test_cluster_needs_both_buys_within_14_days(events):
    con, ev = events(
        buy("a1", "01-MAR-2019", "100", [("9001", D)]),
        buy("a2", "14-MAR-2019", "100", [("9002", T10)]),
        buy("b1", "01-MAR-2019", "200", [("9001", D)]),
        buy("b2", "15-MAR-2019", "200", [("9002", T10)]),
    )
    assert ev == {"100:A:2019-03-14": ("A", 2, 120_000.0, 2)}
    members = con.execute(
        "select accession, entity_id_at_t, entity_role_at_t, value_usd from evt.prelim_event_member"
        " order by accession"
    ).fetchall()
    assert members == [
        ("a1", "100:9001", "director", 60_000.0),
        ("a2", "100:9002", "ten_pct", 60_000.0),
    ]


def test_ten_percent_owners_alone_make_no_cluster(events):
    _, ev = events(
        buy("c1", "01-MAR-2019", "100", [("9001", T10)]),
        buy("c2", "02-MAR-2019", "100", [("9002", T10)], value=80_000),
    )
    assert ev == {}


def test_a_promotion_before_t_counts(events):
    _, ev = events(
        buy("p1", "01-MAR-2019", "100", [("9001", T10)]),
        joins("p2", "05-MAR-2019", "100", [("9001", D)]),
        buy("p3", "10-MAR-2019", "100", [("9002", T10)]),
    )
    assert ev == {"100:A:2019-03-10": ("A", 2, 120_000.0, 2)}


def test_owners_merged_before_t_are_one_buyer(events):
    _, ev = events(
        buy("m1", "01-MAR-2019", "100", [("9001", D)]),
        joins("m2", "05-MAR-2019", "100", [("9001", D), ("9002", T10)]),
        buy("m3", "10-MAR-2019", "100", [("9002", T10)]),
    )
    assert ev == {"100:B2:2019-03-10": ("B2", 1, 120_000.0, 2)}


@pytest.mark.parametrize(
    "role,group",
    [(CEO, "B1"), (D, "B2"), (VP, "B2"), (T10, None), (OTHER, None)],
)
def test_solo_buyers(events, role, group):
    _, ev = events(buy("s1", "01-MAR-2019", "100", [("9001", role)], value=150_000))
    assert [g for g, *_ in ev.values()] == ([group] if group else [])


def test_cooldown_is_91_days_per_issuer_and_group(events):
    _, ev = events(
        buy("k1", "01-JAN-2019", "100", [("9001", D)], value=150_000),
        buy("k2", "01-APR-2019", "100", [("9001", D)], value=150_000),  # day 90
        buy("k3", "31-JAN-2019", "100", [("9002", CEO)], value=150_000),  # other group
        buy("l1", "01-JAN-2019", "200", [("9001", D)], value=150_000),
        buy("l2", "02-APR-2019", "200", [("9001", D)], value=150_000),  # day 91
    )
    assert sorted(ev) == [
        "100:B1:2019-01-31",
        "100:B2:2019-01-01",
        "200:B2:2019-01-01",
        "200:B2:2019-04-02",
    ]


def test_signal_accession_is_the_highest_on_t(events):
    con, _ = events(
        buy("x-1", "01-MAR-2019", "100", [("9001", D)]),
        buy("x-3", "05-MAR-2019", "100", [("9002", T10)]),
        buy("x-2", "05-MAR-2019", "100", [("9003", T10)]),
    )
    assert con.execute("select signal_accession from evt.prelim_event").fetchall() == [("x-3",)]


def test_price_standin_and_labelled_window_flags(events):
    con, _ = events(
        buy("f1", "30-DEC-2011", "100", [("9001", CEO)], value=150_000),
        buy("f2", "03-JAN-2012", "200", [("9001", CEO)], value=150_000, price="1.5"),
        quarter="2011q4",
    )
    rows = con.execute(
        "select event_id, in_labelled_window, passes_price_standin from evt.prelim_event "
        "order by event_id"
    ).fetchall()
    assert rows == [("100:B1:2011-12-30", False, True), ("200:B1:2012-01-03", True, False)]
