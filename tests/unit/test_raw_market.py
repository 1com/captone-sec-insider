"""FRED, Cboe and FINRA downloads (respx; no network)."""

import re
from datetime import date

import httpx
import pytest
import respx

from sentinel.raw import market
from sentinel.raw.http import RateLimiter
from sentinel.raw.manifest import Manifest

QUIET = {"echo": lambda s: None}


@pytest.fixture
def env(tmp_data, fake_env, monkeypatch):
    fake_env.write_text(fake_env.read_text() + "FRED_API_KEY=fred-secret-456\n")

    def no_wait(rate, ceiling):
        return RateLimiter(rate, ceiling, sleep=lambda s: None)

    monkeypatch.setattr(market, "RateLimiter", no_wait)
    return tmp_data


@respx.mock
def test_each_fred_series_is_stored_once_a_day_without_the_key_in_its_record(env):
    route = respx.get(market.FRED_BASE).mock(return_value=httpx.Response(200, json={
        "observations": [{"date": "2026-10-28", "value": "4.1"},
                         {"date": "2026-10-29", "value": "."}]}))  # fmt: skip
    report = market.fetch_fred(env, date(2026, 10, 30), **QUIET)
    assert route.call_count == 7 and report.files_stored == 7  # 5 market, 2 first-release
    assert all(c.request.url.params["api_key"] == "fred-secret-456" for c in route.calls)
    urls = [e.url for e in Manifest(env.manifest).originals("fred")]
    assert urls and not any("fred-secret" in u or "api_key" in u for u in urls)
    assert report.latest_date == date(2026, 10, 28)  # "." is no value
    assert market.fetch_fred(env, date(2026, 10, 30), **QUIET).requests == 0


@respx.mock
def test_a_fred_failure_is_reported_without_the_url(env):
    respx.get(market.FRED_BASE).mock(return_value=httpx.Response(500))
    report = market.fetch_fred(env, date(2026, 10, 30), **QUIET)
    assert report.status == "failed" and not any("fred-secret" in e for e in report.errors)


@respx.mock
def test_the_vix_history_is_stored_as_a_dated_copy(env):
    respx.get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv").mock(
        return_value=httpx.Response(200, text="DATE,OPEN,HIGH,LOW,CLOSE\n10/29/2026,1,1,1,16.5\n")
    )
    report = market.fetch_cboe(env, date(2026, 10, 30), **QUIET)
    assert report.files_stored == 1 and report.latest_date == date(2026, 10, 29)
    assert (env.raw / "cboe/VIX_History-2026-10-30.csv.gz").exists()


@respx.mock
def test_finra_days_are_asked_once_and_an_old_missing_file_is_a_holiday(env):
    def answer(request):
        day = re.search(r"shvol(\d{8})", str(request.url)).group(1)
        if day == "20261028":
            return httpx.Response(200, text="Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume")
        return httpx.Response(403)  # FINRA: a file that does not exist (yet)

    route = respx.get(re.compile(r"https://cdn\.finra\.org/.*")).mock(side_effect=answer)
    report = market.fetch_finra(env, date(2026, 10, 30), from_day=date(2026, 10, 19),
                                to_day=date(2026, 10, 30), **QUIET)  # fmt: skip
    assert report.files_stored == 5  # five facilities on the 28th
    absent = (env.raw / "finra/short_volume/absent.csv").read_text()
    assert "FNSQ/20261019" in absent  # 11 days old: a day without a file
    assert "FNSQ/20261029" not in absent  # yesterday: not published yet, asked again
    asked = route.call_count
    market.fetch_finra(env, date(2026, 10, 30), from_day=date(2026, 10, 19),
                       to_day=date(2026, 10, 30), **QUIET)  # fmt: skip
    assert route.call_count - asked == 4 * 5  # only the recent days (26th, 27th, 29th, 30th)
