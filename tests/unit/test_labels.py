"""Development labels and purchase outcomes (feature 006 research R2–R8; plan §6.6, §6.7)."""

import math
from datetime import date

import pytest
from conftest import REPO, market_prices, market_sessions

from sentinel import warehouse
from sentinel.config import Paths, load_params
from sentinel.core import prices
from sentinel.labels import build as labels

T = date(2021, 6, 1)  # a Tuesday
LATE_T = date(2022, 8, 1)  # its 126- and 252-session windows end in 2023
FACTORS = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom")
RF = 0.0001


def factor(name: str, k: int) -> float:
    """Deterministic, varied, non-collinear factor returns."""
    phase = {
        "mkt_rf": (1.0, 0.0, 0.010),
        "smb": (1.3, 0.5, 0.006),
        "hml": (0.7, 1.0, 0.005),
        "rmw": (0.4, 1.5, 0.004),
        "cma": (1.9, 2.0, 0.003),
        "mom": (2.3, 2.5, 0.005),
    }[name]
    return phase[2] * math.sin(phase[0] * k + phase[1])  # fmt: skip


def path(days, returns, start=100.0, bad_open=()):
    """Bars whose open is the previous close, so open-to-close is the whole day's return."""
    rows, close = [], start
    for i, (d, r) in enumerate(zip(days, returns, strict=True)):
        prev, close = close, close * (1 + r)
        opn = 0.0 if i in bad_open else prev
        rows.append({"session": d, "open": opn, "close": close, "high": max(prev, close),
                     "low": min(prev, close)})  # fmt: skip
    return rows


@pytest.fixture(scope="module")
def params():
    return load_params(REPO / "config" / "params.yaml")


@pytest.fixture(scope="module")
def lab(tmp_path_factory, params):
    """One synthetic warehouse for the module (building it takes a few seconds)."""
    tmp_data = Paths.from_root(tmp_path_factory.mktemp("labels"))
    con = warehouse.connect(tmp_data)
    days = market_sessions(con, date(2020, 1, 2), 800)
    no = {d: i for i, d in enumerate(days)}
    t, late = no[T], no[LATE_T]
    flat = [0.01] * len(days)
    market_prices(con, "1", path(days, flat))  # also the purchase-outcome issuer
    market_prices(con, "2", path(days, [
        RF + (0.0002 if i <= t else 0.003) + 1.5 * factor("mkt_rf", i) + 0.5 * factor("smb", i)
        for i in range(len(days))]))  # fmt: skip
    market_prices(con, "3", path(days[: t + 31], flat[: t + 31]))  # last price at T+30
    market_prices(con, "4", path(days, flat, bad_open={t + 1}))
    con.execute(f"create table stg.price_yahoo ({prices.YAHOO_COLUMNS})")
    for ticker, r in (("SPY", 0.005), ("IWM", 0.002)):
        con.executemany(
            "insert into stg.price_yahoo values (?, ?, ?, ?, ?, ?, 1e6, ?, 0, 1, 'x')",
            [(ticker, b["session"], b["open"], b["high"], b["low"], b["close"], b["close"])
             for b in path(days, [r] * len(days))],
        )  # fmt: skip
    con.execute("create table core.ff_factor_daily (date DATE, factor VARCHAR, ret DOUBLE)")
    con.executemany(
        "insert into core.ff_factor_daily values (?, ?, ?)",
        [(d, f, factor(f, i)) for i, d in enumerate(days) for f in FACTORS]
        + [(d, "rf", RF) for d in days],
    )
    con.execute(
        "create table core.ff_industry_daily (date DATE, scheme INTEGER, industry_no INTEGER, "
        "industry VARCHAR, weighting VARCHAR, ret DOUBLE)"
    )
    for ind, name, ew, vw in ((36, "Chips", 0.004, 0.003), (49, "Other", 0.001, 0.001)):
        con.executemany(
            "insert into core.ff_industry_daily values (?, 49, ?, ?, ?, ?)",
            [(d, ind, name, w, r) for d in days for w, r in (("ew", ew), ("vw", vw))],
        )
    con.execute(
        "create table core.sic_industry (scheme INTEGER, industry_no INTEGER, industry VARCHAR, "
        "description VARCHAR, sic_from INTEGER, sic_to INTEGER)"
    )
    con.executemany("insert into core.sic_industry values (?, ?, ?, ?, ?, ?)",
                    [(49, 36, "Chips", "Chips", 3600, 3699),
                     (49, 49, "Other", "Almost Nothing", 4950, 4961)])  # fmt: skip
    con.execute(
        'create table evt.event (event_id VARCHAR, issuer_cik VARCHAR, "group" VARCHAR, '
        "signal_date DATE, t_session DATE, priced BOOLEAN, g7_sic VARCHAR, price_source VARCHAR)"
    )
    events = [("E1", "1", T, "3674"), ("E2", "2", T, "3674"), ("E3", "3", T, "3674"),
              ("E4", "4", T, "3674"), ("E5", "1", LATE_T, "3674"),
              ("E6", "1", T, "9995")]  # fmt: skip
    con.executemany("insert into evt.event values (?, ?, 'A', ?, ?, true, ?, 'yahoo')",
                    [(e, c, d, d, s) for e, c, d, s in events])  # fmt: skip
    con.execute("create table evt.event_cost (event_id VARCHAR, cost DOUBLE)")
    con.executemany("insert into evt.event_cost values (?, ?)",
                    [("E1", 0.02), ("E2", 0.01), ("E3", 0.03), ("E4", 0.02), ("E5", None),
                     ("E6", 0.02)])  # fmt: skip
    con.execute(
        "create table evt.event_member (event_id VARCHAR, accession VARCHAR, "
        "entity_id_at_t VARCHAR, entity_role_at_t VARCHAR, value_usd DOUBLE)"
    )
    con.execute("insert into evt.event_member values ('E1', 'a1', '1:9001', 'director', 1e5)")
    con.execute(
        "create table core.entity_member (issuer_cik VARCHAR, owner_cik VARCHAR, "
        "entity_id VARCHAR, valid_from DATE)"
    )
    con.executemany("insert into core.entity_member values ('1', ?, ?, '2019-01-01')",
                    [("9001", "1:9001"), ("9002", "1:9002")])  # fmt: skip
    con.execute(
        "create table core.priced_purchase (accession VARCHAR, issuer_cik VARCHAR, "
        "filing_date DATE, owner_ciks VARCHAR[], g8_status VARCHAR)"
    )
    con.executemany("insert into core.priced_purchase values (?, '1', ?, ?, 'checked')",
                    [("p_old", date(2020, 12, 1), ["9001"]),     # window ends before T
                     ("p_recent", date(2021, 5, 3), ["9001"]),   # window ends after T
                     ("p_other", date(2020, 12, 1), ["9002"])])  # another buyer  # fmt: skip
    con.execute(
        "create table core.delisting (issuer_cik VARCHAR, class VARCHAR, delisting_return DOUBLE)"
    )
    con.execute("insert into core.delisting values ('3', 'performance', -0.55)")
    report = labels.build(con, params)
    yield con, report, days, t, late
    con.close()


