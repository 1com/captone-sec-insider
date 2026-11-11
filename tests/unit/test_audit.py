"""The price coverage audit (027, research R12): one synthetic company per problem family, each
counted once; the examples are the same on every run."""

from datetime import date

import pandas as pd
import pytest

from sentinel import audit, db

DAYS = [d.date() for d in pd.bdate_range("2010-01-04", "2021-12-31")]


def _frame(con, table: str, rows: list[dict]) -> None:
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


def _days(start, end, step=1):
    return [d for d in DAYS[::step] if start <= d <= end]


def _prices(cik, ticker, days, close=20.0, source="yahoo"):
    return [{"cik": cik, "session": d, "source": source, "ticker": ticker, "close": close}
            for d in days]  # fmt: skip


@pytest.fixture
def world(tmp_data):
    con = db.connect(tmp_data)
    F4 = "form4"
    companies = [
        # cik, name, filer_type, tickers, first_form4, last_periodic, former names
        ("A", "Cut Corp", "us", ["CUT"], date(2010, 2, 1), date(2021, 11, 1), []),
        ("B", "Renamed Corp", "us", ["NEWB"], date(2010, 2, 1), date(2021, 11, 1), []),
        ("C", "Holey Corp", "us", ["HOLE"], date(2010, 2, 1), date(2021, 11, 1), []),
        ("D", "Gone Early Inc", "us", None, date(2010, 2, 1), date(2015, 6, 1), []),
        ("E", "Unpriced Corp", "us", ["UNP"], None, None, []),
        ("F", "Parent Corp", "us", ["SHR"], date(2010, 2, 1), date(2021, 11, 1), []),
        ("G", "Parent Operating LP", "us", None, date(2010, 2, 1), date(2012, 6, 1), []),
        ("H", "Merged Co", "us", ["MRG"], None, date(2021, 11, 1), []),
        ("I", "Never Priced Inc", "us", None, date(2012, 1, 3), date(2014, 1, 2), []),
    ]  # fmt: skip
    _frame(con, "ref.company", [
        {"cik": c, "name": n, "filer_type": ft, "tickers": t, "first_form4": f4,
         "last_periodic": lp, "is_fund": False, "is_blank_check": False, "sic": "1000"}
        for c, n, ft, t, f4, lp, _ in companies])  # fmt: skip
    con.execute(
        "alter table ref.company add column former_names "
        "STRUCT(name VARCHAR, valid_from VARCHAR, valid_to VARCHAR)[]"
    )
    con.execute(
        "update ref.company set former_names = [{'name': 'Shell Acquisition Corp', "
        "'valid_from': '2018-01-02', 'valid_to': '2019-06-28'}] where cik = 'H'"
    )
    reason = {"A": "yahoo_primary_late", "B": "yahoo_primary", "C": "yahoo_primary",
              "D": "tiingo_resolved", "E": "no_price", "F": "yahoo_primary",
              "G": "tiingo_resolved", "H": "yahoo_primary", "I": "no_ticker_found"}  # fmt: skip
    tick = {"A": "CUT", "B": "NEWB", "C": "HOLE", "D": "GONE", "E": None, "F": "SHR", "G": "SHR",
            "H": "MRG", "I": None}  # fmt: skip
    start = {"A": date(2016, 1, 4), "B": date(2016, 1, 4)}
    _frame(con, "core.price_choice", [
        {"cik": c, "source": "tiingo" if c in "DG" else "yahoo", "ticker": tick[c],
         "reason": reason[c], "trim_from": start.get(c, date(2010, 1, 1)), "trim_to": None,
         "listed": c not in "DGI"} for c in "ABCDEFGHI"])  # fmt: skip
    _frame(con, "core.price_candidate", [
        {"cik": "A", "source": "yahoo", "ticker": "CUT", "listing_start": date(2016, 1, 4),
         "n_sessions": 3000},
        {"cik": "E", "source": "yahoo", "ticker": "UNP-PA", "listing_start": None,
         "n_sessions": 500}])  # fmt: skip
    _frame(con, "ref.ticker_history", [
        {"cik": "B", "ticker": "OLDB", "valid_from": date(2010, 2, 1),
         "valid_to": date(2015, 12, 1), "evidence": F4},
        {"cik": "B", "ticker": "NEWB", "valid_from": date(2016, 1, 4),
         "valid_to": date(2021, 6, 1), "evidence": F4}])  # fmt: skip
    daily = (
        _prices("A", "CUT", _days(date(2016, 1, 4), DAYS[-1], 5))
        + _prices("B", "NEWB", _days(date(2016, 1, 4), DAYS[-1], 5))
        + _prices(
            "C", "HOLE", _days(DAYS[0], date(2011, 6, 30), 5) + _days(date(2015, 1, 2), DAYS[-1], 5)
        )
        + _prices("D", "GONE", _days(DAYS[0], date(2012, 12, 31), 5), source="tiingo")
        + _prices("F", "SHR", _days(DAYS[0], DAYS[-1], 5))
        + _prices("G", "SHR", _days(DAYS[0], date(2012, 12, 31), 5))
        + _prices("H", "MRG", _days(date(2018, 1, 2), DAYS[-1], 5), close=10.0)
    )
    _frame(con, "core.price_daily", daily)
    _frame(con, "stg_yahoo.price", [
        {"ticker": t, "session": d, "close": 20.0}
        for t, a, b in (("CUT", DAYS[0], DAYS[-1]), ("NEWB", date(2016, 1, 4), DAYS[-1]),
                        ("OLDB", DAYS[0], date(2015, 12, 31)))
        for d in _days(a, b, 20)])  # fmt: skip
    _frame(con, "stg_tiingo.price", [{"ticker": "GONE", "session": DAYS[0], "close": 1.0}])
    _frame(con, "stg_tiingo.listing", [
        {"ticker": "CUT", "exchange": "NYSE", "asset_type": "Stock", "currency": "USD",
         "start_date": date(2016, 1, 4), "end_date": date(2026, 10, 23)}])  # fmt: skip
    _frame(con, "stg_sec_filings.filing", [
        {"cik": c, "form": "10-K", "filing_date": date(y, 3, 1)}
        for c in "ABCFH" for y in (2012, 2020)])  # fmt: skip
    yield con
    con.close()


