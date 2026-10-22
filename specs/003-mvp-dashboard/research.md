# Research: MVP Prototype Dashboard

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-22

Live checks on 2026-10-22: feature 001's provisional outputs, the SEC ticker snapshot, a Yahoo download test in a throw-away environment, and dependency resolution for Python 3.14.

## R1. How much of the pilot can be priced (survivors)

- **Finding**: of the **6,937** pilot events (2006–2011: 5,399 clusters, 1,538 solo CEO/CFO buys) at 3,117 companies, **2,555 events (37%) at 1,008 companies** belong to CIKs still in today's SEC ticker map:
  - clusters 1,959 of 5,399; solo CEO/CFO 596 of 1,538;
  - today's venues: NYSE 1,434, Nasdaq 1,044, OTC 74.
- **Recent events (July–September 2026)**: 244, of which **228** are listed today and can be scored.
- **Yahoo history coverage**: in a random sample of 25 listed pilot companies, **22 have history back to 2005–2006**. Three would not cover their pilot events:
  - Kodak (`KODK`), re-listed in 2013 after bankruptcy;
  - Par Pacific (`PARR`), from 2012;
  - `ANG-PD`, a preferred-share ticker picked by mistake (see R3).

  Expect about 30–34% of pilot events to be priced before the floors.
- **Decision**: proceed. About 2,000 priced events are enough for a stable event study and a small model: roughly 1,600 training (2006–2010) and 400 test (2011). Coverage is shown by group on the Overview and Findings pages (FR-020). The spec's below-30% warning (SC-005) may well trigger after the floors, and that is fine: it is honest.
- **Why survivors-only matters**: every pilot event at a company that later failed or was acquired is missing. This is the clearest possible demonstration of why the full study pays for Tiingo. The Method page says so with these numbers.

## R2. Yahoo download behaviour

- **Finding**: `yfinance 1.7.0` installs on Python 3.14, pulling in `curl-cffi 0.16.3` and `pandas 3.0`. One `yf.download([...27 tickers], start="2005-01-01", auto_adjust=False, actions=True, group_by="ticker", threads=True)` took **4.0 s** and returned `Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits` per ticker.
- **Price semantics with `auto_adjust=False`**:
  - `Open/High/Low/Close` are split-adjusted but not dividend-adjusted;
  - `Adj Close` is split- and dividend-adjusted;
  - `Volume` is split-adjusted;
  - `Stock Splits` gives the ratio on each split date.
- **Decision**:
  - **Batches**: download in batches of 50 tickers, about 1,240 in all (1,008 pilot + 228 recent + SPY + IWM), so about 25 batches and a few minutes.
  - **Caching**: cache each ticker as received, one Parquet file per ticker, in `data/mvp/raw/yahoo/`, with lines in `data/mvp/raw/manifest.jsonl` written through feature 001's `Manifest` class. Reruns skip cached tickers. The cache sits in the MVP's own folder, as the constitution's Prototype Exception requires.
  - **Failures**: a failed batch is retried with back-off up to 3 times, then the ticker goes to `failures.csv` and is counted as unpriced.
- **Derived prices**:
  - **As-traded close** (for the floors) = `Close × Π(split ratios after that date)`.
  - **Dollar volume** = `Close × Volume`, which is the same adjusted or not.
  - **Adjusted open** for entry = `Open × (Adj Close ÷ Close)` on the entry day.
- **Provider terms**: personal use. The dashboard shows derived results only (FR-018).

## R3. Choosing the price ticker for a company

- **Finding**: the SEC map can list several tickers per CIK, including preferred shares (`ANG-PD`), warrants (`-WS`) and units (`-U`).
- **Decision**:
  1. Prefer the snapshot ticker that equals the company's last ticker reported in Form 4s (normalised).
  2. Otherwise prefer the snapshot ticker with no `-` suffix, shortest first.
  3. Then any remaining ticker.

  For Yahoo, `.`/`/` class separators become `-` (e.g. `BRK-B`).

## R4. Returns, floors and cost (FR-007 – FR-010)

