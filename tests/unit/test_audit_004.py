"""Feature 004 audit sheets: golden set (T026), delistings (T041), market caps (T052)."""

import csv
from datetime import date

import pytest
from test_final_events import CAL, D1, T1, buy, cluster, path

from sentinel.core import audit
from sentinel.events import final

CEO = ("9100", ("Officer", "Chief Executive Officer"))


@pytest.fixture
def golden_warehouse(market_events, params):
    """30 A events at 30 issuers, 3 B1 and 2 B2 events, all priced."""
    filings, prices = [], {}
    for i in range(30):
        cik = str(1000 + i)
        filings += cluster(f"a{i}-", T1, cik=cik)
        prices[cik] = path()
    for i in range(3):
        cik = str(2000 + i)
        filings.append(buy(f"b{i}", T1, cik, CEO, value=120_000))
        prices[cik] = path()
    for i in range(2):
        cik = str(3000 + i)
        filings.append(buy(f"c{i}", T1, cik, D1, value=120_000))
        prices[cik] = path()
    con = market_events(*filings, prices=prices, sessions=CAL)
    final.detect(con, params)
    return con


def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_golden_sheet_layout_seed_and_strata(golden_warehouse, tmp_path):
    n = audit.make_golden_sheet(golden_warehouse, tmp_path)
    rows = read(tmp_path / "golden_set.csv")
    assert n == 30
    assert list(rows[0]) == audit.GOLDEN_COLUMNS
    assert {r["seed"] for r in rows} == {"20261025"}
    events = {r["event_id"]: r["group"] for r in rows}
    groups = [g for g in events.values()]
    # 10 per group where possible; B1 and B2 fall short, A makes up the rest
    assert (groups.count("A"), groups.count("B1"), groups.count("B2")) == (25, 3, 2)
    a_rows = [r for r in rows if r["group"] == "A"]
    assert len(a_rows) == 2 * 25  # one row per member purchase
    first = a_rows[0]
    assert first["edgar_link"].startswith("https://www.sec.gov/Archives/edgar/data/")
    assert first["owner_names"].startswith("Owner ") and first["prices"] == "10.0"
    assert all(r[c] == "" for r in rows for c in (*audit.GOLDEN_CHECKS, "notes"))
    assert sorted({int(r["n"]) for r in rows}) == list(range(1, 31))


def test_golden_sheet_is_not_replaced_without_force(golden_warehouse, tmp_path):
    audit.make_golden_sheet(golden_warehouse, tmp_path)
    with pytest.raises(audit.SheetsExist):
        audit.make_golden_sheet(golden_warehouse, tmp_path)
    assert audit.make_golden_sheet(golden_warehouse, tmp_path, force=True) == 30


def test_golden_summary_counts_events_by_their_first_row(golden_warehouse, tmp_path):
    audit.make_golden_sheet(golden_warehouse, tmp_path)
    path_ = tmp_path / "golden_set.csv"
    rows = read(path_)
    seen = []
    for r in rows:
        if r["event_id"] in seen:
            continue
        seen.append(r["event_id"])
        k = len(seen)
        if k <= 27:
            r.update(insiders_ok="yes", dates_ok="Yes", amounts_ok="yes")
        elif k == 28:
            r.update(insiders_ok="yes", dates_ok="no", amounts_ok="yes")
        elif k == 29:
            r.update(insiders_ok="unclear", dates_ok="yes", amounts_ok="yes")
    with path_.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=audit.GOLDEN_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    s = audit.summarize_golden(tmp_path)
    assert (s.events, s.all_yes, s.with_no, s.unclear, s.blank) == (30, 27, 1, 1, 1)
    assert s.agreement == pytest.approx(27 / 29)


def test_warm_up_events_are_not_sampled(market_events, params, tmp_path):
    cal = {"start": date(2011, 3, 1), "n": 200}
    from conftest import weekdays

    rows = [{"session": d, "close": 10.0, "volume": 50_000} for d in weekdays(**cal)]
    con = market_events(*cluster("w", date(2011, 9, 15)), prices={"100": rows}, sessions=cal)
    final.detect(con, params)
    assert audit.make_golden_sheet(con, tmp_path) == 0


