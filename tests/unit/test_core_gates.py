"""Step 4: production gates, clean purchases, holdings and the funnel (FR-009 – FR-013, W5, W6)."""

import pytest
from conftest import holding, line, note, owner, sub

from sentinel.core import gates


@pytest.fixture
def run(archives, pipeline):
    def go(subs, owners, lines, notes=(), holdings=(), quarter="2019q1", extra=None):
        quarters = {
            quarter: {
                "SUBMISSION": subs,
                "REPORTINGOWNER": owners,
                "NONDERIV_TRANS": lines,
                "FOOTNOTES": list(notes),
                "NONDERIV_HOLDING": list(holdings),
            }
        }
        quarters.update(extra or {})
        archives(quarters)
        return pipeline(until="gates")

    return go


def passes(con, acc, sk="1"):
    return con.execute(
        "select passes_lines from core.transaction where accession = ? and line_sk = ?", [acc, sk]
    ).fetchone()[0]


def clean(con):
    return dict(con.execute("select accession, value_usd from core.clean_purchase").fetchall())


def one(con, acc, cols="shares_before, shares_after, opens_position"):
    return con.execute(
        f"select {cols} from core.clean_purchase where accession = ?", [acc]
    ).fetchone()


def test_one_exclusion_per_gate(run):
    accs = ["g1", "g2", "g3", "g4b", "g5", "g6a", "g6a_price", "g6b", "ok"]
    con = run(
        [sub(a, doc="4/A" if a == "g1" else "4") for a in accs],
        [owner(a) for a in accs],
        [
            line("g1", "1"),
            line("g2", "1", code="S", ad="D"),
            line("g3", "1", title="Series A Preferred Stock"),
            line("g4b", "1", TRANS_PRICEPERSHARE_FN="F1"),
            line("g5", "1", NATURE_OF_OWNERSHIP_FN="F2"),
            line("g6a", "1", tdate="12-FEB-2019"),
            line("g6a_price", "1", price=""),
            line("g6b", "1", shares="999", price="10"),
            line("ok", "1"),
        ],
        [
            note("g4b", "F1", "Purchased under a Rule 10b5-1 trading plan."),
            note("g5", "F2", "Bought in the company's underwritten public offering."),
        ],
    )
    first_failed = dict(
        con.execute(
            "select accession, case when not g1_form4 then 'g1' when not g2_purchase then 'g2' "
            "when not g3_common then 'g3' when not g4a_no_checkbox then 'g4a' "
            "when not g4b_no_plan_fn then 'g4b' when not g5_no_offering_fn then 'g5' "
            "when not g6a_timely_valued then 'g6a' end from core.transaction"
        ).fetchall()
    )
    assert first_failed == {
        "g1": "g1",
        "g2": "g2",
        "g3": "g3",
        "g4b": "g4b",
        "g5": "g5",
        "g6a": "g6a",
        "g6a_price": "g6a",
        "g6b": None,
        "ok": None,
    }
    assert clean(con) == {"ok": 50000.0}
    missing_price = con.execute(
        "select value_usd from core.transaction where accession = 'g6a_price'"
    ).fetchone()[0]
    assert missing_price is None


def test_only_footnotes_cited_by_the_line_count(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [line("a", "1"), line("a", "2", SECURITY_TITLE_FN="F1")],
        [note("a", "F1", "These shares were acquired through the issuer's ESPP.")],
    )
    assert passes(con, "a", "1") and not passes(con, "a", "2")


def test_footnote_ids_come_from_every_footnote_column(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [line("a", "1", TRANS_SHARES_FN="F2, F1", NATURE_OF_OWNERSHIP_FN="F3")],
    )
    assert con.execute("select fn_ids from core.transaction").fetchone()[0] == ["F1", "F2", "F3"]


def test_ticked_checkbox_excludes_every_line_of_the_filing(run):
    con = run(
        [sub("t", date="15-FEB-2023", aff="1"), sub("u", date="15-FEB-2023", aff="0")],
        [owner("t"), owner("u")],
        [line(a, sk, tdate="13-FEB-2023") for a in ("t", "u") for sk in ("1", "2")],
        quarter="2023q1",
    )
    assert not passes(con, "t", "1") and not passes(con, "t", "2")
    assert passes(con, "u", "1") and passes(con, "u", "2")


def test_timeliness(run):
    con = run(
        [sub("a"), sub("b"), sub("c")],
        [owner(x) for x in "abc"],
        [
            line("a", "1", tdate="13-FEB-2019"),  # 30 days
            line("b", "1", tdate="12-FEB-2019"),  # 31 days
            line("c", "1", tdate="16-MAR-2019"),  # after the filing
        ],
    )
    assert passes(con, "a") and not passes(con, "b") and not passes(con, "c")


