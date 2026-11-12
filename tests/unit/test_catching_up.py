"""The catching-up check of the dilution answer (V2-70): which filings count as an announced share
sale, and when a sale counts as announced for a row."""

from datetime import date

import duckdb
import pandas as pd

from sentinel.models import catching_up


def _filings(rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("create schema core")
    con.execute(
        "create table core.filing (cik varchar, form varchar, filing_date date, items varchar, "
        "known_at date)"
    )
    con.executemany("insert into core.filing values (?, ?, ?, ?, ?)", rows)
    return con


def test_sale_filings_keep_share_sales_only():
    con = _filings(
        [
            ("1", "FWP", date(2020, 3, 8), None, date(2020, 3, 9)),
            ("1", "424B5", date(2020, 3, 10), None, date(2020, 3, 11)),  # bonds: term sheet
            ("1", "424B5", date(2020, 5, 10), None, date(2020, 5, 11)),  # shares
            ("1", "424B3", date(2020, 6, 1), None, date(2020, 6, 2)),  # resale or merger
            ("1", "8-K", date(2020, 7, 1), "3.02,9.01", date(2020, 7, 2)),  # unregistered sale
            ("1", "8-K", date(2020, 8, 1), "2.02,9.01", date(2020, 8, 3)),  # results
            ("1", "S-3", date(2020, 9, 1), None, date(2020, 9, 2)),  # a shelf: no sale yet
        ]
    )
    out = catching_up.sale_filings(con, date(2020, 1, 1), date(2020, 12, 31))
    out = out.sort_values("filing_date")
    kept = [date(2020, 5, 10), date(2020, 6, 1), date(2020, 7, 1)]
    assert list(out["filing_date"].dt.date) == kept
    assert list(out["strict"]) == [True, False, True]
    assert (out["cik"] == 1).all()


def test_a_sale_counts_after_the_start_count_and_once_known():
    shares = pd.DataFrame(
        {
            "cik": ["7", "7", "8"],
            "period_end": pd.to_datetime(["2021-01-31", "2021-05-02", "2021-03-31"]),
            "value": [100.0, 100.0, 50.0],
            "filed": pd.to_datetime(["2021-02-05", "2021-05-06", "2021-04-05"]),
        }
    )
    rows = pd.DataFrame(
        {
            "cik": ["7", "7", "7", "8"],
            "as_of": pd.to_datetime(["2021-04-30", "2021-05-28", "2021-06-30", "2021-04-30"]),
            "dilution": [1.0, 1.0, 1.0, 0.0],
        }
    )
    sales = pd.DataFrame(
        {
            "cik": [7, 7, 7, 8, 8],
            "filing_date": pd.to_datetime(
                ["2021-04-27", "2021-05-04", "2021-06-03", "2021-03-30", "2021-04-30"]
            ),
            "known_at": pd.to_datetime(
                ["2021-04-28", "2021-05-05", "2021-06-04", "2021-03-31", "2021-05-03"]
            ),
            "strict": [True, False, True, True, True],
        }
    )
    out = catching_up.announced(catching_up.start_counts(rows, shares), sales)
    out = out.sort_values(["cik", "as_of"]).reset_index(drop=True)
    # company 7: the count of 2 May is the start once filed (6 May); the 4 May filing (a 424B3)
    # is dated after that count's own date, so it is not in it
    assert list(out["count_date"].dt.date) == [
        date(2021, 1, 31),
        date(2021, 5, 2),
        date(2021, 5, 2),
        date(2021, 3, 31),
    ]
    assert list(out["announced"]) == [True, True, True, False]
    assert list(out["announced_strict"]) == [True, False, True, False]
    # company 8: one sale is older than its start count, the other known only after the row