- **Calendar**: SPY's trading days.
  - **Session "at T"**: the last session on or before T (the SEC is open on some market holidays).
  - **Entry**: the next session's open.
- **Path**: for k = −20 … 252 sessions relative to the entry day (k = 0), the stock's cumulative return to the close of session k from the entry open is `AdjClose[k] ÷ AdjOpen[0] − 1`. For k < 0 the same formula shows the run-up or decline before entry. The benchmark (IWM, SPY) uses the same formula, and the **abnormal return is the difference** (a buy-and-hold abnormal return). Headline horizons are 5, 21, 63, 126 and 252 (`registered.horizons`).
- **Floors** at the session at T: as-traded close ≥ `registered.price_floor.value` ($2) and 20-session mean dollar volume ≥ $100,000 (`registered.liquidity_floor`).
- **Cost (simple)**: Abdi & Ranaldo (2017) close-high-low spread estimate, averaged over the 20 sessions to T, floored at one tick ($0.01 ÷ as-traded close), with round-trip cost = estimated spread. The net abnormal return is gross minus cost. Price impact is left for the full study (spec Assumptions).
- **Guard**: the return builder **raises** if given any event dated 2012-01-01 or later (constitution, Prototype Exception; FR-003, FR-022). A test asserts this, and also that the stored outcome tables have `max(signal_date) ≤ 2011-12-31`.

## R5. Event-study uncertainty that respects overlap (FR-010)

- **Decision**: a moving-block bootstrap over **calendar months** (plan §7.1, scaled down).
  1. Group events by signal month and average within each month.
  2. Resample blocks of consecutive months, with block length ⌈H/21⌉ months, at least 1 (3 for the 63-session headline).
  3. Use 1,000 replications and the 2.5–97.5 percentiles of the mean of monthly means.
- For the path chart, the bands use a 3-month block at every k. The seed is fixed.
- **Rationale**: events in the same month share market moves. Monthly blocks stop the bands pretending events are independent, which the constitution's Principle IV requires in spirit even for a prototype.

## R6. Model (FR-011 – FR-014)

- **Label**: 63-session abnormal return against IWM, net of cost, > 0.
- **Split**:
  - **Train**: pilot events with signal year 2006–2010 whose 63-session window ends before 2011-01-01 (purged).
  - **Test**: 2011 events.
  - **Scoring model**: refitted on all pilot events (2006–2011) with the same settings, so recent events benefit from the 2011 data. This is documented on the Model page.
- **Features**, all as of T (spec FR-012; plan F-numbers where they exist):
  - **From the insider filings**: F1 number of buyers; F2 total value (log); F3 largest buyer's share; F4 CEO/CFO count; F5 director count; F6 10%-owner count; F7 mean log holdings increase; F8 new positions; F11 mean filing lag; F12 value of insider sales in the prior 90 days; F13 any CEO/CFO sale in the prior 90 days; F14 clean purchases in the prior 365 days.
  - **From prices**: F17 ADDV20 (log); F18 value ÷ ADDV20; F19 prior 21-session return; F20 momentum (T−252 to T−21); F21 distance from the 52-week high; F22 63-session volatility; F23 estimated spread.
  - **Market-only baseline**: F17 and F19–F23.
- **Feature data not in the scratch database**: holdings after each line and code-S sales are read from the raw archives with `sentinel.ingest.sec_tables` for the quarters involved: 2005 Q1–2011 Q4 for pilot look-backs, and 2025 Q3–2026 Q3 for recent ones. That is about 30 quarters at about 1.3 s each.
- **Models**:
  - (a) logistic regression with L2, median imputation plus missing-value indicators, standardised;
  - (b) LightGBM with a small fixed setting (num_leaves 15, min_child_samples 30, learning_rate 0.05, 300 rounds, seed 2002);
  - (c) the market-only baseline, the better family of (a)/(b) trained on F17 and F19–F23.

  There is no tuning grid; it's a prototype. The fixed settings live in `mvp/params.yaml`.
