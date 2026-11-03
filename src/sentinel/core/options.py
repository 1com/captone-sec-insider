"""Core database management and market benchmark calculations for options (Feature 023).

Stores option chains in `core.option_chain` and computes market implied volatility
benchmarks in `core.option_summary`.
"""

from datetime import date
from typing import Any

import duckdb
import pandas as pd


def init_options_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create core.option_chain and core.option_summary tables if not already present."""
    con.execute("create schema if not exists core;")
    con.execute("create schema if not exists app;")

    con.execute(
        """
        create table if not exists core.option_chain (
            ticker VARCHAR NOT NULL,
            as_of DATE NOT NULL,
            expiration DATE NOT NULL,
            days_to_exp INTEGER NOT NULL,
            option_type VARCHAR NOT NULL,
            strike DOUBLE NOT NULL,
            last_price DOUBLE,
            bid DOUBLE,
            ask DOUBLE,
            mid_price DOUBLE,
            volume BIGINT,
            open_interest BIGINT,
            implied_volatility DOUBLE,
            in_the_money BOOLEAN,
            contract_symbol VARCHAR,
            primary key (ticker, as_of, expiration, option_type, strike)
        );
        """
    )

    con.execute(
        """
        create table if not exists core.option_summary (
            ticker VARCHAR NOT NULL,
            as_of DATE NOT NULL,
            spot_price DOUBLE,
            atm_iv_30d DOUBLE,
            atm_iv_60d DOUBLE,
            atm_iv_90d DOUBLE,
            call_volume BIGINT,
            put_volume BIGINT,
            put_call_ratio DOUBLE,
            primary key (ticker, as_of)
        );
        """
    )


def save_option_chain(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Idempotently insert option contracts into core.option_chain."""
    if df is None or df.empty:
        return 0

    init_options_tables(con)
    ticker = str(df["ticker"].iloc[0]).upper()
    as_of = df["as_of"].iloc[0]

    with con.cursor() as cur:
        # Idempotent replacement for this ticker and snapshot date
        cur.execute(
            "delete from core.option_chain where ticker = ? and as_of = ?",
            [ticker, as_of],
        )
        cur.register("tmp_opt_input", df)
        cur.execute(
            """
            insert into core.option_chain
            select
                ticker, as_of, expiration, days_to_exp, option_type, strike,
                last_price, bid, ask, mid_price, volume, open_interest,
                implied_volatility, in_the_money, contract_symbol
            from tmp_opt_input
            """
        )
        cur.unregister("tmp_opt_input")

    return len(df)


def compute_option_summary(
    con: duckdb.DuckDBPyConnection, ticker: str, as_of: date | None = None
) -> dict[str, Any]:
    """Compute ATM implied volatility benchmarks and Put/Call volume ratios."""
    init_options_tables(con)
    symbol = ticker.strip().upper()

    if as_of is None:
        row = con.execute(
            "select max(as_of) from core.option_chain where ticker = ?", [symbol]
        ).fetchone()
        if not row or row[0] is None:
            return {}
        as_of = row[0]

    # 1. Total volume & Put/Call ratio
    vol_row = con.execute(
        """
        select
            coalesce(sum(case when option_type = 'call' then volume else 0 end), 0) as call_vol,
            coalesce(sum(case when option_type = 'put' then volume else 0 end), 0) as put_vol
        from core.option_chain
        where ticker = ? and as_of = ?
        """,
        [symbol, as_of],
    ).fetchone()

    call_vol = int(vol_row[0]) if vol_row else 0
    put_vol = int(vol_row[1]) if vol_row else 0
    pcr = (put_vol / call_vol) if call_vol > 0 else None

    # 2. Estimate spot price from close or closest ATM call/put strike
    has_price_bar = (
        con.execute(
            "select count(*) from information_schema.tables "
            "where table_schema='core' and table_name='price_bar'"
        ).fetchone()[0]
        > 0
    )
    spot_row = (
        con.execute(
            """
            select close from core.price_bar p
            join app.stock s on s.cik = p.cik
            where s.ticker = ?
            order by session desc limit 1
            """,
            [symbol],
        ).fetchone()
        if has_price_bar
        else None
    )

    spot_price = float(spot_row[0]) if spot_row and spot_row[0] is not None else None

    if spot_price is None:
        # Fallback to median strike of near-the-money active contracts
        med_row = con.execute(
            """
            select median(strike) from core.option_chain
            where ticker = ? and as_of = ? and days_to_exp between 5 and 45 and volume > 0
            """,
            [symbol, as_of],
        ).fetchone()
        spot_price = float(med_row[0]) if med_row and med_row[0] is not None else 100.0

    # 3. Compute ATM IV for target tenors: 30d, 60d, 90d
    def get_atm_iv(target_days: int) -> float | None:
        # Find closest expiration to target_days
        exp_row = con.execute(
            """
            select expiration, abs(days_to_exp - ?) as diff
            from core.option_chain
            where ticker = ? and as_of = ?
            order by diff asc limit 1
            """,
            [target_days, symbol, as_of],
        ).fetchone()

        if not exp_row:
            return None
        target_exp = exp_row[0]

        # Get ATM Call & Put IV (strike closest to spot_price)
        iv_row = con.execute(
            """
            with atm as (
                select implied_volatility
                from core.option_chain
                where ticker = ? and as_of = ? and expiration = ?
                  and implied_volatility is not null and implied_volatility > 0.01
                order by abs(strike - ?) asc limit 4
            )
            select avg(implied_volatility) from atm
            """,
            [symbol, as_of, target_exp, spot_price],
        ).fetchone()

        return float(iv_row[0]) if iv_row and iv_row[0] is not None else None

    iv_30d = get_atm_iv(30)
    iv_60d = get_atm_iv(60)
    iv_90d = get_atm_iv(90)

    summary = {
        "ticker": symbol,
        "as_of": as_of,
        "spot_price": spot_price,
        "atm_iv_30d": iv_30d,
        "atm_iv_60d": iv_60d,
        "atm_iv_90d": iv_90d,
        "call_volume": call_vol,
        "put_volume": put_vol,
        "put_call_ratio": pcr,
    }

    # Save into core.option_summary
    con.execute(
        "delete from core.option_summary where ticker = ? and as_of = ?",
        [symbol, as_of],
    )
    con.execute(
        "insert into core.option_summary values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            symbol,
            as_of,
            spot_price,
            iv_30d,
            iv_60d,
            iv_90d,
            call_vol,
            put_vol,
            pcr,
        ],
    )

    return summary
