"""Layer 3b: the insider tracker: entities, roles, gates, buys and sells, holdings, clusters."""

from datetime import date

import pandas as pd
import pytest
from conftest import holding, line, note, owner, sub

from sentinel import db
from sentinel.core import insider
from sentinel.staging import sec_form4

QUIET = {"echo": lambda s: None}
STEPS = (
    insider.build_insider_filing,
    insider.build_insider_entities,
    insider.build_insider_trade,
    insider.build_insider_activity,
    insider.build_insider_cluster,
)


@pytest.fixture
def build(archives, tmp_data):
    """build({quarter: {TABLE: rows}}) stages the archives and runs every insider step."""
    cons = []

    def run(quarters):
        archives(quarters)
        con = db.connect(tmp_data)
        cons.append(con)
        sec_form4.stage_all(con, sec_form4.stored_archives(tmp_data))
        days = [d.date() for d in pd.bdate_range("2019-01-02", "2019-12-31")]
        con.register("_s", pd.DataFrame({"session": days}))
        con.execute(
            "create or replace table ref.calendar as "
            "select session, row_number() over (order by session) as session_no from _s"
        )
        con.unregister("_s")
        con.execute("create or replace table stg_sec_headers.header "
                    "(accession VARCHAR, accepted_at_et TIMESTAMP)")  # fmt: skip
        for step in STEPS:
            step(con, tmp_data, **QUIET)
        return con

    yield run
    for con in cons:
        con.close()


def test_co_filers_become_one_entity_and_roles_follow_the_latest_filing(build):
    con = build({"2019q1": {
        "SUBMISSION": [sub("a", date="08-MAR-2019"), sub("b", date="11-MAR-2019"),
                       sub("c", date="20-MAR-2019"), sub("d", date="25-MAR-2019")],
        "REPORTINGOWNER": [
            owner("a", ocik="9006", rel="TenPercentOwner", name="FUND GP LLC"),
            owner("b", ocik="9005", rel="TenPercentOwner", name="FUND LP"),
            owner("b", ocik="9006", rel="TenPercentOwner", name="FUND GP LLC"),
            owner("c", ocik="9003", rel="Officer", title="Chief Operating Officer"),
            owner("d", ocik="9003", rel="Officer", title="Chief Executive Officer"),
        ],
    }})  # fmt: skip
    members = con.execute(
        "select owner_cik, entity_id, valid_from from core.insider_entity_member "
        "where owner_cik in ('9005', '9006') order by valid_from, owner_cik"
    ).fetchall()
    assert members == [
        ("9006", "100:9006", date(2019, 3, 8)),  # alone at first
        ("9005", "100:9005", date(2019, 3, 11)),  # merged by the joint filing: lowest CIK names it
        ("9006", "100:9005", date(2019, 3, 11)),
    ]
    roles = con.execute(
        "select valid_from, role from core.insider_owner_role where owner_cik = '9003' order by 1"
    ).fetchall()
    assert roles == [(date(2019, 3, 20), "officer"), (date(2019, 3, 25), "ceo_cfo")]


def test_gates_keep_clean_purchases_and_flag_planned_and_offering_ones(build):
    filings = {
        "ok": ([line("ok", "1", after="11000")], "4"),
        "plan": ([line("plan", "1", TRANS_PRICEPERSHARE_FN="F1")], "4"),
        "offer": ([line("offer", "1", TRANS_SHARES_FN="F1")], "4"),
        "small": ([line("small", "1", shares="100")], "4"),  # $5,000
        "amend": ([line("amend", "1")], "4/A"),
        "pref": ([line("pref", "1", title="Series A Preferred Stock")], "4"),
        "late": ([line("late", "1", tdate="02-JAN-2019")], "4"),  # filed 72 days later
        "sale": ([line("sale", "1", code="S", ad="D", shares="500", price="55", after="0",
                       EQUITY_SWAP_TRANS_CD_FN="F1")], "4"),  # the code's footnote
    }  # fmt: skip
    con = build({"2019q1": {
        "SUBMISSION": [sub(acc, doc=doc) for acc, (_, doc) in filings.items()],
        "REPORTINGOWNER": [owner(acc) for acc in filings],
        "NONDERIV_TRANS": [row for rows, _ in filings.values() for row in rows],
        "NONDERIV_HOLDING": [holding("ok", "h1", shares="500")],
        "FOOTNOTES": [note("plan", "F1", "Bought under a Rule 10b5-1 trading plan."),
                      note("offer", "F1", "Bought in the Company's underwritten public offering."),
                      note("sale", "F1", "Sold pursuant to a 10b5-1 plan adopted in 2018."),
                      note("ok", "F9", "A 10b5-1 note the line does not cite.")],
    }})  # fmt: skip
    got = {
        acc: (side, clean, planned, offering)
        for acc, side, clean, planned, offering in con.execute(
            "select accession, side, clean, planned, offering from core.insider_activity"
        ).fetchall()
    }
    assert got == {
        "ok": ("buy", True, False, False),
        "plan": ("buy", False, True, False),
        "offer": ("buy", False, False, True),
        "small": ("buy", False, False, False),
        "sale": ("sell", False, True, False),
    }  # the amendment, the preferred shares and the late filing are not open-market lines
    funnel = con.execute(
        "select gate, rows_in, rows_out from core.insider_funnel order by step"
    ).fetchall()
    assert funnel[0] == ("g1_form4", 8, 7)  # the 4/A
    assert funnel[-1] == ("g6b_min_value", 2, 1)  # "ok" and "small" pass the lines; "small" < $25k


