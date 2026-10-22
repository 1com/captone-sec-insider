# Feature Specification: MVP Prototype Dashboard

**Feature Branch**: `003-mvp-dashboard`

**Created**: 2026-10-22

**Status**: Draft

**Input**: User description: "Feature 003 — MVP prototype dashboard (decision D44; constitution v3.0.0 'Prototype Exception (MVP)' governs it). A self-contained prototype in the `mvp/` folder that shows teachers what EDGAR-SENTINEL will look like, built before the real insider warehouse and before prereg-v1, using real data, real modelling and a professional-grade dashboard. Data: feature 001's provisional insider events and clean filings, the SEC ticker snapshot, Yahoo prices for companies still listed plus SPY and IWM; no Tiingo. Returns only for events from 2006 to 2011 (pilot sample), labelled 'Pilot sample (2006–2011), survivors only — prototype, not research results'; the model may score recent events but no outcome is computed for events from 2012. Analysis: T+1 open entry, abnormal-return paths −20 to +252 sessions against IWM and SPY, a 63-session net headline, simple floors from unadjusted prices, clusters against solo CEO/CFO with overlap-aware bands; a logistic and a gradient-boosted classifier against a market-only baseline, trained 2006–2010, checked on 2011, scoring the July–September 2026 clusters. Pages: Overview, Latest clusters screener, Company lookup, Findings, Model, Method & limitations; a professional design for laptop and projector, light and dark; derived results only. One command builds and one serves; a 5-minute demo script. Out of scope: production rules, Tiingo, the 2012–2026 study, the holdout, public deployment. Success: demo-ready by 26 October 2026, the label on every return and model view, automated checks for no outcomes from 2012 and no imports of mvp, pilot coverage shown, fast pages."

## Context

The full study (2012–2026) cannot show returns before the pre-registration is locked. The researcher still needs to show teachers *now* what the finished product will look like. This prototype uses the one window the constitution allows: insider purchase events from **2006–2011**. They fall before the study window, so looking at their returns does not compromise the real tests. Prices come from Yahoo for companies still listed today, so the prototype describes survivors only and says so on every relevant view.

What the prototype has to work with, from feature 001:
- **Pilot events:** 6,937 provisional events at 3,117 companies (5,399 clusters, 1,538 solo CEO/CFO buys).
- **Latest quarter:** 244 recent events from July–September 2026 (168 clusters, 76 solo CEO/CFO buys), available to score.

The actors are **the researcher**, who presents, and **the teachers**, who watch the demo and judge the product idea.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See whether insider clusters paid off (Priority: P1)

A teacher opens the dashboard and immediately sees the research question, how the data was narrowed from 83 quarters of filings to insider clusters, and the headline result. Did stocks that insiders bought together beat the market over the following three months, before and after trading costs? How did that compare with a CEO or CFO buying alone? Each result is clearly marked as a survivors-only pilot.

**Why this priority**: this is the core of the project. Without a result there is nothing to demonstrate.

**Independent Test**: build the prototype and open the Overview and Findings pages. Check that the return paths, the headline 63-session figures (gross and net) and the cluster vs solo comparison appear with uncertainty bands and the pilot label.

**Acceptance Scenarios**:

1. **Given** a built prototype, **When** the Overview page opens, **Then** it shows the question, the data funnel (quarters → filings → clean purchases → events → priced pilot events) and three or four headline numbers, each with the pilot label where it involves returns.
2. **Given** the Findings page, **When** it loads, **Then** it shows the average abnormal-return path from 20 sessions before to 252 sessions after entry, for clusters and solo CEO/CFO buys, against IWM (with SPY selectable), with uncertainty bands.
3. **Given** the Findings page, **When** the viewer looks at the headline table, **Then** it shows, for each group and for horizons of 5, 21, 63, 126 and 252 sessions: the number of events, the mean and median abnormal return, and the share positive, gross and net of the estimated cost.
4. **Given** any view showing returns or model performance, **When** it is displayed, **Then** the label "Pilot sample (2006–2011), survivors only — prototype, not research results" is visible without scrolling.

---

### User Story 2 - See today's insider clusters ranked by a model (Priority: P2)

