"""Named real cases on the built data/sentinel.duckdb (skipped without it): known events and values
from the public record, checked end to end through the layers."""

from datetime import date

import duckdb
import pytest

from sentinel.config import paths
from sentinel.raw import yahoo
from sentinel.raw.manifest import Manifest

pytestmark = pytest.mark.slow

APPLE, META, TESLA, JPM, TSMC = "320193", "1326801", "1318605", "19617", "1046179"
SIXTH_STREET, BED_BATH, ADAMS_FUND = "1508655", "886158", "2230"
HITACHI, DEUTSCHE_TELEKOM, STANDARD_LIFE, NGK = "47710", "946770", "1370418", "1442655"


@pytest.fixture(scope="module")
def con():
    with duckdb.connect(str(paths().build_db), read_only=True) as con:
        yield con


def _one(con, sql: str, *args):
    return con.execute(sql, list(args)).fetchone()


def test_jamie_dimons_february_2016_purchase(con):
    """Jamie Dimon bought 500,000 JPMorgan shares at about $53 on 11 February 2016."""
    row = _one(con, "select known_at, entity_role, shares, value_usd, clean, planned, shares_after "
                    "from core.insider_activity where issuer_cik = ? and side = 'buy' "
                    "and filing_date = '2016-02-11'", JPM)  # fmt: skip
    assert row[:3] == (date(2016, 2, 12), "ceo_cfo", 500_000.0)
    assert row[3] == pytest.approx(26.59e6, rel=0.01) and row[4] and not row[5]
    assert row[6] == pytest.approx(6.75e6, rel=0.01)
    assert _one(con, "select grp, starts_event from core.insider_cluster where issuer_cik = ? "
                     "and cluster_date = '2016-02-11'", JPM) == ("B1", True)  # fmt: skip


def test_teslas_2022_results_releases(con):
    """Tesla released its results on 26 January, 20 April, 20 July and 19 October 2022."""
    rows = con.execute(
        "select filing_date from core.results_release where cik = ? "
        "and filing_date between '2022-01-01' and '2022-12-31' order by 1",
        [TESLA],
    ).fetchall()
    got = [d for (d,) in rows]
    assert got == [date(2022, 1, 26), date(2022, 4, 20), date(2022, 7, 20), date(2022, 10, 19)]


def test_apples_market_value_on_its_2020_split_day(con):
    """Apple split 4-for-1 on 31 August 2020 and closed at $129.04: about $2.2 trillion. The latest
    cover-page count (July 2020) was of pre-split shares."""
    close, cap = _one(con, "select close, market_cap from feature.snapshot where cik = ? "
                           "and as_of = '2020-08-31'", APPLE)  # fmt: skip
    assert close == pytest.approx(129.04, rel=0.01)
    assert 2.0e12 < cap < 2.4e12


def test_metas_market_value_counts_both_share_classes(con):
    """Meta closed 2021 at $336.35 with about 2.8 billion class A and B shares: about $940
    billion."""
    cap = _one(con, "select market_cap from feature.snapshot where cik = ? "
                    "and as_of = '2021-12-31'", META)[0]  # fmt: skip
    assert 0.85e12 < cap < 1.05e12


def test_tsmc_is_a_foreign_filer_without_a_market_value(con):
    """TSMC files 20-F; its price is the ADR's, so market value is missing, not wrong."""
    row = _one(con, "select coverage, foreign_filer, log_market_cap, buy_value_12m, vol_63 "
                    "from feature.snapshot where cik = ? and latest", TSMC)  # fmt: skip
    assert row[:4] == ("foreign", True, None, None) and row[4] > 0


def test_a_bdc_is_a_stock_and_a_closed_end_fund_is_not_covered(con):
    """Sixth Street Specialty Lending files N-2 like a fund but 10-Ks like a company (v5), so it
    is priced; Adams Diversified Equity Fund files N-CSR, so it is a fund and not covered (spec)."""
    row = _one(con, "select c.is_fund, s.coverage from ref.company c "
                    "left join ref.security s on s.security_id = c.cik where c.cik = ?",
               SIXTH_STREET)  # fmt: skip
    assert row == (False, "full")
    row = _one(con, "select c.is_fund, s.security_id from ref.company c "
                    "left join ref.security s on s.security_id = c.cik where c.cik = ?",
               ADAMS_FUND)  # fmt: skip
    assert row == (True, None)