def test_holdings_before_and_after_include_untraded_rows(build):
    con = build({"2019q1": {
        "SUBMISSION": [sub("add"), sub("new", cik="200"), sub("out", cik="300")],
        "REPORTINGOWNER": [owner("add"), owner("new"), owner("out")],
        "NONDERIV_TRANS": [
            line("add", "1", shares="1000", after="11000"),
            line("new", "1", shares="1000", after="1000"),
            line("out", "1", code="S", ad="D", shares="700", after="0"),
        ],
        "NONDERIV_HOLDING": [holding("add", "h1", shares="500")],
    }})  # fmt: skip
    got = {r[0]: r[1:] for r in con.execute(
        "select accession, shares_before, shares_after, opens_position, closes_position "
        "from core.insider_activity").fetchall()}  # fmt: skip
    assert got == {
        "add": (10500.0, 11500.0, False, False),  # 10,000 direct + 500 by trust before
        "new": (0.0, 1000.0, True, False),
        "out": (700.0, 0.0, False, True),
    }


def test_clusters_need_two_buyers_or_one_senior_one_and_events_cool_down(build):
    con = build({"2019q1": {
        "SUBMISSION": [
            sub("a1", date="04-MAR-2019"), sub("b1", date="11-MAR-2019"),
            sub("a2", date="15-MAR-2019"),
            sub("c1", date="11-MAR-2019", cik="200"),
            sub("f1", date="11-MAR-2019", cik="300"), sub("g1", date="12-MAR-2019", cik="300"),
        ],
        "REPORTINGOWNER": [
            owner("a1", ocik="9001"), owner("b1", ocik="9002"), owner("a2", ocik="9001"),
            owner("c1", ocik="9300", rel="Officer", title="Chief Executive Officer"),
            owner("f1", ocik="9400", rel="TenPercentOwner"),
            owner("g1", ocik="9401", rel="TenPercentOwner"),
        ],
        "NONDERIV_TRANS": [
            line("a1", "1", tdate="01-MAR-2019", shares="1200"),  # $60k
            line("b1", "1", tdate="08-MAR-2019"),  # $50k
            line("a2", "1", tdate="14-MAR-2019"),  # $50k
            line("c1", "1", tdate="08-MAR-2019", shares="3000"),  # $150k
            line("f1", "1", tdate="08-MAR-2019", shares="2000"),
            line("g1", "1", tdate="08-MAR-2019", shares="2000"),
        ],
    }})  # fmt: skip
    got = con.execute(
        "select issuer_cik, cluster_date, grp, n_entities, total_value_usd, starts_event, known_at "
        "from core.insider_cluster order by all"
    ).fetchall()
    assert got == [
        ("100", date(2019, 3, 11), "A", 2, 110_000.0, True, date(2019, 3, 12)),
        ("100", date(2019, 3, 15), "A", 2, 160_000.0, False, date(2019, 3, 18)),  # same run
        ("200", date(2019, 3, 11), "B1", 1, 150_000.0, True, date(2019, 3, 12)),
    ]  # two 10% owners (CIK 300) are no group: A needs an officer or director