A teacher sees the product's main use: a list of the most recent real insider clusters, each scored by a model trained on the pilot years. A page explains how well that model did on the year it was checked on, compared with a model that sees only market data.

**Why this priority**: it shows that the project is a working tool, not just a backtest, and it demonstrates the ML component, which is the capstone's focus.

**Independent Test**: open the Model page and confirm it shows test-year performance for each model against the market-only baseline, plus a calibration view and the top drivers. Open the Screener and confirm the July–September 2026 events appear with scores and can be filtered and sorted.

**Acceptance Scenarios**:

1. **Given** the pilot events, **When** the models are trained on 2006–2010 and checked on 2011, **Then** the Model page shows, for the logistic model, the gradient-boosted model and the market-only baseline: ranking quality, probability accuracy, and the average net return of the top fifth of scored events in 2011.
2. **Given** the Model page, **When** it loads, **Then** it shows a calibration chart (predicted vs observed) and the most influential features of the selected model, in plain language.
3. **Given** the Screener, **When** it loads, **Then** it lists the July–September 2026 events with company, ticker, date, group, number of insiders, total value, the roles involved and the model score. The list can be filtered by group, score range and minimum value, and sorted by any column.
4. **Given** a recent event, **When** it is scored, **Then** no return or outcome for it is computed or shown. Only the score and its inputs appear.

---

### User Story 3 - Look up any company's insider activity (Priority: P3)

A teacher types a ticker or company name and sees that company's insider history: buys and sells over time, who made them (roles), any clusters, and a price chart from a licensed embeddable widget.

**Why this priority**: it shows the second half of the product, and it makes the demo interactive. A teacher can ask "what about company X?".

**Independent Test**: search for a well-known company and a delisted one. The first shows its insider timeline and the chart widget. The second shows its insider history with a note that no price data is available.

**Acceptance Scenarios**:

1. **Given** a ticker or a name fragment, **When** the viewer searches, **Then** matching companies are suggested, and choosing one opens its page.
2. **Given** a company page, **When** it loads, **Then** it shows a timeline of insider purchases and sales (date, insider role, shares, value), its provisional events marked, and summary counts.
3. **Given** a company still listed, **When** its page loads, **Then** an embeddable price-chart widget appears, licensed for display. No raw price table from the prototype's own data is shown.
4. **Given** a company that is no longer listed, **When** its page loads, **Then** the insider history still appears, with a note that price data is unavailable in the prototype.

---

### User Story 4 - Explain the method and run the demo smoothly (Priority: P4)

The researcher can rebuild everything with one command, start the dashboard with another, and follow a short demo script. A Method & limitations page explains the data sources, the pilot-sample and survivorship caveats, and what the full study will add.

**Why this priority**: a prototype that is hard to start or easy to misread hurts the presentation. Teachers will ask about limitations.

**Independent Test**: on a clean checkout with feature 001's data, run the build command and then the serve command, and follow the demo script end to end in under 5 minutes.

**Acceptance Scenarios**:

1. **Given** feature 001's data on disk, **When** the researcher runs the build command, **Then** prices are downloaded (cached and resumable), and the analysis, model and dashboard data are produced, with a summary of coverage and timing.
2. **Given** a completed build, **When** the build command runs again, **Then** it reuses cached prices and finishes quickly.
3. **Given** the serve command, **When** the researcher opens the local address, **Then** every page works with no further setup.
4. **Given** the Method & limitations page, **When** it is read, **Then** it covers the data sources, the pilot-sample rule and why it exists, survivorship bias, the simple cost model, the provisional (pilot) event rules, and what the full study adds (delisted stocks, production rules, 2012–2026, holdout, more features).
5. **Given** the demo script, **When** the researcher follows it, **Then** it visits every page in a logical order within 5 minutes, with talking points.

---

### Edge Cases

