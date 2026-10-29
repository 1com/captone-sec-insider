# EDGAR-SENTINEL v2: specification

Version 2.0, 29 October 2026. This document says what v2 is and what it must do. How it is built is
in [architecture.md](architecture.md); why things are the way they are is in
[decisions.md](decisions.md) and [lessons-from-v1.md](lessons-from-v1.md); when, in [plan.md](plan.md).

## 1. What it is

A market research platform for any US-traded stock. For each stock it brings together, in one
place and updated every day, what is otherwise spread over SEC filings, price histories and
market data, and it adds four things a retail investor cannot easily get elsewhere:

1. **Dilution risk**: the chance the company issues 10% or more new shares within six months, with
   the red flags in its own filings.
2. **The expected results-day move**: how violent the next earnings day is likely to be, as chances
   of a large move, not a single number.
3. **Expected volatility**: how much the stock is likely to swing over the next three months.
4. **An insider tracker**: what the company's directors and officers have been buying and selling,
   cleaned of the trades that carry no information (gifts, option exercises, planned sales).

Plus the facts beneath them: prices, financial statements as first filed, and the company's SEC
filings in plain English.

v1 began as a study of whether clusters of insider purchases predict returns. It found no such
signal in 2012–2022 (see [lessons-from-v1.md](lessons-from-v1.md)), and the project became this
platform. v2 rebuilds it from the start around that purpose (decision V2-1).

## 2. Who it is for

A retail investor or student researching individual stocks: before buying, while holding (is a
results day or a share sale coming?) and when screening for stocks to look at. Private use; the
data licences limit what can be shown publicly (§6).

## 3. What the user sees

| Feature | What it shows | Must / Should |
|---|---|---|
| **Stock page** | price chart, key facts, financial statements as first filed with history, SEC filings timeline (8-K items in plain words), next results date | Must |
| **Dilution check** | the stock's own probability of a 10%+ share increase within 6 months, its band (1–5) with the band's past hit rate, and its red flags (losses, cash runway, offering and shelf filings, share growth) | Must |
| **Results-day move** | band, typical range (middle half of past moves in that band), chances of a 10%+ and a 20%+ move, next results date; never a single forecast number (D62) | Must |
| **Volatility** | band, expected yearly volatility and the 80% three-month range (its width set on all earlier years, V2-10) | Must |
| **Insider tracker** | Form 4 activity per stock and market-wide: open-market buys and sells by role, size and date, clusters of buyers; no claim that it predicts returns | Must |
| **Screeners** | filter the whole market by risk band, sector, size and recent insider activity | Must |
| **Model card** | how each forecast was made and how well it did, including live hit rates | Must |
| Filing alerts during the day | a shelf or offering filing updates the stock's dilution band within minutes (D64) | Should |
| More horizons | volatility for 1 and 6 months | Could |

v1's fourth forecast, a 50% price fall within a year, is dropped: it could rank stocks but not
forecast how many would fall (V2-9).

## 4. Coverage: which stocks get what

The universe is every security trading on a US venue (exchange or OTC) that we can price, plus, for
history, every one that traded since 2012 and has since disappeared. It is defined by what trades,
never by another question's data (V2-1, D63). Each stock falls into one coverage level:

| Level | Who | Example | Gets |
|---|---|---|---|
| **Full** | US-style SEC filers (10-K, 10-Q, 8-K) | Apple, Tesla, Ares Capital | everything |
| **Foreign filer** | foreign private issuers filing 20-F or 40-F | ASML, Shell, Novo Nordisk | prices, volatility, insider tracker (Form 4 since March 2026); no dilution or results-day forecast (counts filed once a year; results on 6-K without item codes); market value only where the ADR ratio is known |
| **Price only** | traded in the US but filing nothing periodic with the SEC | Hitachi, Deutsche Telekom (OTC ADRs) | prices and volatility |

Every forecast states which level the stock is in and why a forecast is missing. Funds, ETFs and
blank-check companies are not covered (their prices follow what they hold).

