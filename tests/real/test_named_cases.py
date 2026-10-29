"""Named real cases on the built data/sentinel.duckdb (skipped without it): known events and values
from the public record, checked end to end through the layers."""

from datetime import date

import duckdb
import pytest

from sentinel.config import paths

pytestmark = pytest.mark.slow

APPLE, META, TESLA, JPM, TSMC = "320193", "1326801", "1318605", "19617", "1046179"
SIXTH_STREET, BED_BATH, ADAMS_FUND = "1508655", "886158", "2230"


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