- **A pilot company still listed whose Yahoo history starts after its event date** (for example, after a ticker change): the event is unpriced and counted in the coverage figure.
- **A company that changed tickers:** priced under its current ticker if Yahoo's history covers the event window. Otherwise unpriced.
- **The 252-session window runs past the end of available prices:** shorter horizons are still used and the longer ones are left empty for that event. Pilot events end by 2011, so this is rare.
- **Floors:** an event failing the price or liquidity floor on the last session before T is excluded from returns and counted in the funnel.
- **Missing features for a recent event** (for example, a stock with less than a year of trading for momentum): it is scored with the missing values handled, and the screener flags it as "partial data".
- **Yahoo rate limits or outages during the build:** downloads are retried and resumed, and companies that still fail are listed and counted as unpriced.
- **Ticker lookup finds nothing:** a clear "no match" message with suggestions.
- **The price widget cannot load (no internet in the classroom):** the rest of the company page still works, and a note replaces the chart.
- **Overlapping events** (the same month, or the same company within a window): the uncertainty bands account for this rather than treating events as independent.
- **Pilot coverage turns out low** (for example, below 30% of pilot events priced): the dashboard states the coverage prominently next to the results.

## Requirements *(mandatory)*

### Functional Requirements

**Data and pilot rules**

- **FR-001**: The prototype MUST take insider events and clean filings from feature 001's provisional outputs, and company identities and current tickers from the latest SEC ticker snapshot.
- **FR-002**: Prices MUST come from Yahoo Finance for companies still listed today, plus the SPY and IWM benchmarks. Downloads MUST be cached on disk and resumable, and failures listed.
- **FR-003**: Post-event returns, labels and any other outcomes MUST be computed only for events with signal dates from 2006-01-01 to 2011-12-31.
- **FR-004**: Events dated 2012-01-01 or later MAY be scored by the model, using only inputs available on or before their signal date. No outcome for them may be computed, stored or shown.
- **FR-005**: Every page, chart and table that shows returns or model performance MUST display the label "Pilot sample (2006–2011), survivors only — prototype, not research results".
- **FR-006**: All prototype code MUST live in `mvp/`, and its generated data in a git-ignored folder. Production code MUST NOT import prototype code.

**Analysis**

- **FR-007**: Entry MUST be at the open of the first trading session after the signal date T. Abnormal returns MUST be measured against IWM (primary) and SPY, from 20 sessions before entry to 252 after.
- **FR-008**: Tradability floors MUST use as-traded prices rebuilt from split history: close ≥ $2 and 20-session average dollar volume ≥ $100,000 on the last session on or before T. Excluded events are counted.
- **FR-009**: A round-trip trading cost per event MUST be estimated from daily high and low prices around T, and every headline figure MUST be shown gross and net of it.
- **FR-010**: The event study MUST report, for clusters and solo CEO/CFO buys at horizons of 5, 21, 63, 126 and 252 sessions: event count, mean, median, share positive, and uncertainty bands that account for events overlapping in time.

**Model**

- **FR-011**: The outcome to predict MUST be whether the 63-session abnormal return against IWM, net of cost, is above zero.
- **FR-012**: Features MUST be computed as of T. From the insider filings: number of insiders, total value, largest buyer's share, CEO/CFO, director and 10%-owner counts, holdings increase, new positions, filing lag, prior insider selling and repeat buying. From prices: average dollar volume, purchase value relative to dollar volume, prior one-month return, momentum, distance from the 52-week high, volatility and estimated spread.
- **FR-013**: Three models MUST be trained on 2006–2010 pilot events and evaluated on 2011 pilot events: a regularised logistic regression, a gradient-boosted model, and a market-only baseline that sees the price features only. Results MUST report ranking quality, probability accuracy, calibration, and the top-fifth average net return.
- **FR-014**: The selected model, the better of the two on 2011 by probability accuracy, MUST score every event with a signal date from 2026-07-01 to 2026-09-30.

**Dashboard**