def test_each_family_counts_its_one_company(world):
    result = audit.run(world, date(2026, 11, 11))
    f = result["families"]
    cut = f["cut_with_stored_prices"]
    assert (cut["companies"], cut["by_cause"]) == (1, {"listing_start": 1})
    assert cut["company_months_2012_2022"] == 48  # Jan 2012 to Jan 2016
    assert f["ticker_change_not_joined"] == {
        "companies": 1, "old_prices_stored": 1,
        "examples": [{"cik": "B", "name": "Renamed Corp", "ticker": "OLDB",
                      "detail": "first price 2016-01-04"}]}  # fmt: skip
    assert (f["hole_over_a_year"]["listed"], f["hole_over_a_year"]["disappeared"]) == (1, 0)
    assert f["listed_without_price"]["us"] == 1
    assert f["listed_without_price"]["other_ticker_has_data"] == 1
    assert f["disappeared_prices_end_early"]["companies"] == 1
    assert f["disappeared_us_with_form4_without_prices"]["companies"] == 1
    assert f["ticker_days_claimed_twice"]["tickers"] == 1
    assert f["ticker_days_claimed_twice"]["rows"] > 0
    spac = f["blank_check_periods"]
    assert (spac["names"], spac["counted"], spac["left_out"]) == (1, 1, 0)
    assert spac["rows_in_counted_periods"] > 0
    assert result["layout"] == "one series per company"
    assert {(c["year"], c["status"]): (c["companies"], c["priced"]) for c in result["coverage"]}[
        (2012, "listed")
    ] == (5, 1)  # only F priced in 2012


def test_the_audit_fails_on_twice_given_days_and_failed_named_cases(world):
    result = audit.run(world, date(2026, 11, 11))
    issues = audit.problems(result)
    assert issues[0].endswith("ticker-days given to two or more companies")
    # none of the named companies is in this world: every case fails but the operating
    # partnership's, which holds (it has no DLR prices)
    assert len(issues) == 1 + len(audit.NAMED) - 1


def test_the_examples_are_the_same_on_every_run(world):
    first = audit.run(world, date(2026, 11, 11))
    second = audit.run(world, date(2026, 11, 11))
    assert first == second


def test_a_spac_name_counts_only_as_whole_words_and_when_short_or_near_10(world):
    world.execute("""
        update ref.company set former_names = [
            {'name': 'OYO GEOSPACE CORP', 'valid_from': '1997-11-18', 'valid_to': '2012-10-01'},
            {'name': 'Parkway Acquisition Corp.', 'valid_from': '2010-01-04',
             'valid_to': '2017-06-30'}] where cik = 'F'""")
    spac = audit.run(world, date(2026, 11, 11))["families"]["blank_check_periods"]
    assert spac["names"] == 2  # Shell Acquisition Corp (H) and Parkway; not "GEOSPACE"
    assert (spac["counted"], spac["left_out"]) == (1, 1)  # Parkway: 7.5 years, $20, not a SPAC
    assert spac["examples"][0]["detail"].startswith("7.5 years, 0% near $10")