def test_a_disappeared_company_is_priced_from_tiingo(con):
    """Bed Bath & Beyond went bankrupt in April 2023 and stopped trading that year."""
    row = _one(con, "select source, listed, last_session from ref.security where security_id = ?",
               BED_BATH)  # fmt: skip
    assert row[:2] == ("tiingo", False) and date(2023, 4, 1) <= row[2] <= date(2023, 12, 31)


# --- Feature 001: the daily refresh ------------------------------------------------------------


def test_the_calendar_and_prices_reach_the_last_session_of_the_refresh(con):
    """The calendar no longer stops on 23 October 2026 (an old SPY file): it reaches the last
    session the refresh fetched, and Apple has a close that day."""
    (last,) = _one(con, "select max(session) from ref.calendar")
    assert last >= date(2026, 10, 28)
    assert _one(con, "select close from core.price_daily where cik = ? and session = ?",
                APPLE, last)[0] > 0  # fmt: skip


def test_every_dataset_has_a_data_as_of_date():
    with duckdb.connect(str(paths().serving_db), read_only=True) as serving:
        got = dict(serving.execute("select dataset, latest_date from app.freshness").fetchall())
    for dataset in ("prices", "filings", "financial_values", "insider_filings", "short_volume",
                    "vix"):  # fmt: skip
        assert got.get(dataset) is not None, dataset
    assert any(k.startswith("fred:") for k in got)
    assert got["insider_filings"] >= date(2026, 10, 28)  # daily Form 4s, past the 2026q3 data set


def test_price_only_stocks_have_long_histories(con):
    """Foreign companies listed in the US but filing nothing periodic with the SEC (V2-11) are
    priced from their listing (V2-18): Hitachi's ADR from April 2012, Deutsche Telekom's from
    2010."""
    first = dict(con.execute(
        "select cik, min(session) from core.price_daily where cik in (?, ?, ?, ?) group by 1",
        [HITACHI, DEUTSCHE_TELEKOM, STANDARD_LIFE, NGK]).fetchall())  # fmt: skip
    assert first[HITACHI] <= date(2012, 4, 27)
    assert first[DEUTSCHE_TELEKOM] <= date(2010, 6, 21)
    assert STANDARD_LIFE in first and NGK in first  # renamed (abrdn; Niterra): now priced
    (long,) = _one(con, "select count(*) from core.price_coverage c join ref.security s "
                        "on s.security_id = c.cik where s.coverage = 'price_only' "
                        "and c.priced_from < '2025-01-01'")  # fmt: skip
    assert long >= 450


def test_every_listed_symbol_was_asked_of_yahoo_and_every_unpriced_company_has_a_reason(con):
    p = paths()
    book = Manifest(p.manifest)
    assert yahoo.missing_histories(p, book, yahoo.listed_symbols(p, book)) == []
    assert _one(con, "select count(*) from core.price_coverage where reason is null")[0] == 0


def test_daily_form4s_match_the_quarterly_data_set(con):
    """The filings of 24–30 September 2026, fetched one by one and parsed (US4), against the
    2026q3 data set built from the same documents: no filing differs."""
    (both,) = _one(con, "select count(*) from stg_sec_form4_daily.submission d "
                        "join stg_sec_form4.submission q using (accession_number) "
                        "where d.filing_day between '2026-09-24' and '2026-09-30'")  # fmt: skip
    assert both >= 1_000
    differ = con.execute(
        "select r.* from core.form4_reconciliation r join stg_sec_form4_daily.submission d "
        "on d.accession_number = r.accession where d.filing_day between '2026-09-24' and "
        "'2026-09-30'"
    ).fetchall()
    assert differ == []


def test_a_form4_filed_on_28_october_is_in_the_tracker(con):
    """Derek Williams, an officer of Consumers Bancorp, bought 100 shares at $31.71 on 28 October
    2026; the filing was accepted at 16:57, after the close, so it is known from the 29th."""
    row = _one(con, "select side, owner_names, entity_role, shares, value_usd, known_at "
                    "from core.insider_activity where accession = ?",
               "0001437749-26-033807")  # fmt: skip
    assert row == ("buy", ["WILLIAMS DEREK G"], "officer", 100.0, pytest.approx(3171.0),
                   date(2026, 10, 29))  # fmt: skip
