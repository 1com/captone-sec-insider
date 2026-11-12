"""The stock research app (026) on a small test copy of the serving tables: search, the company
page's data, split-adjusted prices, insider totals, filings explained, no volatility or results-day
forecast, and an error (never invented data) when the serving copy is missing."""

import dataclasses

import duckdb
import pytest
from fastapi.testclient import TestClient

from sentinel import config
from sentinel.web import main


def _serving(path):
    con = duckdb.connect(str(path))
    con.execute("create schema app")
    con.execute(
        "create table app.freshness as select * from (values ('prices', DATE '2026-11-09'), "
        "('filings', DATE '2026-11-09'), ('insider_filings', DATE '2026-11-06'), "
        "('short_volume', DATE '2026-11-09'), ('financial_values', DATE '2026-11-09')) "
        "t(dataset, latest_date)"
    )
    con.execute(
        """create table app.stock as select * from (values
        ('1744489', 'DIS', 'Walt Disney Co', 'NYSE', 'Media', '4841', 'Services', 'operating',
         'full', false, false, null, true, true, 'yahoo', DATE '2019-03-11', DATE '2026-11-09',
         null, null, null, true, null, null, 'Walt Acquisition Corp', DATE '2019-03-08'),
        ('1001039', 'DIS', 'TWDC Enterprises 18 Corp.', null, 'Media', '4841', 'Services',
         'operating', 'full', false, false, null, true, false, 'tiingo', DATE '2010-01-04',
         DATE '2019-06-19', null, null, null, true, null, null, null, null))
        t(cik, ticker, name, exchange, sector, sic, sic_description, filer_type, coverage,
          is_fund, is_blank_check, former_names, has_prices, listed, price_source, first_session,
          last_session, first_periodic, last_periodic, last_filing, is_form4_issuer, first_form4,
          last_form4, listed_via, listed_via_date)"""
    )
    con.execute(
        "alter table app.stock alter former_names type "
        "struct(name varchar, valid_from varchar, valid_to varchar)[]"
    )
    con.execute(
        "create table app.company_card as select '1744489' as cik, DATE '2026-11-09' as as_of, "
        "false as foreign_filer, false as excluded, 'full' as coverage, true as eligible_dilution, "
        "2.0e11 as market_cap, 1.8e9 as shares_outstanding, 1.5e9 as addv20, "
        "0.01 as share_growth_12m, null::double as cash_runway_years, false as loss_making, "
        "DATE '2027-02-04' as next_results_estimate, 0.45 as short_ratio_1m, "
        "0.44 as short_ratio_3m, 0.01 as short_ratio_chg"
    )
    con.execute(
        """create table app.price_daily as select * from (values
        ('1744489', DATE '2026-11-04', 'yahoo', 200.0, 202.0, 198.0, 200.0, 1000.0, 2.0, false),
        ('1744489', DATE '2026-11-05', 'yahoo', 100.0, 101.0, 99.0, 101.0, 3000.0, 1.0, false),
        ('1744489', DATE '2026-11-06', 'yahoo', 999.0, 999.0, 999.0, 999.0, 10.0, 1.0, true),
        ('1744489', DATE '2026-11-09', 'yahoo', 101.0, 103.0, 100.0, 102.0, 2000.0, 1.0, false))
        t(cik, session, source, open, high, low, close, volume, cum_split_after, glitch)"""
    )
    for col in ("open", "high", "low", "close", "volume", "cum_split_after"):
        con.execute(f"alter table app.price_daily alter {col} type double")
    con.execute(
        """create table app.insider_activity as select * from (values
        ('1744489', 'a1', 'buy', DATE '2026-10-02', DATE '2026-10-01', DATE '2026-10-01',
         ['Jane Doe'], 'e1', 'director', 50000.0, 500.0, 100.0, false, false, 'https://x/a1'),
        ('1744489', 'a2', 'sell', DATE '2026-10-20', DATE '2026-10-17', DATE '2026-10-17',
         ['John Roe'], 'e2', 'ceo_cfo', 200000.0, 2000.0, 100.0, true, false, 'https://x/a2'),
        ('1744489', 'a3', 'sell', DATE '2026-11-03', DATE '2026-11-02', DATE '2026-11-02',
         ['John Roe'], 'e2', 'ceo_cfo', 30000.0, 300.0, 100.0, false, false, 'https://x/a3'))
        t(cik, accession, side, filing_date, min_trade_date, max_trade_date, owner_names,
          entity_id, entity_role, value_usd, shares, avg_price, planned, offering, url)"""
    )
    con.execute(
        "create table app.insider_feed (cik varchar, cluster_date date, kind varchar, "
        "n_entities integer, total_value_usd double, top_role varchar)"
    )
    con.execute(
        """create table app.filings as select * from (values
        ('1744489', 'f1', '10-Q', DATE '2026-11-05', DATE '2026-09-30', null, 'https://x/f1'),
        ('1744489', 'f2', '8-K', DATE '2026-11-06', DATE '2026-11-06', '2.02,9.01', 'https://x/f2'),
        ('1744489', 'f3', 'S-3', DATE '2026-11-07', null, null, 'https://x/f3'),
        ('1744489', 'f4', '4', DATE '2026-11-03', null, null, 'https://x/f4'))
        t(cik, accession, form, filing_date, report_date, items, url)"""
    )
    con.execute(
        """create table app.financials as select * from (values
        ('1744489', 'shares_outstanding', DATE '2026-09-30', 1.8e9, DATE '2026-11-05'),
        ('1744489', 'shares_outstanding', DATE '2026-11-04', 0.9e9, DATE '2026-11-05'))
        t(cik, item, period_end, value, filed)"""
    )
    con.close()


