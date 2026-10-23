"""Step 7: one price series per issuer (feature 004, research R2–R5; data-model.md "Prices").

`core.price_daily` holds **as-traded** open, high, low, close and volume (what printed that day),
the split- and dividend-adjusted close, and `cum_split_after`, the product of the split ratios dated
after the session (split-adjusted price = as-traded ÷ `cum_split_after`). `core.session` is the
market calendar: SPY's sessions, numbered.
"""

import duckdb

SESSION_COLUMNS = "session DATE, session_no INTEGER"
SERIES_COLUMNS = (
    "issuer_cik VARCHAR, price_source VARCHAR, ticker VARCHAR, role VARCHAR, first_session DATE, "
    "last_session DATE, n_sessions INTEGER, identity VARCHAR, chosen BOOLEAN, reason VARCHAR"
)
DAILY_COLUMNS = (
    "issuer_cik VARCHAR, session DATE, price_source VARCHAR, ticker VARCHAR, open DOUBLE, "
    "high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, adj_close DOUBLE, "
    "cum_split_after DOUBLE, split_ratio DOUBLE, dividend DOUBLE, dollar_volume DOUBLE"
)
TABLES = {
    "core.session": SESSION_COLUMNS,
    "core.price_series": SERIES_COLUMNS,
    "core.price_daily": DAILY_COLUMNS,
}


def create_price_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Empty price tables in the data-model layout, if absent (tests and first builds)."""
    for name, columns in TABLES.items():
        con.execute(f"create table if not exists {name} ({columns})")
