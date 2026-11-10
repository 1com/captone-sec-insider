# Feature Specification: Stock research app, dilution first

**Feature Branch**: `026-stock-research-app`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a completely new and separate app. It will not show the expected
volatility or the expected earnings move; it is all about displaying the information we gather every
day, with dilution risk as the main feature. Redesign the whole thing so it looks like a
professional tool where users search for a stock and see all the information and the dilution
prediction. One page is enough: search a stock and see its price, volume history, all the
information about the company (market cap, industry, CIK, …) and the insider filing history, with
a chart showing buys and sells so people can see patterns easily." (the researcher, 10 Nov 2026;
decision V2-61). Faults of the old app it must not repeat: SEC filing descriptions missing, a
typed-in data date ("Oct 30, 2026"), no price and volume history, no short selling data, no
diagnostics, form types (8-K, 10-K, 10-Q, Form 4) without explanations.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Look up a stock and judge its dilution risk (Priority: P1)

An investor types a ticker or a company name ("MULN", "Mullen"), picks the company and sees at the
top of the page who it is (name, tickers, exchange, industry, CIK, market cap, last price) and, as
the main panel, the chance that the company's share count rises by 10% or more within the next six
months: how that compares with all companies, how reliable such forecasts have been, and why the
model says so. *Dilution* means the company issues new shares, so each existing share owns a
smaller part of the company; it often happens when a loss-making company sells shares to raise
cash.

**Why this priority**: the dilution forecast is the product's main feature and its reason to exist
beside free quote sites.

**Independent Test**: search the named cases (a large US company, a small loss-making company with
recent offerings, a foreign filer, a delisted company, a ticker used by two companies over time);
each page shows the company's facts and either the dilution panel or the reason it is absent.

**Acceptance Scenarios**:

1. **Given** an eligible company still trading, **When** its page opens, **Then** the dilution
   panel shows the chance as a percentage, its band (risk group), the share of all eligible
   companies that diluted in the test years for comparison, how often companies in the same band
   diluted in each test year 2019–2022, the main reasons (three to five) in plain words with the
   company's own values, the share count over time, and the date of the forecast.
2. **Given** a foreign filer (for example ASML), **When** its page opens, **Then** the panel says
   that no dilution forecast is made for foreign filers and why (V2-27), and the rest of the page
   is complete.
3. **Given** a company that no longer trades, **When** its page opens, **Then** the panel says so
   and shows no forecast; its history (prices, filings, insider trades) is still shown.
4. **Given** a ticker used by more than one company over time (for example DIS), **When** it is
   searched, **Then** each company is listed with its name and dates, the one listed today first.
5. **Given** any page, **When** it is shown, **Then** the date the data is current to is read from
   the data for each source (prices, filings, insider filings, short selling, financials), never
   typed in.

---

### User Story 2 - See the price and volume history (Priority: P1)

The investor sees the daily closing prices and traded volumes over a chosen period (one month,
three months, six months, one year, five years, all), with insider purchases and sales and share
offering filings marked on the same timeline, to see how events lined up with the price.

**Why this priority**: price and volume history is the basic context of any research tool; its
absence was the first fault of the old app.

**Independent Test**: open a company with a reverse split and one with insider trades; the price
line has no jump at the split, the last point equals the latest close in the data, and markers sit
on the trade and offering dates.

**Acceptance Scenarios**:

1. **Given** a priced company, **When** a period is chosen, **Then** the chart shows the daily
   price and volume for that period, and pointing at a day shows its date, open, high, low, close
   and volume.
2. **Given** a stock split inside the period, **When** the chart is shown, **Then** prices are
   adjusted for the split, so the line shows no artificial jump.
3. **Given** insider trades or offering filings inside the period, **When** the chart is shown,
   **Then** each is marked on its date, with its details when pointed at.
4. **Given** a company without prices, **When** its page opens, **Then** the chart area says that
   no price data exists for it, and why if known.

---

### User Story 3 - See insider buying and selling patterns (Priority: P2)

The investor sees, month by month, how much the company's insiders (officers, directors, owners of
10% or more) bought and sold, buys and sells drawn on opposite sides of a line so that clusters of
buying or waves of selling stand out, and a table of every reported trade.

**Why this priority**: the insider tracker is one of the platform's four questions, and patterns
(several insiders buying at once, heavy selling) are what users look for in Form 4 filings.

**Independent Test**: for named companies with known insider purchases and sales, the monthly
totals and the table match the Form 4 filings in the data.

**Acceptance Scenarios**:

