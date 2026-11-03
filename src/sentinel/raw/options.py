"""Option chain fetcher for US-traded equities using Yahoo Finance (Feature 023).

Fetches full Call and Put option chains across all available expiration dates up to
`max_days` (default: 365 days / 1 year) into the future.
Stores raw parquet snapshots in `data/raw/options/<date>/<ticker>.parquet`.
"""

import io
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from sentinel.config import Paths
from sentinel.raw import FetchReport
from sentinel.raw.manifest import Manifest, store_bytes

SOURCE = "options"


def fetch_option_chain_data(
    ticker_symbol: str,
    as_of: date | None = None,
    max_days: int = 365,
) -> pd.DataFrame:
    """Fetch call and put option chains for `ticker_symbol` for all expirations
    within `max_days`.
    """
    as_of_date = as_of or date.today()
    ticker = yf.Ticker(ticker_symbol.upper())
    try:
        expirations = ticker.options
    except Exception:
        expirations = None

    if not expirations:
        return pd.DataFrame()

    cutoff_date = as_of_date + timedelta(days=max_days)
    records: list[dict[str, Any]] = []

    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if exp_date < as_of_date or exp_date > cutoff_date:
            continue

        days_to_exp = (exp_date - as_of_date).days
        try:
            chain = ticker.option_chain(exp_str)
        except Exception:
            continue

        for opt_type, chain_df in [("call", chain.calls), ("put", chain.puts)]:
            if chain_df is None or chain_df.empty:
                continue

            for _, row in chain_df.iterrows():
                bid = float(row["bid"]) if pd.notna(row.get("bid")) else None
                ask = float(row["ask"]) if pd.notna(row.get("ask")) else None
                last_price = float(row["lastPrice"]) if pd.notna(row.get("lastPrice")) else None

                # Compute mid_price
                if bid is not None and ask is not None and bid > 0 and ask > 0:
                    mid_price = (bid + ask) / 2.0
                else:
                    mid_price = last_price

                vol = int(row["volume"]) if pd.notna(row.get("volume")) else 0
                oi = int(row["openInterest"]) if pd.notna(row.get("openInterest")) else 0
                iv = (
                    float(row["impliedVolatility"])
                    if pd.notna(row.get("impliedVolatility"))
                    else None
                )
                itm = bool(row["inTheMoney"]) if pd.notna(row.get("inTheMoney")) else False

                records.append(
                    {
                        "ticker": ticker_symbol.upper(),
                        "as_of": as_of_date,
                        "expiration": exp_date,
                        "days_to_exp": days_to_exp,
                        "option_type": opt_type,
                        "strike": float(row["strike"]),
                        "last_price": last_price,
                        "bid": bid,
                        "ask": ask,
                        "mid_price": mid_price,
                        "volume": vol,
                        "open_interest": oi,
                        "implied_volatility": iv,
                        "in_the_money": itm,
                        "contract_symbol": str(row.get("contractSymbol", "")),
                    }
                )

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


def fetch_options(
    p: Paths,
    today: date,
    echo=print,
    con=None,
    ticker: str = "AAPL",
    max_days: int = 365,
    **_,
) -> FetchReport:
    """Fetch option chains for a ticker and store as raw Parquet with manifest logging."""
    report = FetchReport(SOURCE)
    symbol = ticker.strip().upper()
    echo(f"fetching options for {symbol} up to {max_days} days...")
    df = fetch_option_chain_data(symbol, as_of=today, max_days=max_days)
    if df.empty:
        report.skipped = f"no option chains available for {symbol}"
        return report

    report.requests += len(df["expiration"].unique()) + 1
    rel_path = f"options/{today.isoformat()}/{symbol}.parquet"
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    raw_bytes = buf.getvalue()

    book = Manifest(p.manifest)
    if book.has_path(rel_path):
        echo(f"options for {symbol} on {today} already exists in raw manifest")
    else:
        url = f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}"
        store_bytes(p, book, SOURCE, rel_path, f"{symbol}/{today.isoformat()}", raw_bytes, url)
        report.stored(len(raw_bytes))
        report.latest_date = today

    return report
