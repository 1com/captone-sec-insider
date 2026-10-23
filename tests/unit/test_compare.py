"""Comparison with feature 001's provisional events (FR-016, SC-005; research.md R8)."""

import ast
import datetime as dt
import inspect

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import line, owner, sub

from sentinel.events import compare

D, T10, CEO = ("Director", ""), ("TenPercentOwner", ""), ("Officer", "CFO")


def buy(acc, date, cik, ocik, role, value, price="50"):
    rel, title = role
    return (
        sub(acc, date=date, cik=cik),
        owner(acc, ocik=ocik, rel=rel, title=title),
        line(acc, "1", tdate=date, shares=str(value / float(price)), price=price),
    )


@pytest.fixture
def con(archives, pipeline):
    filings = [
        buy("a1", "01-MAR-2019", "100", "9001", D, 60_000),  # A in every variant
        buy("a2", "05-MAR-2019", "100", "9002", T10, 60_000),
        buy("t1", "01-MAR-2018", "300", "9003", T10, 60_000),  # A only without the O/D rule
        buy("t2", "05-MAR-2018", "300", "9004", T10, 60_000),
        buy("g1", "01-MAR-2017", "400", "9005", D, 90_000),  # A only at the pilot's G6 ($10k)
        buy("g2", "05-MAR-2017", "400", "9006", T10, 15_000),
        buy("b1", "01-MAR-2019", "200", "9007", CEO, 150_000),  # B1
        buy("b2", "01-MAR-2019", "500", "9008", D, 150_000),  # B2
        buy("p1", "01-MAR-2016", "600", "9009", CEO, 150_000, price="1.5"),  # B1 under $2
    ]
    archives(
        {
            "2019q1": {
                "SUBMISSION": [f[0] for f in filings],
                "REPORTINGOWNER": [f[1] for f in filings],
                "NONDERIV_TRANS": [f[2] for f in filings],
            }
        }
    )
    return pipeline(until="prelim")


@pytest.fixture
def provisional(tmp_path):
    """Feature 001's schema: A in 2017, 2018 and 2019; two B1 in 2019."""
    rows = [("400", "A", 2017), ("300", "A", 2018), ("100", "A", 2019), ("200", "B1", 2019)]
    rows.append(("201", "B1", 2019))
    path = tmp_path / "events_PROVISIONAL.parquet"
    pq.write_table(
        pa.table(
            {
                "status": ["PROVISIONAL"] * len(rows),
                "issuer_cik": [r[0] for r in rows],
                "group": [r[1] for r in rows],
                "signal_date": [dt.date(r[2], 3, 5) for r in rows],
                "n_buyers": pa.array([2] * len(rows), pa.int64()),
                "total_value_usd": [120_000.0] * len(rows),
                "member_accessions": [["x"]] * len(rows),
                "in_labelled_window": [r[2] >= 2012 for r in rows],
            }
        ),
        path,
    )
    return path


def test_counts_per_group_year_and_variant(con, provisional, params):
    table = compare.tabulate(con, provisional, params)
    a = {r.year: (r.provisional, r.variants) for r in table["A"]}
    assert a == {
        2017: (1, (0, 0, 0, 1)),
        2018: (1, (0, 0, 1, 1)),
        2019: (1, (1, 1, 1, 1)),
    }
    b1 = {r.year: (r.provisional, r.variants) for r in table["B1"]}
    assert b1 == {2016: (0, (1, 0, 0, 0)), 2019: (2, (1, 1, 1, 1))}
    b2 = {r.year: (r.provisional, r.variants) for r in table["B2"]}
    assert b2 == {2019: (None, (1, 1, 1, 1))}


def test_years_off_by_more_than_15_percent_are_flagged(con, provisional, params):
    table = compare.tabulate(con, provisional, params)
    flagged = {(g, r.year) for g, rows in table.items() for r in rows if r.flagged}
    assert flagged == {("B1", 2019)}
    row = next(r for r in table["B1"] if r.year == 2019)
    assert row.gap == pytest.approx(-0.5)


def test_report_is_markdown_with_a_table_per_group(con, provisional, params):
    report = compare.compare(con, provisional, params)
    for group in ("A", "B1", "B2"):
        assert f"\n## {group}" in report
    assert "| 2019 | 2 | 1 | 1 | 1 | 1 | −50.0% | ⚠ |" in report
    assert "| 2019 | — | 1 | 1 | 1 | 1 | — |  |" in report
    assert "\n## Explanations" in report


def test_hand_written_explanations_survive_a_rerun(con, provisional, params, tmp_path):
    out = tmp_path / "comparison.md"
    compare.write_report(out, compare.compare(con, provisional, params))
    out.write_text(out.read_text() + "- **B1 2019**: one event was a typo.\n")
    compare.write_report(out, compare.compare(con, provisional, params))
    assert out.read_text().endswith("- **B1 2019**: one event was a typo.\n")


def test_the_module_does_not_import_the_provisional_package():
    tree = ast.parse(inspect.getsource(compare))
    imported = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    ]
    assert not [m for m in imported if m and m.startswith("sentinel.provisional")]
