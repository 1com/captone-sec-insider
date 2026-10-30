"""The validation round's checks (022) on small synthetic tables: each finds the planted case."""

from datetime import date, timedelta

import pandas as pd

from sentinel import db, validation


def _frame(con, table: str, rows: list[dict]) -> None:
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


def test_first_counts_far_from_the_next_ones_are_found(tmp_data):
    con = db.connect(tmp_data)
    d = [date(2020, 1, 1) + timedelta(days=90 * i) for i in range(4)]
    rows = [{"cik": c, "as_of": a, "shares": s, "filed": a, "known_at": a, "source": "cover_page"}
            for c, counts in (("1", [1.0, 5e8, 5e8, 5e8]), ("2", [4e8, 5e8, 5e8, 5e8]))
            for a, s in zip(d, counts, strict=True)]  # fmt: skip
    _frame(con, "core.shares_outstanding", rows)
    got = validation.first_count_outliers(con)
    assert list(got["cik"]) == ["1"] and got["first_count"].iloc[0] == 1.0


def test_crowded_release_years_and_far_tiingo_prices_are_found(tmp_data):
    con = db.connect(tmp_data)
    days = [date(2015, m, 1) for m in (1, 2, 4, 7, 10)] + [date(2016, m, 1) for m in (1, 4, 7)]
    _frame(con, "core.results_release", [{"cik": "1", "filing_date": d, "confirmed": d}
                                         for d in days])  # fmt: skip
    got = validation.crowded_releases(con)
    assert (got["year"].tolist(), got["releases"].tolist()) == ([2015], [5])
    sessions = [date(2024, 1, 1) + timedelta(days=i) for i in range(30)]
    _frame(con, "core.price_daily", [
        {"cik": c, "session": s, "close": (0.000001 if c == "9" and i == 29 else 1.0),
         "source": "tiingo"} for c in ("8", "9") for i, s in enumerate(sessions)])  # fmt: skip
    jumps = validation.tiingo_price_jumps(con)
    assert jumps["cik"].tolist() == ["9"]


def test_filing_urls_point_at_the_complete_submission():
    assert validation.filing_url("0001061630", "0001193125-13-201909") == (
        "https://www.sec.gov/Archives/edgar/data/1061630/000119312513201909/"
        "0001193125-13-201909.txt"
    )