# --- Delisting sheet (T041) ---------------------------------------------------------------------


@pytest.fixture
def delisted(tmp_data):
    from conftest import universe_tables

    from sentinel import warehouse
    from sentinel.core import delistings

    con = warehouse.connect(tmp_data)
    universe_tables(con)
    con.execute(f"create table core.delisting ({delistings.COLUMNS})")
    classes = ["acquired"] * 12 + ["performance"] * 4 + ["unknown"] * 15 + ["remap"] * 2
    for i, cls in enumerate(classes):
        cik = str(500 + i)
        con.execute(
            "insert into core.delisting values (?, '2019-06-03', 'tiingo', 'T', ?, null, "
            "'DEFM14A', '2019-01-02', '0000950103-19-000001', 'nasdaq', 0.0, -1.0, 0.0)",
            [cik, cls],
        )
        con.execute("insert into core.filing values (?, ?, '2018-01-02', 'T', ?)",
                    [f"f{i}", cik, f"Company {i}"])  # fmt: skip
    yield con
    con.close()


def test_delisting_sheet_layout_strata_and_no_prices(delisted, tmp_path):
    n = audit.make_delisting_sheet(delisted, tmp_path)
    rows = read(tmp_path / "delisting_audit.csv")
    assert n == 30 and list(rows[0]) == audit.DELISTING_COLUMNS
    classes = [r["class"] for r in rows]
    assert classes.count("performance") == 4  # all of them
    assert classes.count("acquired") >= 10 and classes.count("unknown") >= 10
    assert {r["seed"] for r in rows} == {"20261024"}
    assert rows[0]["filings_link"].startswith("https://www.sec.gov/cgi-bin/browse-edgar")
    assert rows[0]["evidence_link"].endswith("/000095010319000001/")
    assert not any("close" in c or "price" in c for c in rows[0])
    with pytest.raises(audit.SheetsExist):
        audit.make_delisting_sheet(delisted, tmp_path)


def test_delisting_summary_by_class(delisted, tmp_path):
    audit.make_delisting_sheet(delisted, tmp_path)
    path_ = tmp_path / "delisting_audit.csv"
    rows = read(path_)
    for i, r in enumerate(rows):
        r["verdict"] = "agree" if i % 10 else "disagree"
    with path_.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=audit.DELISTING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    s = audit.summarize_delistings(tmp_path)
    assert s["all"]["agree"] == 27 and s["all"]["disagree"] == 3 and s["all"]["blank"] == 0
    assert sum(v["agree"] + v["disagree"] for k, v in s.items() if k != "all") == 30


# --- Market-cap sheet (T052) --------------------------------------------------------------------


def test_market_cap_sheet_compares_with_yahoo_and_stores_it_once(tmp_data, params):
    from conftest import market_prices, market_sessions

    from sentinel import warehouse
    from sentinel.core import company
    from sentinel.ingest import manifest

    con = warehouse.connect(tmp_data)
    days = market_sessions(con, start=date(2026, 9, 1), n=20)
    market_prices(con, "100", [{"session": d, "close": 20.0} for d in days], ticker="ABC")
    con.execute(f"create table core.xbrl_fact ({company.FACT_COLUMNS})")
    con.execute(
        "insert into core.xbrl_fact values ('100', 'shares_outstanding', 'shares', null, "
        "'2026-07-31', 5e6, '2026-08-05', 'x', '10-Q', 'Q2', 'main:x')"
    )
    params["ops"]["market_cap_examples"] = ["ABC"]
    calls = []

    def fetch(t):
        calls.append(t)
        return 102_000_000.0

    rows = audit.make_market_cap_sheet(con, tmp_data, params, fetch=fetch)
    assert rows[0][5:7] == [100_000_000.0, 102_000_000.0] and rows[0][-1] is True
    sheet = read(tmp_data.audits_004 / "market_caps.csv")
    assert sheet[0]["market_cap_pipeline"] == "100000000" and sheet[0]["within_5pct"] == "True"
    assert manifest.find_original(tmp_data.manifest, "yahoo", "market_cap/ABC") is not None
    audit.make_market_cap_sheet(con, tmp_data, params, fetch=fetch)
    assert calls == ["ABC"]  # stored once, offline afterwards
    con.close()
