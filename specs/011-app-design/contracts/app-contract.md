# App Serving Contract (`data/serving.duckdb`)

The FastAPI application reads exclusively from `data/serving.duckdb` in `read_only=True` mode under schema `app`.

## Serving Tables Consumed

1. `app.stock`: Company identity, ticker, exchange, sector, SIC, filer type, coverage.
2. `app.company_card`: Latest fundamental snapshot, price, size, volatility, results timing, cash runway.
3. `app.price_daily`: Daily prices, adjusted close, volume.
4. `app.daily_score`: Machine learning forecasts (volatility, dilution, results move) with risk bands (1–5) and calibrated probability ranges.
5. `app.filings`: SEC filings with form types, descriptions, accession numbers, and EDGAR links.
6. `app.financials`: Periodic financial statement facts as first filed.
7. `app.insider_activity`: Form 4 open-market transactions with insider role, shares, and price.
8. `app.insider_feed`: Market-wide cluster purchases and C-suite solo acquisitions.
9. `app.screener`: Pre-indexed screening view across all active stocks.
10. `app.freshness`: Pipeline freshness timestamps per dataset.
