"""The Kenneth French library files (T061). Fixtures are short excerpts of the public files
(`tests/fixtures/french/`), zipped here as the library serves them."""

import zipfile
from datetime import date
from pathlib import Path

import pytest

from sentinel import warehouse
from sentinel.core import reference
from sentinel.ingest import french

FIXTURES = Path(__file__).parents[1] / "fixtures" / "french"
FILES = {
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip": "five_factors_daily.csv",
    "F-F_Momentum_Factor_daily_CSV.zip": "momentum_daily.csv",
    "49_Industry_Portfolios_daily_CSV.zip": "industry49_daily.csv",
    "Siccodes49.zip": "siccodes49.txt",
    "ME_Breakpoints_CSV.zip": "me_breakpoints.csv",
}


@pytest.fixture
def built(tmp_data):
    tmp_data.french.mkdir(parents=True)
    for zip_name, fixture in FILES.items():
        with zipfile.ZipFile(tmp_data.french / zip_name, "w") as zf:
            zf.write(FIXTURES / fixture, arcname=fixture)
    con = warehouse.connect(tmp_data)
    report = reference.build_french(con, tmp_data)
    yield con, report
    con.close()


def test_sections_skip_free_text_and_keep_titles():
    text = (FIXTURES / "industry49_daily.csv").read_text()
    sections = french.sections(text)
    assert list(sections) == [
        "Average Value Weighted Returns -- Daily",
        "Average Equal Weighted Returns -- Daily",
    ]
    columns, rows = sections["Average Value Weighted Returns -- Daily"]
    assert columns == ["Agric", "Food", "Soda"]
    assert rows[0] == (date(1926, 7, 1), [0.56, -0.07, None])  # −99.99 is missing


def test_factors_are_decimal_returns_through_august_2026(built):
    con, report = built
    assert report.last_date == date(2026, 8, 31)
    got = dict(
        con.execute(
            "select factor, ret from core.ff_factor_daily where date = '2026-08-31'"
        ).fetchall()
    )
    assert got == pytest.approx(
        {
            "mkt_rf": -0.0033,
            "smb": -0.0029,
            "hml": -0.0039,
            "rmw": -0.0109,
            "cma": 0.0003,
            "rf": 0.0001,
        }
    )
    mom = con.execute("select ret from core.ff_factor_daily where factor = 'mom' order by date")
    assert [r[0] for r in mom.fetchall()] == pytest.approx([0.0055, -0.0051])


def test_industries_by_weighting_with_missing_values(built):
    con, report = built
    rows = con.execute(
        "select weighting, industry_no, industry, ret from core.ff_industry_daily "
        "where date = '1926-07-01' order by 1, 2"
    ).fetchall()
    assert rows[:2] == [("ew", 1, "Agric", pytest.approx(0.0063)),
                        ("ew", 2, "Food", pytest.approx(-0.0028))]  # fmt: skip
    assert rows[2] == ("ew", 3, "Soda", None)
    assert report.industry_rows == 12


def test_sic_ranges_and_breakpoints(built):
    con, report = built
    agric = con.execute(
        "select sic_from, sic_to from core.sic_industry where industry = 'Agric' order by 1"
    ).fetchall()
    assert agric[0] == (100, 199) and len(agric) == 5 and report.sic_ranges == 11
    p5 = con.execute(
        "select value_musd from core.me_breakpoint where month = '2026-08-01' and percentile = 5"
    ).fetchone()
    assert p5 == (256.10,) and report.breakpoints == 40


def test_files_not_stored_are_listed(built):
    _, report = built
    assert set(report.missing_files) == {
        "F-F_ST_Reversal_Factor_daily_CSV.zip",
        "12_Industry_Portfolios_daily_CSV.zip",
        "Siccodes12.zip",
    }
