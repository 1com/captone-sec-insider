"""Layer 3b: the insider tracker: entities, roles, gates, buys and sells, holdings, clusters."""

from datetime import date

import pandas as pd
import pytest
from conftest import holding, line, note, owner, sub

from sentinel import db
from sentinel.core import insider
from sentinel.raw.manifest import Manifest, store_gz
from sentinel.staging import sec_form4, sec_form4_daily

QUIET = {"echo": lambda s: None}
STEPS = (
    insider.build_insider_filing,
    insider.build_insider_entities,
    insider.build_insider_trade,
    insider.build_insider_activity,
    insider.build_insider_cluster,
    insider.build_form4_reconciliation,
)


def filing(
    acc: str, filed: date, accepted: str, owners=("9001",), lines=(("1000", "50"),)
) -> bytes:
    """A Form 4 submission as the SEC serves it: header, then `ownershipDocument`; a director's
    open-market purchases of (shares, price) on 13 March 2019 at issuer 100."""
    who = "".join(
        f"<reportingOwner><reportingOwnerId><rptOwnerCik>{o}</rptOwnerCik><rptOwnerName>Owner {o}"
        "</rptOwnerName></reportingOwnerId><reportingOwnerRelationship><isDirector>1</isDirector>"
        "</reportingOwnerRelationship></reportingOwner>"
        for o in owners
    )
    trades = "".join(
        "<nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>"
        "<transactionDate><value>2019-03-13</value></transactionDate><transactionCoding>"
        "<transactionFormType>4</transactionFormType><transactionCode>P</transactionCode>"
        "<equitySwapInvolved>0</equitySwapInvolved></transactionCoding><transactionAmounts>"
        f"<transactionShares><value>{shares}</value></transactionShares><transactionPricePerShare>"
        f"<value>{price}</value></transactionPricePerShare><transactionAcquiredDisposedCode>"
        "<value>A</value></transactionAcquiredDisposedCode></transactionAmounts><ownershipNature>"
        "<directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>"
        "</nonDerivativeTransaction>"
        for shares, price in lines
    )
    return (
        f"<SEC-DOCUMENT>{acc}.txt\n<SEC-HEADER>{acc}.hdr.sgml\n<ACCEPTANCE-DATETIME>{accepted}\n"
        f"ACCESSION NUMBER:\t\t{acc}\nCONFORMED SUBMISSION TYPE:\t4\n"
        f"FILED AS OF DATE:\t\t{filed:%Y%m%d}\n</SEC-HEADER>\n<DOCUMENT>\n<TYPE>4\n<TEXT>\n<XML>\n"
        '<?xml version="1.0"?>\n<ownershipDocument><documentType>4</documentType>'
        "<periodOfReport>2019-03-13</periodOfReport><issuer><issuerCik>0000000100</issuerCik>"
        "<issuerName>Abc Corp</issuerName><issuerTradingSymbol>ABC</issuerTradingSymbol></issuer>"
        f"{who}<nonDerivativeTable>{trades}</nonDerivativeTable></ownershipDocument>\n</XML>\n"
        "</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
    ).encode()


@pytest.fixture
def build(archives, tmp_data):
    """build({quarter: {TABLE: rows}}, {accession: submission}) stages the archives and the daily
    filings, then runs every insider step."""
    cons = []

    def run(quarters, daily=None, market=None):
        archives(quarters)
        book = Manifest(tmp_data.manifest)
        for acc, data in (daily or {}).items():
            store_gz(tmp_data, book, sec_form4_daily.SOURCE, f"sec/form4/2019/{acc}.txt.gz", acc,
                     data, "stand-in")  # fmt: skip
        con = db.connect(tmp_data)
        cons.append(con)
        sec_form4.stage_all(con, sec_form4.stored_archives(tmp_data))
        if daily:
            sec_form4_daily.stage(con, tmp_data, **QUIET)
        days = [d.date() for d in pd.bdate_range("2019-01-02", "2019-12-31")]
        con.register("_s", pd.DataFrame({"session": days}))
        con.execute(
            "create or replace table ref.calendar as "
            "select session, row_number() over (order by session) as session_no from _s"
        )
        con.unregister("_s")
        con.execute("create or replace table stg_sec_headers.header "
                    "(accession VARCHAR, accepted_at_et TIMESTAMP)")  # fmt: skip
        if market:  # (close, shares): issuer 100's price all year and share count
            close, shares = market
            con.execute(
                f"create or replace table core.price_daily as select '100' as cik, "
                f"session, {close}::DOUBLE as close from ref.calendar"
            )
            con.execute(
                f"create or replace table core.shares_outstanding as select '100' as cik, "
                f"DATE '2019-01-02' as known_at, {shares}::DOUBLE as shares"
            )
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


