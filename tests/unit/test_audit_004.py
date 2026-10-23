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
