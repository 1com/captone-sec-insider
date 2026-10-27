"""Features F1–F29 as of T (feature 006 research R8–R10; plan §7.2; constitution I)."""

import math
from datetime import date

import pytest
from conftest import REPO, market_prices, market_sessions

from sentinel import warehouse
from sentinel.config import Paths, load_params
from sentinel.features import build as features

T = date(2021, 6, 1)  # a Tuesday
LATE = date(2023, 3, 1)  # after the development period: no F10


@pytest.fixture(scope="module")
def params():
    return load_params(REPO / "config" / "params.yaml")


def _tables(con, days, t_no):
    con.execute(
        'create table evt.event (event_id VARCHAR, issuer_cik VARCHAR, "group" VARCHAR, '
        "signal_date DATE, t_session DATE, priced BOOLEAN, n_entities BIGINT, "
        "total_value_usd DOUBLE, market_cap DOUBLE, addv20 DOUBLE, g7_sic VARCHAR, "
        "price_source VARCHAR)"
    )
    con.executemany(
        "insert into evt.event values (?, '1', 'A', ?, ?, true, 3, 300000, 5e7, 1e6, '3674', "
        "'yahoo')",
        [("E1", T, T), ("E3", LATE, LATE)],
    )
    con.execute("create table evt.event_cost (event_id VARCHAR, volatility DOUBLE, spread DOUBLE)")
    con.executemany("insert into evt.event_cost values (?, 0.03, 0.01)", [("E1",), ("E3",)])
    con.execute(
        "create table evt.event_member (event_id VARCHAR, accession VARCHAR, "
        "entity_id_at_t VARCHAR, entity_role_at_t VARCHAR, value_usd DOUBLE)"
    )
    members = [("a1", "1:100", "ceo_cfo", 100_000), ("a2", "1:200", "director", 150_000),
               ("a3", "1:300", "director", 50_000)]  # fmt: skip
    con.executemany("insert into evt.event_member values (?, ?, ?, ?, ?)",
                    [(e, *m) for e in ("E1", "E3") for m in members])  # fmt: skip
    con.execute(
        "create table core.clean_purchase (accession VARCHAR, issuer_cik VARCHAR, "
        "filing_date DATE, shares_before DOUBLE, shares_after DOUBLE, opens_position BOOLEAN)"
    )
    con.executemany(
        "insert into core.clean_purchase values (?, '1', ?, ?, ?, ?)",
        [
            ("a1", date(2021, 5, 28), 1000, 2000, False),
            ("a2", date(2021, 5, 31), 0, 500, True),
            ("a3", date(2021, 6, 1), 4000, 5000, False),
            ("c_year", date(2020, 8, 3), 10, 20, False),  # F14: in the 365 days, before the window
            ("c_window", date(2021, 5, 20), 10, 20, False),  # inside the window: not F14
            ("c_old", date(2020, 5, 1), 10, 20, False),  # more than 365 days before T
            ("c_after", date(2021, 6, 2), 10, 20, False),
        ],  # after T  # fmt: skip
    )
    con.execute(
        "create table core.transaction (accession VARCHAR, issuer_cik VARCHAR, "
        "filing_date DATE, document_type VARCHAR, trans_date DATE, trans_code VARCHAR, "
        "value_usd DOUBLE, passes_lines BOOLEAN)"
    )
    lines = [
        ("a1", date(2021, 5, 28), date(2021, 5, 26), "P", 100_000, True),
        ("a2", date(2021, 5, 31), date(2021, 5, 27), "P", 150_000, True),
        ("a3", date(2021, 6, 1), date(2021, 5, 28), "P", 50_000, True),
        ("s_in", date(2021, 4, 15), date(2021, 4, 13), "S", 40_000, False),
        ("s_old", date(2021, 1, 10), date(2021, 1, 8), "S", 99_999, False),
        ("s_after", date(2021, 6, 2), date(2021, 6, 1), "S", 77_777, False),
    ]
    # F9 histories: owner 101 trades every March (routine); 201 in three different months
    for y in (2018, 2019, 2020):
        lines.append((f"r{y}", date(y, 3, 20), date(y, 3, 18), "P", 1, False))
        lines.append((f"o{y}", date(y, {2018: 3, 2019: 7, 2020: 11}[y], 20),
                      date(y, {2018: 3, 2019: 7, 2020: 11}[y], 18), "S", 1, False))  # fmt: skip
    lines.append(("u2020", date(2020, 5, 20), date(2020, 5, 18), "P", 1, False))
    con.executemany("insert into core.transaction values (?, '1', ?, '4', ?, ?, ?, ?)", lines)
    con.execute("create table stg.reportingowner (accession_number VARCHAR, rptownercik VARCHAR)")
    owners = [("a1", "101"), ("a2", "201"), ("a3", "301"), ("s_in", "900"), ("s_old", "900"),
              ("s_after", "900"), ("u2020", "301")]  # fmt: skip
    owners += [(f"r{y}", "101") for y in (2018, 2019, 2020)]
    owners += [(f"o{y}", "201") for y in (2018, 2019, 2020)]
    con.executemany("insert into stg.reportingowner values (?, ?)", owners)
    con.execute(
        "create table core.owner_role (issuer_cik VARCHAR, owner_cik VARCHAR, valid_from DATE, "
        "role VARCHAR)"
    )
    con.execute("insert into core.owner_role values ('1', '900', '2019-01-01', 'ceo_cfo')")
    con.execute(
        "create table core.company_filing (issuer_cik VARCHAR, accession VARCHAR, "
        "form VARCHAR, filing_date DATE)"
    )
    con.executemany("insert into core.company_filing values ('1', ?, ?, ?)",
                    [("q1", "10-Q", date(2021, 5, 10)), ("k1", "10-K", date(2021, 2, 20)),
                     ("q2", "10-Q", date(2021, 8, 10)),
                     ("e1", "8-K", date(2021, 5, 25))])  # fmt: skip
    con.execute(
        "create table core.xbrl_fact (issuer_cik VARCHAR, concept VARCHAR, "
        "period_start DATE, period_end DATE, value DOUBLE, filed DATE)"
    )
    q1, fy = (date(2021, 1, 1), date(2021, 3, 31)), (date(2020, 1, 1), date(2020, 12, 31))
    con.executemany(
        "insert into core.xbrl_fact values ('1', ?, ?, ?, ?, ?)",
        [
            ("equity", None, q1[1], 2e7, date(2021, 5, 10)),
            ("equity", None, date(2021, 6, 30), 999, date(2021, 8, 10)),  # filed after T
            ("assets", None, q1[1], 1e8, date(2021, 5, 10)),
            ("cash", None, q1[1], 1e7, date(2021, 5, 10)),
            ("net_income", *q1, -1e6, date(2021, 5, 10)),
            ("net_income", date(2020, 10, 1), q1[1], 3e6, date(2021, 5, 10)),  # longer period
            ("net_income", *fy, 5e6, date(2021, 2, 20)),
        ],
    )
    con.execute(
        "create table core.sic_industry (scheme INTEGER, industry_no INTEGER, "
        "industry VARCHAR, description VARCHAR, sic_from INTEGER, sic_to INTEGER)"
    )
    con.execute("insert into core.sic_industry values (12, 6, 'BusEq', 'Business Eq.', 3660, "
                "3692)")  # fmt: skip
    con.execute(
        "create table lab.event_label (event_id VARCHAR, horizon INTEGER, measure VARCHAR, "
        "exit_session DATE, net DOUBLE)"
    )
    con.executemany(
        "insert into lab.event_label values (?, 63, 'ind_ew', ?, ?)",
        [
            ("x1", date(2020, 1, 15), 0.05),
            ("x2", date(2020, 6, 15), -0.02),
            ("x3", date(2021, 3, 15), 0.01),
            ("x_old", date(2017, 1, 15), 0.9),  # more than 36 months before T
            ("x_late", date(2021, 9, 15), 0.9),
        ],  # ends after T  # fmt: skip
    )
    con.execute(
        "create table lab.purchase_outcome (event_id VARCHAR, accession VARCHAR, "
        "entity_id_at_t VARCHAR, exit_session DATE, net DOUBLE)"
    )
    con.executemany(
        "insert into lab.purchase_outcome values ('E1', ?, ?, ?, ?)",
        [
            ("p1", "1:100", date(2020, 9, 1), 0.03),
            ("p2", "1:100", date(2021, 2, 1), -0.01),
            ("p3", "1:300", date(2021, 2, 1), None),
        ],  # unknown net: not counted
    )