def test_daily_filings_fill_in_after_the_data_sets_which_win_where_both_have_one(build):
    con = build(
        {"2019q1": {"SUBMISSION": [sub("q"), sub("same"), sub("cents")],
                    "REPORTINGOWNER": [owner("q"), owner("same"), owner("cents")],
                    "NONDERIV_TRANS": [line("q", "1"), line("same", "1"),
                                       line("cents", "1"), line("cents", "2", shares="10",
                                                                price="2.01")]}},
        {"q": filing("q", date(2019, 3, 15), "20190315100000", lines=[("2000", "50")]),
         "same": filing("same", date(2019, 3, 15), "20190315100000"),
         "cents": filing("cents", date(2019, 3, 15), "20190315100000",
                         lines=[("1000", "50.004"), ("10", "2.005")]),
         "d": filing("d", date(2019, 3, 20), "20190320153000", owners=["9002"]),
         "late": filing("late", date(2019, 3, 20), "20190320171000", owners=["9003"])},
    )  # fmt: skip
    got = {r[0]: r[1:] for r in con.execute(
        "select accession, quarter, known_at, value_usd, owner_ciks from core.insider_activity"
    ).fetchall()}  # fmt: skip
    assert got == {
        "q": ("2019q1", date(2019, 3, 15), 50_000.0, ["9001"]),  # the data set's 1,000 shares
        "same": ("2019q1", date(2019, 3, 15), 50_000.0, ["9001"]),
        "cents": ("2019q1", date(2019, 3, 15), 50_020.1, ["9001"]),
        "d": ("2019q1", date(2019, 3, 20), 50_000.0, ["9002"]),  # accepted before the close
        "late": ("2019q1", date(2019, 3, 21), 50_000.0, ["9003"]),  # after it: the next session
    }
    (filed,) = con.execute("select known_at from core.insider_filing where accession = 'q'"
                           ).fetchone()  # fmt: skip
    assert filed == date(2019, 3, 15)  # the daily copy's acceptance time, 10:00 that day
    diff = con.execute(
        "select accession, owners_differ, lines_differ, value_differ, value_quarterly, value_daily "
        "from core.form4_reconciliation"
    ).fetchall()
    assert diff == [("q", False, False, True, 50_000.0, 100_000.0)]  # not "cents": the data set
    # rounds 50.004 to 50.00 and 2.005 to 2.01 (half up), as the filing's values give


def test_a_reconciliation_lists_different_owners_and_line_counts(build):
    con = build(
        {"2019q1": {"SUBMISSION": [sub("a")], "REPORTINGOWNER": [owner("a")],
                    "NONDERIV_TRANS": [line("a", "1")]}},
        {"a": filing("a", date(2019, 3, 15), "20190315100000", owners=["9001", "9009"],
                     lines=[("1000", "50"), ("0", "0")])},
    )  # fmt: skip
    (row,) = con.execute(
        "select owners_quarterly, owners_daily, lines_quarterly, lines_daily, owners_differ, "
        "lines_differ, value_differ from core.form4_reconciliation"
    ).fetchall()
    assert row == (["9001"], ["9001", "9009"], 1, 2, True, True, False)


def test_a_line_with_a_typed_in_price_or_size_loses_its_value(build):
    filings = {
        "big": [line("big", "1", shares="1000000", price="25")],  # more than the company
        "fine": [line("fine", "1", shares="100", price="25")],  # $2,500
        "pricey": [line("pricey", "1", shares="1", price="200000")],  # 10,000 times the close
        "class_a": [line("class_a", "1", shares="1", price="30000")],  # 1,500 times: a share class
        "award": [line("award", "1", code="A", price="0")],  # an award at $0: not a typo
    }
    con = build({"2019q1": {
        "SUBMISSION": [sub(acc) for acc in filings],
        "REPORTINGOWNER": [owner(acc) for acc in filings],
        "NONDERIV_TRANS": [row for rows in filings.values() for row in rows],
    }}, market=(20, 1_000_000))  # $20 a share, worth $20 million  # fmt: skip
    got = con.execute("select accession, shares, value_usd, value_typo, open_market "
                      "from core.insider_trade order by 1").fetchall()  # fmt: skip
    assert got == [("award", 1000.0, 0.0, False, False), ("big", 1e6, None, True, True),
                   ("class_a", 1.0, 30000.0, False, True), ("fine", 100.0, 2500.0, False, True),
                   ("pricey", 1.0, None, True, True)]  # fmt: skip