- **Metrics on 2011**: AUC; log loss; Brier score; a calibration curve in 5 quantile bins; the mean net 63-session return of the top fifth by score against all 2011 events.
- **Drivers**: permutation importance on the 2011 test set (scikit-learn), mapped to plain-language feature names. SHAP is left for the full study, to avoid a heavy dependency.
- **Selection**: the lower 2011 log loss between (a) and (b) (FR-014).

## R7. Web stack and design

- **Decision**: FastAPI + Jinja2 server-rendered pages + HTMX for the company search, which is the product stack in plan §8.3 and constitution VII, so the MVP is a head start on the real product rather than a throw-away.
  - **Charts**: Apache ECharts.
  - **Vendoring**: ECharts 5.6.0 and HTMX 2.0.4 are vendored into `mvp/app/static/vendor/`, so the classroom demo works offline.
  - **Price widget**: the TradingView "Advanced Chart" embed (free, licensed for public display), which needs internet. It is the one external dependency, and the page degrades gracefully without it (spec edge case).
- **Data at serve time**: everything is precomputed by `build` into `data/mvp/serve/` (Parquet and JSON) and loaded once at start-up, so pages render from memory in milliseconds (SC-004). Chart data is embedded in each page as `<script type="application/json">`.
- **Design system**, from the data-visualisation reference instance:
  - **Tokens**: CSS custom properties for surfaces, ink and series. Light surface `#fcfcfb`, page `#f9f9f7`; dark surface `#1a1a19`, page `#0d0d0d`.
  - **Theme**: a light/dark toggle (`data-theme` on `<html>`, remembered in `localStorage` inside try/catch) plus `prefers-color-scheme`.
  - **Series**: slot 1 blue (`#2a78d6` / `#3987e5`) for clusters or the selected model; slot 2 orange (`#eb6834` / `#d95926`) for solo CEO/CFO or the second model; slot 3 aqua for a third series; grey for benchmarks and reference lines. At most 3 series per chart (the validated all-pairs limit).
  - **Warning style**: the pilot label uses the status *warning* colour with an icon and text, never colour alone.
  - **Type**: the system sans throughout, with tabular figures only in tables and axes.
  - **Marks**: 2px lines, a crosshair and tooltip on line charts, hover tooltips on bars and dots, recessive grids, a single y-axis, a legend whenever there are two or more series, and a "Show table" toggle on every chart.
- **Layout**:
  - a fixed top bar with the product name, the six-page navigation and the theme toggle;
  - content up to 1,200px wide;
  - KPI stat tiles above charts;
  - cards on a 12-column grid that collapses to one column below 900px;
  - no horizontal scroll at 1,280px (SC-006).

## R8. Libraries (resolved for Python 3.14)

| Package | Resolved | Pin | Role |
|---|---|---|---|
| fastapi | 0.159.1 | `>=0.156,<0.160` | Web app (plan §8.3) |
| uvicorn | 0.54.0 | `>=0.54,<0.55` | Local server |
| jinja2 | 3.1.6 | `>=3.1.6,<4` | Templates (plan §8.3) |
| yfinance | 1.7.0 | `>=1.7,<1.8` | Yahoo prices (plan §8.3); pulls in curl-cffi and pandas 3.0 |
| scikit-learn | 1.9.1 | `>=1.9,<1.10` | Logistic model, metrics, permutation importance (plan §8.3) |
| lightgbm | 4.7.0 | `>=4.7,<4.8` | Gradient-boosted model (plan §8.3) |

Every one is already in the plan's tech stack (§8.3), so no decision-log justification is needed beyond D44. They become project dependencies now; features 004 and 005 need them anyway.

## R9. Guards (FR-006, FR-022)

1. **No outcomes from 2012**: `mvp.pipeline.returns` raises on any event dated from 2012, and a test checks the stored outcome tables.
2. **Containment**: an AST scan of `src/sentinel/` fails on any `mvp` import, alongside the existing provisional guard.
3. **Pilot label**: a FastAPI `TestClient` renders every page, and the Overview, Findings, Model and Latest-clusters pages must contain the exact label text.
4. **Output location**: an MVP output path outside `data/mvp/` fails a path check in `mvp.config`.