- **FR-015**: The dashboard MUST have six pages: Overview, Latest clusters (screener), Company lookup, Findings, Model, and Method & limitations. It MUST have consistent navigation and a visible project identity.
- **FR-016**: The screener MUST support filtering (group, score range, minimum value) and sorting by any column, and flag events with partial feature data.
- **FR-017**: The company lookup MUST support search by ticker or name fragment, show the insider purchase and sale timeline with roles, mark events, and embed a licensed price-chart widget for listed companies.
- **FR-018**: The dashboard MUST show only derived results (averages, distributions, scores, aggregate paths), never tables of raw Yahoo prices.
- **FR-019**: The design MUST be professional and readable on a laptop and a classroom projector (1280×720 and up), with light and dark themes and no horizontal scrolling at 1280 pixels wide.
- **FR-020**: Pilot price coverage MUST appear on the Overview and Findings pages: priced pilot events ÷ all pilot events, by group.

**Operation and checks**

- **FR-021**: One command MUST build all prototype data: prices, returns, event study, model, scores, dashboard data. A second command MUST start the dashboard locally.
- **FR-022**: Automated checks MUST verify that:
  - no outcome exists for any event dated 2012 or later;
  - production code does not import prototype code;
  - every return or model view carries the pilot label.
- **FR-023**: A demo script MUST guide a 5-minute walkthrough of all six pages, with talking points.

### Key Entities

- **Pilot event**: a provisional cluster or solo CEO/CFO event with a signal date in 2006–2011, and whether it was priced and passed the floors.
- **Recent event**: a provisional event dated July–September 2026, with its features and model score, and no outcome.
- **Event return path**: for a priced pilot event, the abnormal return against IWM and SPY at each session from −20 to +252, plus the estimated cost.
- **Event-study summary**: per group and horizon, the count, mean, median, share positive and uncertainty band, gross and net.
- **Model result**: per model, the 2011 ranking quality, probability accuracy, calibration points, top-fifth net return and top drivers.
- **Company profile**: one company's identity, current ticker (if listed), insider transactions over time and events.
- **Coverage and funnel figures**: counts from quarters down to priced pilot events, per group.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The dashboard is demo-ready by 26 October 2026. From feature 001's data, two commands (build, then serve) produce a working dashboard.
- **SC-002**: 100% of pages, charts and tables that show returns or model performance display the pilot label, confirmed by an automated check over every page.
- **SC-003**: The automated checks find zero outcomes for events dated 2012 or later, and zero imports of prototype code by production code.
- **SC-004**: After the build, every page loads in under 2 seconds on the researcher's laptop.
- **SC-005**: Pilot coverage (priced pilot events ÷ pilot events) is shown by group. If it is below 30%, a prominent coverage warning appears next to the results.
- **SC-006**: All six pages are legible and free of horizontal scrolling at 1280×720, in both light and dark themes.
- **SC-007**: The researcher completes the demo script across all six pages in 5 minutes or less in a rehearsal.
- **SC-008**: With prices already cached, a rebuild finishes in under 5 minutes. The first build, including all price downloads, finishes in under 60 minutes.

## Assumptions

- **Event rules.** The pilot uses feature 001's provisional events and their simplified rules. The production rules come with feature 002 and are not needed for a prototype.
- **"Still listed".** A company counts as still listed if its CIK is in the latest SEC ticker snapshot. Its current ticker is used for Yahoo, which usually holds a renamed company's history under the current ticker.
- **Benchmark.** IWM, small-cap US stocks, is the primary benchmark because most insider-cluster stocks are small. SPY is shown for comparison. Industry-adjusted returns are left for the full study.
- **Simple cost.** The cost is a high-low spread estimate per event, round trip. The full study adds price impact.
- **Uncertainty bands.** Bands come from resampling calendar months of events, so events in the same month move together.
- **Features left out.** Market capitalisation and the company-financial features (F16, F25–F29) are left out: XBRL share counts are incomplete before mid-2011. Dollar volume stands in for size, and sector is left out.
- **Latest quarter.** "Latest real clusters" means events with signal dates from 2026-07-01 to 2026-09-30, the last quarter in the SEC data (244 events).
- **Local only.** The dashboard runs on the researcher's machine for a private class demo, with no login and no public deployment. The price widget needs an internet connection during the demo.
- **Provider terms.** Yahoo's terms allow personal use. Showing derived results and a licensed widget in a private demo stays within them.
- **Out of scope** (later features): the production insider rules (feature 002), delisted-stock prices (Tiingo), the 2012–2026 study, the holdout, industry adjustment, public deployment.