A stock outside a model's training range (for example under $1 or barely traded, see §7) still gets
a page; its forecast is labelled as outside the range and shown with the historical rates of its
group instead.

## 5. Data sources

| Source | What | Licence / access |
|---|---|---|
| SEC EDGAR | Form 4 data sets (quarterly), filing histories (`submissions.zip`), financial facts (`companyfacts.zip`), filing headers, the company–ticker list; daily filings index | free, with a contact in the User-Agent |
| Yahoo Finance (`yfinance`) | daily prices of stocks listed today, full history, and every new day | free, unofficial |
| Tiingo (Power plan, 26 Oct – 26 Nov 2026) | daily prices of stocks that have disappeared; a complete second source for listed stocks (cross-check and gap-fill) | paid; internal use only, never shown publicly; downloads stop on 26 November |
| FRED / ALFRED | rates, credit spread, CPI and unemployment as first published | free, API key |
| Cboe | VIX | free |
| FINRA | daily short-sale volume | free |
| Kenneth French data library | factors and industry returns | free |

Raw files are kept unchanged in `data/raw/` with a manifest line each (source, URL, time, size,
checksum). Nothing is ever edited in place.

## 6. Data rules

1. **Point in time.** Every fact carries the moment it became public (`known_at`): financials as
   first filed, macro values from their release day, a results release once its report is filed.
   Nothing is used before its `known_at`.
2. **Securities, not only companies.** A company may have several share classes and ADRs with a
   ratio; prices, market value and tickers belong to securities.
3. **Complete staging per source.** Each source's staging table holds everything downloaded from
   that source, with the file and line every row came from.
4. **Missing is not zero.** A filing that does not apply to a company (Form 4 for most foreign
   filers before March 2026, 8-K for foreign filers) leaves its features missing.
5. **Deterministic builds.** Rows are sorted before any model sees them; models with randomness are
   seeded and, where it matters, averaged over seeds.
6. **Every rule is checked on real data.** Each layer's tests include named real cases (Apple,
   ASML, Meta, Tesla, JPMorgan, a closed-end fund, a BDC) as well as synthetic ones.
7. **Tiingo stays private.** Values derived from Tiingo prices are never published; public pages
   use Yahoo-priced stocks only.

## 7. Models and how they are judged

The three risk forecasts follow the evaluation fixed in D60 before any model was built, and
`config/risk_params.yaml` v5 (tag `prereg-risk-v5`), carried over unchanged:

- each risk is tried as a simple rule, a classic small model and LightGBM on walk-forward test
  years 2019–2022, training purged by each answer's window;
- the simplest level within one standard error of the best is chosen; probabilities are calibrated;
  five bands carry their past hit rates; insider and macro data are measured by refitting without
  them (five seeds);
- the chosen models are tested **once** on the sealed holdout (answers whose windows start in 2023
  or later), which no development step may compute;
- training uses eligible rows only: close at $1 or more, $10,000 a day traded, an active SEC filer,
  63 days of prices, not a fund (the reasons are in [lessons-from-v1.md](lessons-from-v1.md)).

In production the models score every covered stock every day and are refitted about every quarter;
a new version replaces the current one only if it is no worse on recent data (D64).

## 8. Daily operation

Every evening after the US close, `sentinel update` fetches the day's prices, SEC filings and market
series, extends the reference and core tables, computes the day's features, scores every covered
stock and publishes a read-only serving snapshot that the app reads. A rerun on the same day changes
nothing. Outcomes are recorded as each forecast's window closes, giving live hit rates.

## 9. Out of scope

- Predicting returns, including the v1 insider study's hypothesis tests (dropped, V2-4).
- Options data (historical options data is paid; noted as a limitation).
- Intraday prices.
- Showing Tiingo-derived values on a public page.

## 10. Deliverables

| Date | Deliverable |
|---|---|
| 17 November 2026 | product v1: stock page, dilution check, risk card, insider tracker, screeners, model card, daily update |
| 18 November 2026 | the capstone report |
| before 26 November 2026 | everything that needs Tiingo; the offline rebuild check |