@pytest.fixture(scope="module")
def feat(tmp_path_factory, params):
    paths = Paths.from_root(tmp_path_factory.mktemp("features"))
    con = warehouse.connect(paths)
    days = market_sessions(con, date(2019, 1, 2), 1100)
    t_no = days.index(T)
    rows = []
    for i, d in enumerate(days):
        close = 10 * 1.001**i
        high = 2 * close if i == t_no - 100 else close  # the 52-week high
        rows.append({"session": d, "close": close, "high": high})
    market_prices(con, "1", rows)
    _tables(con, days, t_no)
    features.build(con, params)
    yield con, days, t_no, rows
    con.close()


def row(con, event="E1") -> dict:
    cur = con.execute("select * from feat.event_features where event_id = ?", [event])
    return dict(zip([d[0] for d in cur.description], cur.fetchone(), strict=True))


def test_insider_features(feat):
    r = row(feat[0])
    assert (r["f1"], r["f2"], r["f3"], r["f4"], r["f5"], r["f6"]) == (3, 300_000, 0.5, 1, 2, 0)
    assert r["f7"] == pytest.approx((math.log(2) + math.log(1.25)) / 2)
    assert r["f8"] == 1
    assert r["f11"] == pytest.approx(10 / 3)


def test_selling_and_repeat_buying_look_back_only_to_t(feat):
    r = row(feat[0])
    assert (r["f12"], r["f13"], r["f14"]) == (40_000, 1, 1)
    assert r["f15"] == 22  # the 10-Q of 10 May; the 10-Q of August is after T


