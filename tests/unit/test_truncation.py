"""W9: rebuilding from records dated on or before T changes nothing dated on or before T (FR-023).

A synthetic two-year history at one issuer: separate buyers, a co-filing merge, a promotion to CEO,
a later joint purchase and a departure. Each cutoff rebuild must match the full build up to T.
"""

import pytest
from conftest import line, owner, sub

from sentinel.core import entities, gates
from sentinel.events import prelim


def buy(acc, date, tdate, owners, shares="1000", price="50", doc="4"):
    subs = [sub(acc, date=date, doc=doc)]
    own = [owner(acc, ocik=o, rel=rel, title=title) for o, rel, title in owners]
    lines = [line(acc, "1", tdate=tdate, shares=shares, price=price)] if doc == "4" else []
    return subs, own, lines


HISTORY = [
    buy("h01", "10-JAN-2018", "08-JAN-2018", [("9001", "Director", "")]),
    buy("h02", "16-JAN-2018", "12-JAN-2018", [("9002", "TenPercentOwner", "")], shares="1200"),
    buy("h03", "05-FEB-2018", "02-FEB-2018", [("9003", "Officer", "VP Sales")], shares="600"),
    buy(
        "h04",
        "01-JUN-2018",
        "",
        [("9002", "TenPercentOwner", ""), ("9004", "TenPercentOwner", "")],
        doc="3",
    ),
    buy(
        "h05",
        "04-SEP-2018",
        "31-AUG-2018",
        [("9004", "Officer", "Chief Executive Officer")],
        "3000",
    ),
    buy("h06", "10-SEP-2018", "07-SEP-2018", [("9002", "TenPercentOwner", "")], shares="800"),
    buy(
        "h07",
        "01-MAR-2019",
        "27-FEB-2019",
        [("9001", "Director", ""), ("9003", "Officer", "VP Sales")],
        shares="600",
    ),
    buy("h08", "05-MAR-2019", "04-MAR-2019", [("9005", "Director", "")], shares="2400"),
    buy("h09", "11-MAR-2019", "08-MAR-2019", [("9004", "Director", "")], shares="2500"),
    buy("h10", "20-DEC-2019", "18-DEC-2019", [("9006", "Director", "")], shares="2500"),
]
CUTOFFS = ["2018-06-01", "2018-09-09", "2019-03-04", "2019-03-11"]


@pytest.fixture
def full(archives, pipeline):
    tables = {"SUBMISSION": [], "REPORTINGOWNER": [], "NONDERIV_TRANS": []}
    for subs, own, lines in HISTORY:
        tables["SUBMISSION"] += subs
        tables["REPORTINGOWNER"] += own
        tables["NONDERIV_TRANS"] += lines
    archives({"2019q4": tables})
    return pipeline(until="prelim")


def snapshot(con, t):
    def rows(sql):
        return con.execute(sql, [t]).fetchall()

    return {
        "members": rows("select * from core.entity_member where valid_from <= ? order by all"),
        "roles": rows("select * from core.owner_role where valid_from <= ? order by all"),
        "purchases": rows("select * from core.clean_purchase where filing_date <= ? order by all"),
        "events": rows("select * from evt.prelim_event where signal_date <= ? order by all"),
        "event_members": rows(
            "select m.* from evt.prelim_event_member m join evt.prelim_event e using (event_id) "
            "where e.signal_date <= ? order by all"
        ),
    }


def test_history_produces_merges_promotions_and_events(full):
    snap = snapshot(full, "2019-12-31")
    assert len({r[2] for r in snap["members"]}) < 6  # some owners merged
    assert any(r[3] == "ceo_cfo" for r in snap["roles"])
    assert snap["events"], "the history should produce preliminary events"


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_cutoff_rebuild_matches_the_full_build(full, params, cutoff):
    expected = snapshot(full, cutoff)
    entities.build(full, params, cutoff=cutoff)
    gates.build(full, params, cutoff=cutoff)
    prelim.detect_prelim(full, params, cutoff=cutoff)
    assert snapshot(full, cutoff) == expected
    # nothing dated after the cutoff survives the cutoff build
    assert (
        full.execute(
            "select count(*) from core.clean_purchase where filing_date > ?", [cutoff]
        ).fetchone()[0]
        == 0
    )