def test_minimum_value_per_filing(run, params):
    floor = params["registered"]["g6_min_value"]["value"]
    con = run(
        [sub("a"), sub("b")],
        [owner("a"), owner("b")],
        [
            line("a", "1", shares=str(floor / 20), price="10"),
            line("a", "2", shares=str(floor / 20), price="10"),
            line("b", "1", shares=str(floor / 10 - 0.01), price="10"),
        ],
    )
    assert clean(con) == {"a": float(floor)}


def test_entity_and_role_are_taken_at_the_filing_date(run):
    con = run(
        [
            sub("old", date="01-FEB-2019"),
            sub("join", date="01-MAR-2019", doc="3"),
            sub("buy", date="15-MAR-2019"),
        ],
        [
            owner("old", ocik="9002", rel="TenPercentOwner"),
            owner("join", ocik="9001", rel="Director, Officer", title="Chief Executive Officer"),
            owner("join", ocik="9002", rel="TenPercentOwner"),
            owner("buy", ocik="9002", rel="TenPercentOwner"),
        ],
        [line("old", "1", tdate="30-JAN-2019"), line("buy", "1")],
    )
    rows = con.execute(
        "select accession, entity_id, entity_role, entity_seniority, owner_ciks "
        "from core.clean_purchase order by filing_date"
    ).fetchall()
    assert rows == [
        ("old", "100:9002", "ten_pct", 1, ["9002"]),
        ("buy", "100:9001", "ceo_cfo", 4, ["9002"]),
    ]


def test_holdings_direct_plus_indirect(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [
            line("a", "1", shares="400", price="100", after="1000", di="D"),
            line("a", "2", code="J", shares="0", after="2000", di="I", nature="By Trust"),
        ],
    )
    assert one(con, "a") == (2600.0, 3000.0, False)


def test_holdings_two_trades_on_one_holding(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [
            line("a", "1", shares="100", price="100", after="1100"),
            line("a", "2", shares="200", price="100", after="1300"),
        ],
    )
    assert one(con, "a") == (1000.0, 1300.0, False)


def test_untraded_holding_adds_to_both(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [line("a", "1", shares="400", price="100", after="1000")],
        holdings=[holding("a", "1", shares="500")],
    )
    assert one(con, "a") == (1100.0, 1500.0, False)


def test_same_filing_sale_is_added_back(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [
            line("a", "1", shares="500", price="100", after="1500"),
            line("a", "2", code="S", ad="D", shares="200", after="1300"),
        ],
    )
    assert one(con, "a") == (1000.0, 1300.0, False)


def test_negative_before_is_null_and_new_position_is_flagged(run):
    con = run(
        [sub("neg"), sub("new")],
        [owner("neg"), owner("new", ocik="9002")],
        [
            line("neg", "1", shares="1000", after="100"),
            line("new", "1", shares="1000", after="1000"),
        ],
    )
    assert one(con, "neg") == (None, 100.0, None)
    assert one(con, "new") == (0.0, 1000.0, True)


def test_lines_are_deduplicated_across_quarters(run):
    con = run(
        [sub("a")],
        [owner("a")],
        [line("a", "1")],
        extra={
            "2019q2": {
                "SUBMISSION": [sub("a")],
                "REPORTINGOWNER": [owner("a")],
                "NONDERIV_TRANS": [line("a", "1")],
            }
        },
    )
    assert con.execute("select quarter, count(*) from core.transaction group by 1").fetchall() == [
        ("2019q1", 1)
    ]
    assert con.execute("select count(*) from core.clean_purchase").fetchone()[0] == 1


def test_funnel_reconciles_and_values_meet_the_minimum(run, params):
    con = run(
        [sub("a"), sub("b", doc="4/A"), sub("c")],
        [owner("a"), owner("b"), owner("c")],
        [
            line("a", "1"),
            line("a", "2", ad="D", code="S"),
            line("b", "1"),
            line("a", "3", title="Warrants"),
            line("c", "1", shares="10", price="10"),
        ],
    )
    assert gates.check_funnel(con) == []
    assert gates.check_min_value(con, params) == []
    rows = con.execute(
        "select gate, unit, rows_in, rows_out, rows_removed from audit.funnel order by step"
    ).fetchall()
    assert [r[0] for r in rows] == [*gates.LINE_GATES, "g6b_min_value"]
    assert rows[0][2] == 5
    assert rows[-1][1:] == ("filings", 2, 1, 1)