1. **Given** a company with Form 4 filings, **When** its page opens, **Then** a chart shows per
   month the value bought and the value sold and the number of insiders, for the last two years by
   default and up to all years.
2. **Given** the trade table, **When** it is shown, **Then** each filing lists its date, the
   insider's name and role, buy or sell, shares, average price, value, whether the sale was
   pre-planned (a 10b5-1 plan), and a link to the filing on the SEC's site, newest first.
3. **Given** pre-planned sales, **When** the user chooses to hide them, **Then** the chart and the
   table show only the other trades.
4. **Given** several insiders buying within 14 days (the tracker's cluster rule), **When** the chart
   is shown, **Then** the cluster is highlighted.
5. **Given** a company without Form 4 filings, **When** its page opens, **Then** the section says
   there are none (no empty chart).

---

### User Story 4 - Read the SEC filings in plain English (Priority: P2)

The investor sees the company's SEC filings, newest first, each with its form code, a plain-English
name and a one-line explanation (for example "10-Q, quarterly report: unaudited results for the
quarter"), every 8-K's items translated ("Item 2.02: results of operations"; "Item 3.02: shares
sold without registration, often dilution"), a filter by kind and a link to the filing.

**Why this priority**: the filings are the primary source; without explanations a new investor
cannot tell what they are (a fault of the old app).

**Independent Test**: open a company with 8-Ks, an S-3 and a 424B prospectus; every filing shows a
name and explanation, and an 8-K with items "2.02, 9.01" reads as words.

**Acceptance Scenarios**:

1. **Given** a filing, **When** it is listed, **Then** it shows its form code, plain-English name,
   filing date and a link, and its explanation on demand.
2. **Given** an 8-K, **When** it is listed, **Then** each item number is shown in words.
3. **Given** the filter, **When** a kind is chosen (annual and quarterly reports; current reports;
   offerings and registrations; insider and ownership filings; proxy filings; other), **Then**
   only that kind is listed.
4. **Given** an amendment (a form code ending in "/A"), **When** it is listed, **Then** it reads as
   an amendment of the named form.
5. **Given** a form type without its own description, **When** it is listed, **Then** it shows its
   code, its kind's general description and the link.

---

### User Story 5 - See short selling (Priority: P3)

The investor sees how much of the stock's trading is short selling over time, with a plain
explanation of what the number measures and what it does not. *Short selling* is selling borrowed
shares in the hope of buying them back cheaper; a lot of it can mean that traders expect the price
to fall.

**Why this priority**: a common question about small, risky companies; missing in the old app.

**Independent Test**: for a company with short-sale data, the chart's values match the data.

**Acceptance Scenarios**:

1. **Given** a company with short selling data, **When** its page opens, **Then** the section shows
   [NEEDS CLARIFICATION: is FINRA's daily short-sale volume (collected now: the share of each
   day's reported volume that was sold short) enough, or should short interest (the shares sold
   short and not yet bought back, published twice a month) be added as a new data source?], with
   its explanation and its date.

---

### User Story 6 - See key financials as first filed (Priority: P3)

The investor sees the company's main reported numbers for its last eight quarters and four fiscal
years, as first filed: revenue, net income, operating cash flow, cash, total debt and shares
outstanding, each with the date it was filed.

**Why this priority**: the context for the dilution forecast (a company burning cash with little
left is the classic diluter); the numbers exist in the data.

**Independent Test**: for named companies, the numbers equal the values in the data for the same
periods.

**Acceptance Scenarios**:

1. **Given** a company that files financial statements, **When** its page opens, **Then** the
   table shows the numbers per period with their filing dates; a number the company did not report
   shows as missing, never as zero.

---

### User Story 7 - Diagnostics (Priority: P3)

The investor (and the researcher) can check how much to trust the page.

**Why this priority**: the old app had none; trust in the data and the forecast is the product's
promise.

**Independent Test**: for named companies, every item of the diagnostics section matches the data.

**Acceptance Scenarios**:

1. **Given** any company, **When** the diagnostics section is opened, **Then** its first part shows
   the data behind the page (researcher, 10 Nov: both parts): per source where the company's data
   comes from and the period it covers (prices: source, first and last day, days missing; the last
   filing, the last insider filing, the last financial report and its period; short selling), and
   the data-quality notes that apply to the company (price days removed as glitches, share counts
   adjusted for splits or corrected, coverage level).
2. **Given** an eligible company, **When** the diagnostics section is opened, **Then** its second
   part shows how the dilution forecast works and how good it is: the model and its approval
   (V2-52); its test results per test year 2019–2022 against the simpler levels; a calibration
   chart (forecast chance against how often companies diluted); every factor behind this
   company's forecast with its effect; the model's limits (no forecast for foreign filers; trained
   on answers known before 2023); and, once the holdout test has run, its result on the years
   2023 onwards, as recorded.

---

### Edge Cases

- A ticker reused by several companies, or a company with several tickers (share classes): the
  search finds the company by any of them; the page lists all its tickers with their dates.
- A company without prices (it files with the SEC but its shares do not trade on a US venue): the
  page shows its facts, filings and insider trades; the chart says that no prices exist.
- A delisted company: its last trading day is shown; no dilution forecast.
- A value that is unknown (no market cap, no reported cash): shown as missing with the reason when
  known, never as zero.
- A forecast older than the latest data (the daily scoring failed one day): the panel shows the
  forecast's date and says it is not from the latest update.
- The serving copy missing or unreadable: the app shows an error saying so, and no data.
- The daily update replacing the serving copy while the app runs: the app reads the new copy
  without a restart and never shows a mix of two days.
- Reverse splits in small companies: prices and the share count over time are adjusted for splits,
  with the split dates marked.
- Funds and blank-check companies (SPACs): flagged on the page; the dilution panel follows the
  question's eligibility rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to search by ticker or company name (current or former), with
  suggestions while typing; a ticker used by several companies lists each with its dates, the one
  listed today first.
- **FR-002**: The page MUST show the company's facts: name, current and former tickers, exchange,
  CIK with a link to the company's SEC page, industry and sector, US or foreign filer, fund or
  blank-check flag, listed or delisted (with the last trading day), last close and its change,
  52-week high and low, average daily traded value, market cap and shares outstanding (with their
  dates).
- **FR-003**: The dilution panel MUST show, for an eligible company still trading: the chance that
  shares outstanding rise 10% or more within six months; its band; the rate of dilution among all
  eligible companies in the test years for comparison; how often companies in the same band
  diluted in each test year 2019–2022; three to five main reasons in plain words with the
  company's values; the share count over time, adjusted for splits; the date of the forecast and
  the model it came from.
- **FR-004**: Where no forecast is made (a foreign filer, V2-27; a company not trading; a company
  outside the question's eligibility rules; no forecast yet), the panel MUST say which and why.
- **FR-005**: Every weekday the daily update MUST produce the dilution forecast, with its main
  reasons, for every eligible company still trading, by the approved model (V2-52), the same frozen
  object the holdout test scores (V2-59). Forecasts from unapproved models MUST never be shown.
- **FR-006**: The page MUST show a daily price and volume chart, split-adjusted, with periods from
  one month to all history, and the day's values when a day is pointed at.
- **FR-007**: The chart MUST mark insider purchases and sales and share-offering filings on their
  dates.
- **FR-008**: The insider section MUST show the monthly values bought and sold (on opposite sides)
  and the number of insiders, highlight clusters (several insiders buying within 14 days), and let
  the user hide pre-planned sales.
- **FR-009**: The insider table MUST list each Form 4 filing: date, insider, role, buy or sell,
  shares, average price, value, pre-planned or not, link to the filing.
- **FR-010**: The filings section MUST list the company's filings newest first, each with its form
  code, plain-English name, explanation, filing date and link; 8-K items in words; amendments as
  amendments; a filter by kind.
- **FR-011**: Every form type with at least 100 filings in the data and every 8-K item number MUST
  have a plain-English name and explanation; any other form type MUST show its kind's general
  description.
- **FR-012**: The short selling section MUST show [NEEDS CLARIFICATION: see User Story 5] over
  time, with a plain explanation of what it measures and its date.
- **FR-013**: The financials section MUST show revenue, net income, operating cash flow, cash, total
  debt and shares outstanding for the last eight quarters and four fiscal years, as first filed,
  with their filing dates; unreported values shown as missing.
- **FR-014**: The page MUST show the date each source is current to (prices, filings, insider
  filings, short selling, financials), read from the data.
- **FR-015**: The diagnostics section MUST show two parts (researcher, 10 Nov): the data behind the
  page (per source: origin, period covered, gaps, last items; the data-quality notes that apply
  to the company) and the dilution model's workings (model and approval, test results per year
  against the simpler levels, calibration, every factor behind the company's forecast, limits,
  and the holdout result once recorded), all read from the data and the model report's records.
- **FR-016**: Each market term on the page (dilution, market cap, CIK, Form 4, 10b5-1 plan, short
  selling, band, …) MUST have a short plain-English explanation on the page.
- **FR-017**: The app MUST NOT show the expected volatility or the expected results-day move,
  anywhere (V2-61).
- **FR-018**: The app MUST read only the serving copy that the daily update publishes, read-only,
  and MUST pick up each new copy without a restart.
- **FR-019**: When the serving copy is missing or unreadable, the app MUST show an error saying so
  and no data; it MUST never show invented, sample or typed-in values (tests use their own test
  data).
- **FR-020**: Values derived from Tiingo MUST NOT appear on any public page (constitution VI):
  [NEEDS CLARIFICATION: will the app be used only on this machine for v1, or published online?
  Online, the prices of the companies priced from Tiingo (562 listed, 4,274 delisted) and every
  value computed from them must be hidden, and Yahoo's terms do not allow redistributing its
  prices].
- **FR-021**: The app MUST run on a port checked to be free in WSL and on Windows, and refuse a busy
  or reserved port (8000, 8080, 8090 belong to other programs); by default it is reachable from
  this machine only.
- **FR-022**: The page MUST look like a professional research tool: one page with its sections in a
  fixed order, a consistent layout and typography, numbers with units and sensible rounding
  (\$1.2B, 34%), the same colours for the same meaning everywhere (buy and sell, up and down,
  risk bands), every chart with labelled axes; usable on a laptop screen and readable on a phone.
- **FR-023**: Every number on the page MUST come from the data; a test MUST compare the page's
  numbers with the data for named companies.
- **FR-024**: After the researcher approves the new app, the old app (011–017) MUST be removed,
  with the researcher's agreement.

### Key Entities *(include if feature involves data)*

- **Company**: identified by its CIK; name and former names, industry, sector, filer type, flags
  (fund, blank-check), listed or not; has securities.
- **Security**: a ticker on an exchange over a period (share classes, ADRs); a ticker can belong to
  different companies at different times.
- **Daily price**: per company and trading day: open, high, low, close, volume, split adjustment,
  source.
- **Filing**: per company: form code, filing date, report date, 8-K items, link.
- **Form description**: per form code and per 8-K item: plain-English name, explanation, kind.
- **Insider trade filing**: per Form 4: insider names and role, buy or sell, shares, average price,
  value, pre-planned flag, link; clusters of several insiders.
- **Dilution forecast**: per company and day: chance, band, main reasons, model, date.
- **Band record**: per band and test year: how often companies diluted.
- **Short selling record**: per company and day (see FR-012).
- **Financial value**: per company, item and period: value as first filed, filing date.
- **Source date**: per data source: the date it is current to.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 95% of 100 randomly chosen listed companies, the full page appears within 2
  seconds of choosing the company, on this machine.
- **SC-002**: For ten or more named cases (a large US company, a small diluter, a foreign filer, a
  delisted company, a reused ticker, a reverse split, a company without insider trades, a
  blank-check company, a company without prices, a recent offering), every section shows values
  equal to the data, or the stated reason for their absence.
- **SC-003**: After each weekday update, 100% of the eligible companies still trading have a
  dilution forecast dated that update.
- **SC-004**: 100% of the form types with at least 100 filings and of the 8-K item numbers in the
  data have a plain-English name and explanation.
- **SC-005**: No page shows a typed-in date or number: a test checks every date and number on the
  named cases' pages against the data.
- **SC-006**: No page shows a volatility or results-day move forecast (a test checks every page
  type).
- **SC-007**: With the serving copy missing, every page shows the error and no data (a test).
- **SC-008**: Across a daily update, the app keeps answering and shows the new day's data without a
  restart.

## Assumptions

- Users are investors new to markets, reading English in a desktop browser; the phone layout is a
  readable fallback, not a separate design.
- Scope (V2-61): one stock page with search. Left out of v1: the volatility and results-day move
  forecasts, screeners, the market-wide insider feed, alerts, user accounts, option chains (023).
- Data: the serving copy published by each weekday update. New serving tables the page needs
  (for example the daily short selling series or the form descriptions) are added in the publish
  step; the pipeline's cleaning stays frozen (V2-33).
- The dilution forecast uses the approved frozen model until the first quarterly refit (021, after
  the holdout test); its band record comes from the test years in the model report (008).
- Old forecasts from unapproved models (27 Oct – 3 Nov) stay in the stored history but are never
  shown.
- The old app keeps running until the new one is approved; then it is removed (FR-024).
- The product must work before the hand-in on 17 November 2026.