class _NoForecasts:
    """The model is not loaded in unit tests: one fixed forecast, no MLflow."""

    info, card, as_of, by_cik = {"model": "test"}, {}, "2026-11-09", {}

    def refresh(self, con):
        pass

    def for_company(self, cik, card, listed, facts=None):
        return {"available": True, "chance": 0.05, "band": 2, "band_name": "2 · Low risk",
                "as_of": "2026-11-09", "factors": []}  # fmt: skip

    def top(self, n=15):
        return [{"cik": "1744489", "chance": 0.05, "band": 2}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "serving.duckdb"
    _serving(path)
    monkeypatch.setattr(main, "PATHS", dataclasses.replace(config.paths(), serving_db=path))
    monkeypatch.setattr(main, "FORECASTS", _NoForecasts())
    monkeypatch.setattr(main, "PASSWORD", None)  # the real .env may set one
    return TestClient(main.app)


def test_a_reused_ticker_lists_each_company_the_listed_one_first(client):
    hits = client.get("/api/search?q=dis").json()
    assert [h["name"] for h in hits] == ["Walt Disney Co", "TWDC Enterprises 18 Corp."]
    assert client.get("/api/search?q=walt").json()[0]["cik"] == "1744489"


def test_the_company_page_has_facts_and_the_dilution_forecast_only(client):
    r = client.get("/api/company/1744489")
    assert r.status_code == 200
    c = r.json()
    assert c["facts"]["name"] == "Walt Disney Co" and c["dilution"]["band"] == 2
    assert c["facts"]["listed_via"] == "Walt Acquisition Corp"  # the SPAC line (027, V2-66)
    assert c["quote"]["close"] == 102.0 and c["quote"]["previous"] == 101.0
    assert c["freshness"]["insider_filings"] == "2026-11-06"
    for word in ("vol_forecast", "vol_low_80", "p_move", "move_band", "results_move"):
        assert word not in r.text  # no volatility or results-day forecast (V2-61)
    # both counts come before the 2-for-1 split (the first one before the first price day too):
    # each is doubled into today's shares
    assert [s["adjusted"] for s in c["shares"]] == [3.6e9, 1.8e9]
    assert client.get("/api/company/999").status_code == 404


def test_prices_are_split_adjusted_and_bad_days_left_out(client):
    p = client.get("/api/prices/1744489").json()
    assert p["t"] == ["2026-11-04", "2026-11-05", "2026-11-09"]  # the glitch day is left out
    assert p["c"][0] == 100.0 and p["v"][0] == 2000.0  # 200 / 2 and 1000 x 2: a 2-for-1 split
    assert [o["form"] for o in p["offerings"]] == ["S-3"]


def test_insider_totals_per_month_with_and_without_planned_sales(client):
    ins = client.get("/api/insiders/1744489").json()
    months = {m["month"]: m for m in ins["monthly"]}
    assert months["2026-10-01"]["bought"] == 50000.0 and months["2026-10-01"]["sold"] == 200000.0
    assert months["2026-10-01"]["sold_unplanned"] is None
    assert months["2026-11-01"]["sold_unplanned"] == 30000.0
    assert [t["trade_date"] for t in ins["trades"]] == ["2026-11-02", "2026-10-17", "2026-10-01"]


def test_filings_are_explained_and_counted_by_kind(client):
    f = client.get("/api/filings/1744489").json()
    assert f["total"] == 4 and sum(f["counts"].values()) == 4
    by_form = {r["form"]: r for r in f["filings"]}
    assert [i["item"] for i in by_form["8-K"]["item_list"]] == ["2.02", "9.01"]
    assert by_form["S-3"]["about"]["dilution_signal"] is True
    assert all(r["about"]["name"] for r in f["filings"])
    only = client.get("/api/filings/1744489?kind=offerings").json()
    assert [r["form"] for r in only["filings"]] == ["S-3"]


def test_a_missing_serving_copy_gives_an_error_never_data(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main, "PATHS", dataclasses.replace(config.paths(), serving_db=tmp_path / "missing.duckdb")
    )
    monkeypatch.setattr(main, "PASSWORD", None)
    c = TestClient(main.app)
    r = c.get("/api/search?q=dis")
    assert r.status_code == 503 and "does not exist" in r.json()["error"]
    page = c.get("/")
    assert (
        page.status_code == 200
        and "does not exist" in page.text
        and "Data current to" not in page.text
    )


def test_with_a_password_every_request_needs_it(client, monkeypatch):
    import base64

    monkeypatch.setattr(main, "PASSWORD", "s3cret")
    assert client.get("/").status_code == 401
    assert client.get("/api/search?q=dis").status_code == 401
    assert client.get("/static/app.js").status_code == 401
    good = "Basic " + base64.b64encode(b"anyone:s3cret").decode()
    bad = "Basic " + base64.b64encode(b"anyone:wrong").decode()
    assert client.get("/api/search?q=dis", headers={"Authorization": bad}).status_code == 401
    assert client.get("/api/search?q=dis", headers={"Authorization": good}).status_code == 200
    assert client.get("/", headers={"Authorization": good}).status_code == 200


def test_the_page_shows_the_daily_updates_forecasts_of_the_approved_model_only(tmp_path):
    """T018, V2-72: the app reads the stored forecasts (never computes one) and shows only the
    approved model's; a forecast older than the company's data says so; a company in the question
    without one is told it has none yet."""
    import json

    from sentinel.web import forecast

    path = tmp_path / "serving.duckdb"
    extra = json.dumps({"band_name": "4 · High risk", "factors": [
        ["n_offering_12m", 2.0, 0.8], ["log_market_cap", None, -0.2]]})  # fmt: skip
    with duckdb.connect(str(path)) as con:
        con.execute("create schema app")
        con.execute("create table app.company_card as select * from (values "
                    "('1', DATE '2026-11-10'), ('2', DATE '2026-11-10'), ('3', DATE '2026-11-10'), "
                    "('4', DATE '2026-10-01')) t(cik, as_of)")  # fmt: skip
        con.execute("create table app.daily_score as select * from (values "
                    "('1', DATE '2026-11-10', 'dilution', 'lightgbm-ok', 0.31, 4, 'full', $e, "
                    " TIMESTAMP '2026-11-10 10:30'), "
                    "('2', DATE '2026-11-09', 'dilution', 'lightgbm-ok', 0.05, 2, 'full', $e, "
                    " TIMESTAMP '2026-11-09 10:30'), "
                    "('3', DATE '2026-11-10', 'dilution', 'lightgbm_v1', 0.9, 5, 'full', $e, "
                    " TIMESTAMP '2026-11-10 10:31')) t(cik, as_of, question, model_version, "
                    "forecast_val, band, coverage, extra_json, scored_at)",
                    {"e": extra})  # fmt: skip
    fc = forecast.Forecasts(dataclasses.replace(config.paths(), serving_db=path))
    fc._load = lambda: setattr(fc, "version", "lightgbm-ok")  # the approved model, no MLflow
    with duckdb.connect(str(path), read_only=True) as con:
        fc.refresh(con)
    assert set(fc.by_cik) == {"1", "2"} and fc.as_of == "2026-11-10"
    assert fc.current == {"1", "2", "3"}  # 4: no price in the last week
    one = fc.for_company("1", {"as_of": "2026-11-10"}, True, {})
    assert {k: one[k] for k in ("available", "chance", "band", "band_name", "as_of")} == {
        "available": True, "chance": 0.31, "band": 4, "band_name": "4 · High risk",
        "as_of": "2026-11-10"}  # fmt: skip
    assert "stale" not in one and "extra" not in one
    assert one["factors"] == [
        {"feature": "n_offering_12m", "label": "Share offering filings, 12 months",
         "kind": "count", "value": 2.0, "effect": 0.8},
        {"feature": "log_market_cap", "label": "Market value of the company",
         "kind": "logmoney", "value": None, "effect": -0.2}]  # fmt: skip
    assert fc.for_company("2", {"as_of": "2026-11-10"}, True, {})["stale"] is True
    three = fc.for_company("3", {"as_of": "2026-11-10", "eligible_dilution": True}, True,
                           {"has_prices": True})  # fmt: skip
    assert not three["available"] and three["reason"].startswith("No forecast yet")
    assert fc.top(1) == [{"cik": "1", "chance": 0.31, "band": 4}]
