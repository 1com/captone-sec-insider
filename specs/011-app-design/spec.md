# Feature Specification: App Design, Architecture & Forecast Contract

**Feature Branch**: `011-app-design`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "Step 7: implement webapp - modern equity research terminal showing all ingestions, details, and predictions for any stock."

## Context

EDGAR-SENTINEL v2 is a market research platform for US-traded stocks. The data pipeline and machine learning models are complete, producing 21,000+ daily forecasts in `data/serving.duckdb` (schema `app`).

Feature 011 establishes:
1. The **front-end stack & visual terminal architecture** (Dark slate high-density professional research UI).
2. The **page map & wireframes** (Universal search, Stock page, Insider feed, Dilution check, Cross-stock screeners, Model card & validation).
3. The **app-serving contract**: exact schema and queries the FastAPI service reads from `data/serving.duckdb`.
4. The **FastAPI read-only web server** (`src/sentinel/app/`) running on **port 8080** (strictly preserving port 8000).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Universal Stock Search & Overview (Priority: P1)

An investor types a ticker (e.g. `AAPL`, `MSFT`, `TSLA`), company name, or CIK into the global search bar. The app instantly auto-completes and navigates to the stock's comprehensive research page.

**Acceptance Criteria**:
- Instant search endpoint `/api/search?q={query}` returns matching active stocks with ticker, name, sector, exchange, and coverage within 50ms.
- Navigating to `/stock/{ticker}` renders the company header, real-time price quote, and key metrics ribbon.

---

### User Story 2 - The 4 Core Intelligence Panels (Priority: P1)

On the stock page, the investor immediately sees four prominent intelligence panels answering the core investment questions:
1. **Expected Volatility (005)**: Annualized 63-day forward volatility forecast, 80% expected prediction interval, and risk band (1–5) compared with past realized volatility.
2. **Results-Day Move (006)**: Days until expected earnings release, expected price move magnitude, calibrated exceedance probabilities ($P > 5\%$, $P > 10\%$, $P > 20\%$), and band median comparison.
3. **Dilution Risk (007)**: 6-month dilution probability gauge, risk band (Band 1 Very Low to Band 5 Imminent), shelf registration count (S-3, 424B), 3-year share growth CAGR, and cash burn runway.
4. **Insider Flow & Signals**: 12-month net dollar value bought/sold by executives, buyer count in the last 14 days, and senior officer cluster alerts.

**Acceptance Criteria**:
- Displays calibrated probabilities and risk bands with clear qualitative labels (e.g. "Band 2 · Low Risk").
- Correctly handles `price_only` coverage by displaying volatility forecasts while cleanly noting fundamental/dilution data is unavailable.

---

### User Story 3 - Interactive Charts, SEC Filings & Financials (Priority: P1)

The investor can inspect deep historical context on the stock page:
- **Price Chart**: Interactive daily adjusted close and volume bars with 21-day and 63-day moving averages.
- **Financials**: Multi-period income statement and balance sheet items as first filed (Quarterly 10-Q & Annual 10-K).
- **SEC Filings Timeline**: Chronological list of all SEC submissions with plain-English summaries and direct one-click links to the official SEC EDGAR archive.
- **Insider Transactions**: Form 4 open-market buys and sells detailing officer name, role, shares traded, price, value, post-transaction holdings, and 10b5-1 pre-scheduled plan indicator.

---

### User Story 4 - Market-Wide Screeners & Insider Feed (Priority: P2)

An investor can discover opportunities across the entire market of 11,282 active stocks:
- **Screener (`/screener`)**: Filter by Volatility Band, Dilution Band, Results Move Band, Sector, Market Cap, or C-suite buying.
- **Insider Feed (`/insiders`)**: Live chronological stream of cluster buys and C-suite purchases across all companies.
- **Model Card (`/model-card`)**: Methodological transparency showing out-of-sample walk-forward test metrics against baselines.