def test_routine_and_opportunistic_buyers(feat):
    r = row(feat[0])
    assert (r["f9"], r["f9_classified"]) == (0.5, 2)  # 101 routine, 201 opportunistic


def test_past_hit_rate_shrinks_to_the_base_rate(feat):
    r = row(feat[0])
    p = 2 / 3  # x1 and x3 of the three windows ending in the 36 months before T
    expected = ((1 + 5 * p) / (2 + 5) + p + p) / 3
    assert r["f10"] == pytest.approx(expected) and r["f10_history"] == 2
    assert row(feat[0], "E3")["f10"] is None  # signal after 2022: filled by the holdout job


def test_market_and_company_features(feat):
    con, days, t_no, rows = feat
    r = row(con)
    assert (r["f16"], r["f17"], r["f18"], r["f22"], r["f23"]) == (5e7, 1e6, 0.3, 0.03, 0.01)
    assert r["f19"] == pytest.approx(1.001**21 - 1)
    assert r["f20"] == pytest.approx(1.001**231 - 1)
    assert r["f21"] == pytest.approx(rows[t_no]["close"] / rows[t_no - 100]["high"])
    assert r["f24"] == "BusEq" and r["f25"] == pytest.approx(0.006)
    assert (r["f26"], r["f27"], r["f28"], r["f29"]) == (0.4, 1.0, 0.8, 0.1)


def test_truncation_after_t_changes_nothing(feat, params):
    """Constitution I: delete every record dated after T, rebuild, and E1's features stay."""
    con = feat[0]
    before = row(con)
    for table, column in [("core.clean_purchase", "filing_date"),
                          ("core.transaction", "filing_date"),
                          ("core.company_filing", "filing_date"), ("core.xbrl_fact", "filed"),
                          ("core.price_daily", "session"), ("evt.event", "signal_date"),
                          ("lab.event_label", "exit_session"),
                          ("lab.purchase_outcome", "exit_session")]:  # fmt: skip
        con.execute(f"delete from {table} where {column} > ?", [T])
    con.execute("delete from evt.event_member where event_id = 'E3'")
    features.build(con, params)
    assert row(con) == before