def label(con, event, horizon, measure):
    return con.execute(
        "select gross, cost, net, delisted, delisting_class, gross_dl_zero, gross_dl_wipeout, "
        "entry_at_close, stock_return, bench_return from lab.event_label "
        "where event_id = ? and horizon = ? and measure = ?",
        [event, horizon, measure],
    ).fetchone()


@pytest.mark.parametrize(("measure", "bench"), [("spy", 0.005), ("iwm", 0.002),
                                                 ("ind_ew", 0.004), ("ind_vw", 0.003)])  # fmt: skip
def test_bhar_against_each_benchmark(lab, measure, bench):
    con, *_ = lab
    for h in (5, 21, 63, 126, 252):
        gross = label(con, "E1", h, measure)[0]
        assert gross == pytest.approx(1.01**h - (1 + bench) ** h, rel=1e-9), (measure, h)


def test_net_is_gross_minus_cost_and_a_missing_cost_leaves_it_empty(lab):
    con, *_ = lab
    gross, cost, net, *_ = label(con, "E1", 63, "ind_ew")
    assert (cost, net) == (0.02, pytest.approx(gross - 0.02))
    assert label(con, "E5", 63, "ind_ew")[1:3] == (None, None)


def test_windows_end_by_the_development_end(lab):
    con, *_ = lab
    horizons = [h for (h,) in con.execute(
        "select distinct horizon from lab.event_label where event_id = 'E5' order by 1"
    ).fetchall()]  # fmt: skip
    assert horizons == [5, 21, 63]


def test_an_unmapped_sic_is_benchmarked_against_other(lab):
    con, *_ = lab
    assert label(con, "E6", 63, "ind_ew")[0] == pytest.approx(1.01**63 - 1.001**63, rel=1e-9)


def test_the_factor_model_car_leaves_out_the_intercept(lab):
    con, *_ = lab
    for h in (5, 21, 63, 126, 252):
        assert label(con, "E2", h, "ff6")[0] == pytest.approx(0.003 * h, abs=1e-9), h


def test_a_mid_window_delisting_takes_its_return_then_the_benchmark(lab):
    con, *_ = lab
    gross, _, _, delisted, cls, dl_zero, wipeout, _, stock, bench = label(con, "E3", 63, "ind_ew")
    rs, rb, rest = 1.01**30 - 1, 1.004**30 - 1, 1.004**33 - 1
    assert (delisted, cls) == (True, "performance")
    assert gross == pytest.approx((1 + rest) * ((1 + rs) * 0.45 - (1 + rb)), rel=1e-9)
    assert dl_zero == pytest.approx((1 + rest) * (rs - rb), rel=1e-9)
    assert wipeout == pytest.approx(-(1 + rest) * (1 + rb), rel=1e-9)
    assert stock - bench == pytest.approx(gross, rel=1e-9)
    assert label(con, "E3", 21, "ind_ew")[3] is False  # ends before the delisting


def test_an_unusable_entry_open_enters_at_the_close(lab):
    con, *_ = lab
    gross, *_, at_close, _, _ = label(con, "E4", 63, "spy")
    assert at_close is True
    assert gross == pytest.approx(1.01**62 - 1.005**62, rel=1e-9)
    assert label(con, "E4", 63, "ind_ew")[0] == pytest.approx(1.01**62 - 1.004**62, rel=1e-9)


def test_purchase_outcomes_use_only_windows_ended_before_t(lab):
    con, *_ = lab
    rows = con.execute(
        "select accession, gross, cost, net from lab.purchase_outcome order by 1"
    ).fetchall()
    assert [r[0] for r in rows] == ["p_old"]
    _, gross, cost, net = rows[0]
    assert gross == pytest.approx(1.01**63 - 1.004**63, rel=1e-9)
    assert cost is not None and net == pytest.approx(gross - cost)


def test_the_label_checks_pass(lab, params):
    con, *_ = lab
    assert labels.check_labels(con, params) == []
