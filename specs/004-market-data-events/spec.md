# Feature Specification: Market Data, Final Events, Delistings, Company Financials and Trading Costs

**Feature Branch**: `004-market-data-events`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "Feature 004 — Market data, final events, delistings, company financials and trading costs (docs/initialplan.md v2.2 Steps 7–10; §5 data sources, §5.1–5.2, §6.2 gates G7 and G8, §6.4 events, §6.5 tradability floors, §6.7 delistings and unpriced events, §6.8 trading-cost model; constitution v3.1.0 Principles I, II, V, VI; decisions D39, D40, D45, D46, D49; docs/planning/05 epics E2 and E3). Builds on feature 002's warehouse (core.filing, core.clean_purchase, evt.prelim_event, core.symbol_map, core.filing_header). Deliver: (1) prices: Yahoo daily prices for listed event companies plus SPY and IWM, with as-traded (unadjusted) prices rebuilt from split histories, every raw response kept under data/raw with a manifest line; Tiingo daily prices for delisted event companies during the one paid month (starts Thursday 29 October 2026), stored only while the plan is active and every file tagged for deletion; (2) reference data: Kenneth French daily factors (five factors, momentum, short-term reversal), 49- and 12-industry portfolio returns, SIC-to-industry definitions, NYSE market-cap breakpoints; FINRA tick-size pilot lists; (3) company data: SEC company facts (shares outstanding and the five F26–F29 items, first-filed values only) and SEC submissions (10-Q/10-K dates, forms 25 and 15, merger filings) for event companies; (4) final events: price check G8, issuer-type rule G7 with D45 and its current-SIC fallback, tradability floors (unadjusted price at least $2, ADDV20 at least $100k, 18 of 20 active sessions, tick floor), cooldown of 63 sessions, entry at the open of T+1, into evt.event; (5) delistings: classify every price series that ends early as acquired, performance-related or unknown and assign delisting returns, with worst- and best-case bounds for unpriced events; (6) costs: spread estimates (Abdi–Ranaldo) and the §6.8 cost model per event. Quality gates: price tests; price coverage of A and B1 events at least 90%, reported by year and delisting status; G8 passes for at least 95%; a 30-event golden set matches EDGAR (researcher hand check); a 30-company delisting hand check; market caps match known examples. Heavy steps run under the 5 GB memory ceiling with DuckDB capped at 3 GB. Out of scope: labels, features, the event study and ML (later features), and computing any post-event return before prereg-v1. Researcher checkpoints: the Tiingo subscription, the golden-set and delisting audits, and the D45 check result."

## Context

Feature 002 produced the clean insider purchases, the preliminary events and the list of companies to price, with each company's intended price source (the symbol map: 8,361 of 8,527 event companies mapped, 3,824 to Yahoo and 4,537 to Tiingo). This feature adds the market side of the study: daily prices, including companies that later disappeared, the reference series the labels will need, company size and financials as they were first reported, the final list of tradable events, how each early-ending price series ended, and the cost of trading each event.

It is the last feature before the pre-registration lock (plan Step 10a, 4 November). It computes **no post-event returns**: labels, features and every result come after the lock (constitution Principle III). Prices after T are stored, because later features need them, but nothing here measures performance after an event.

The actor throughout is **the researcher**. **The reviewers** (the course instructors) rely on the coverage reports, the audits and the tests to trust the result.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prices for every event company, including those that later disappeared (Priority: P1)

The researcher runs the price commands and gets daily prices for every event company: from Yahoo for companies listed today, and from Tiingo for companies that delisted, during the one paid month. Every price-level rule can use the price as it actually traded on the day, and every return can use prices adjusted for splits and dividends. A coverage report shows, by year and by delisting status, how many events have the prices they need.

**Why this priority**: without delisted-stock prices the study describes survivors only (plan §5.1), and the Tiingo month is a hard window: it starts on 29 October and its data must be deleted when it ends. Everything else in this feature, and every later feature, reads these prices.

**Independent Test**: fetch a small set of known companies (a listed stock with a reverse split, a stock delisted in bankruptcy under a `Q` ticker, SPY, IWM), load them, and check as-traded prices against known historical prices; then run the full pull and the coverage report.

**Acceptance Scenarios**:

1. **Given** a listed company that did a 1-for-10 reverse split, **When** its prices are loaded, **Then** its as-traded close before the split is ten times smaller than the split-adjusted close, and its dollar volume is the same in both.
2. **Given** a delisted company whose final ticker carries a `Q` suffix, **When** its Tiingo prices are fetched during the paid month, **Then** its history is stored under the company's own identifier, not the ticker, and every stored Tiingo file and table appears in the deletion register.
3. **Given** a company listed today for which Yahoo has no history, or a history that starts after the company's first event, **When** the price pull runs during the paid month, **Then** its prices come from Tiingo instead, and the substitution is recorded.
4. **Given** a download that fails part-way, **When** the command is run again, **Then** it resumes, and responses already stored are not fetched again.
5. **Given** the loaded prices, **When** the coverage report runs, **Then** it shows, for A and B1 events per year and per delisting status, the share with prices on the sessions from T−19 to T+1.

---

### User Story 2 - Final events that could really have been traded (Priority: P2)

The researcher gets the final A, B1 and B2 events: purchases whose reported price matches the market that day, at companies that are not funds or blank-check shells, in stocks that traded actively enough above $2, with the 63-session cooldown, and with the entry session after each signal date. Events at companies that cannot be priced are counted, not silently dropped. A golden set of 30 events lets the researcher check the result against EDGAR by hand.

**Why this priority**: these are the events every label, feature, test and product page will use. Their rules are fixed in the plan (§6.2, §6.4, §6.5) and must be applied exactly, using only information available at T.

**Independent Test**: on synthetic purchases and prices covering each rule (a typo price, a fund, a sub-$2 stock, a thin stock, a cooldown overlap, a signal filed on a market holiday), confirm the expected events; then run on the real data and check the golden set.

**Acceptance Scenarios**:

1. **Given** a clean purchase reported at $200 a share in a stock that traded between $1.80 and $2.10 that day, **When** G8 runs, **Then** the purchase is excluded and counted in the G8 pass rate.
2. **Given** a cluster at a company whose signal-filing header gives SIC 6726, or no SIC code, **When** final events are detected, **Then** the event is excluded by G7 (or, if the D45 check has triggered the fallback, the company's current SIC code is used for the no-SIC case).
3. **Given** an event whose stock closed at $1.95 on the last session on or before T, **When** the floors run, **Then** it fails the price floor, using the as-traded price, even though its later split-adjusted price exceeds $2.
4. **Given** an event at a stock that traded on only 15 of the last 20 sessions, or whose 20-session average dollar volume was $80,000, **When** the floors run, **Then** it fails the activity or liquidity floor, using prices up to the last session on or before T only.
5. **Given** two qualifying clusters at one company 40 sessions apart, **When** the cooldown applies, **Then** only the first becomes an event, and an event that failed a floor starts no cooldown.
6. **Given** a signal filing dated on a Good Friday, **When** the event is recorded, **Then** rules "at T" use the last trading session before it, and the entry session is the next trading session after T.
7. **Given** a company that cannot be priced, **When** final events are detected, **Then** its events are recorded as unpriced and counted by year and group.
8. **Given** the golden-set command, **When** the researcher runs it, **Then** it writes 30 random final events with EDGAR links and blank verdict columns.

---

### User Story 3 - How each early-ending price series ended (Priority: P3)

For every event company whose prices stop before the end of the data, the researcher sees whether it was acquired, delisted for performance reasons, or ended for an unknown reason, based on its SEC filings, and the delisting return the labels will apply. A 30-company sheet lets the researcher check the classification by hand.

**Why this priority**: delisting returns decide the outcome of the events most affected by survivorship bias. Their rules are pre-registered (plan §6.7), and the classification must rest on evidence, not on the absence of data (constitution Principle II).

**Independent Test**: on synthetic filing histories (a merger proxy before the last trade, a Form 25 with no merger filing, no filing at all, a company still filing 10-Qs after its last price), confirm the class and delisting return of each.

**Acceptance Scenarios**:

1. **Given** a company with a merger proxy filed 5 months before its last trade, **When** delistings are classified, **Then** it is "acquired" with a 0% delisting return.
2. **Given** a Nasdaq company with a Form 25 and no merger filing in the 12 months before its last trade, **When** delistings are classified, **Then** it is "performance-related" with a −55% delisting return.
3. **Given** a company whose prices end with no delisting, deregistration or merger filing, **When** delistings are classified, **Then** it is "unknown", takes the performance-related return in the main run, and carries the 0% and −100% bounds.
4. **Given** a company still filing 10-Qs after its last price, **When** delistings are classified, **Then** it is flagged as a likely ticker change for re-mapping, not as a delisting.
5. **Given** the delisting audit command, **When** the researcher runs it, **Then** it writes 30 companies across the three classes with EDGAR links and blank verdict columns.

---

### User Story 4 - Company size and financials as first reported (Priority: P4)

For every event company, the researcher gets shares outstanding and five balance-sheet and income items, each with the date it was first filed, so that market capitalisation and the financial features use only what the market knew at T.

**Why this priority**: market capitalisation feeds features F16 and F25–F29 and a robustness breakdown. It is needed before the features (Step 12) but not before the price pull.

**Independent Test**: load company facts for a handful of known companies and compare their market capitalisation at known dates with published figures.

**Acceptance Scenarios**:

1. **Given** a company that later restated its equity, **When** its facts are loaded, **Then** only the value as first filed is kept for each period, with its filing date.
2. **Given** an event at T, **When** market capitalisation is computed, **Then** it uses the as-traded close at T and the latest shares-outstanding value first filed on or before T, and is missing where no such value exists.
3. **Given** a company with no equity tag but an equity-including-non-controlling-interests tag, **When** its facts are loaded, **Then** the fallback tag is used and recorded as such.

---

### User Story 5 - The cost of trading each event (Priority: P5)

For every final event, the researcher gets the estimated round-trip cost of a $10,000 position: the bid–ask spread estimated from daily prices, floored at one price tick, plus the price impact of the order.

**Why this priority**: every headline number is reported net of cost (constitution Principle IV), and the cost is part of the primary label. The estimate is needed before labels (Step 11).

**Independent Test**: on synthetic price paths with a known spread and volatility, confirm the estimator recovers them within tolerance; check the one-tick floor at $0.01 and, for tick-size pilot stocks during the pilot, at $0.05.

**Acceptance Scenarios**:

1. **Given** a $2 stock with a two-tick spread, 4% daily volatility and $100,000 average daily dollar volume, **When** its cost is computed, **Then** it is about 3.5% round trip (plan §6.8 illustration).
2. **Given** a stock in the tick-size pilot on a pilot date, **When** its spread is floored, **Then** the floor uses a $0.05 tick.
3. **Given** the development-period events, **When** the cost report runs, **Then** it shows the estimated cost by price bucket, and any jump at a price other than $2 is reported.

---

### User Story 6 - Reference series for benchmarks and industries (Priority: P6)

The researcher gets the daily factor returns, industry portfolio returns, SIC-to-industry definitions and size breakpoints from the Kenneth French data library, stored as received, so that labels and the event study can use them later.

**Why this priority**: they are needed from Step 11 on, but downloading them is quick, free and independent of everything else here.

**Independent Test**: download and load the files, and check that they cover dates through 31 August 2026 and that every SIC code in the signal-filing headers maps to one of the 49 industries or is reported as unmapped.

**Acceptance Scenarios**:

1. **Given** the downloaded files, **When** they are loaded, **Then** daily five-factor, momentum and short-term reversal returns and equal- and value-weighted 49- and 12-industry returns exist for every trading session they cover.
2. **Given** the SIC codes in the signal-filing headers, **When** they are mapped, **Then** each maps to one 49-industry portfolio, or is listed as unmapped.

### Edge Cases

- A ticker reused by a different company: prices are taken only within the date range the symbol map assigns to each company, and G8 catches residual mismatches.
- Yahoo returns a history that starts after the company's first event or stops before its last filing: the company falls back to Tiingo during the paid month.
- A delisted company not found in Tiingo's list: its events are unpriced, counted and covered by the bounds.
- Duplicate or conflicting rows for one symbol and session (a provider correction): one row is kept by a fixed rule, and the conflict is reported.
- Zero-volume sessions and missing highs or lows: they count against the activity floor and are excluded from spread estimates.
- A signal date on a weekend or market holiday, or a filing accepted after the close: rules at T use the last session on or before T; entry is the next session after T.
- Yahoo throttles or breaks mid-run: every response is cached, the pull resumes, and the Tiingo month is not spent on stocks Yahoo can supply.
- The paid month ends before this feature is complete: Tiingo data is deleted on schedule anyway, and the offline rebuild check runs before it ends.
- A company with both a merger filing and a Form 25 in the lookback: merger evidence wins (acquired).
- An event in the holdout (from 2023): its floors, G7 and G8 use only data up to T, exactly as for development events; no outcome is computed.

## Requirements *(mandatory)*

### Functional Requirements

**Prices**

- **FR-001**: The system MUST fetch daily prices for every company with a preliminary event (groups A, B1 and B2), over each ticker's date range in the symbol map, from 1 January 2005 or the start of the provider's history, to the latest available session.
- **FR-002**: For companies mapped to Yahoo, and for SPY and IWM, the system MUST store daily open, high, low, close, adjusted close and volume, together with the split history, and MUST rebuild as-traded (unadjusted) prices by undoing later splits.
- **FR-003**: For companies mapped to Tiingo, and for companies listed today whose Yahoo history is missing or starts after their first event, the system MUST fetch Tiingo's raw and adjusted daily prices during the paid month only, resolving each company's final Tiingo ticker (including `Q` suffixes) from SEC-derived tickers.
- **FR-004**: Every raw response MUST be stored as received in the raw-data area, with one manifest line recording the source, address, time and checksum. Downloads MUST be resumable and MUST respect each provider's limits (SEC at most 10 requests per second; Tiingo's plan limits; polite, cached access to Yahoo).
- **FR-005**: Every stored file and table derived from Tiingo data MUST be listed in a deletion register. A deletion command MUST remove all of them and log the deletion in the plan's decision log (constitution Principle VI).
- **FR-006**: The analysis database MUST hold one price row per company, symbol and session, with the source, as-traded and adjusted prices, volume and split factor. Conflicting duplicates MUST be resolved by a fixed rule and reported.
- **FR-007**: A coverage report MUST give, for A and B1 events before floors, the share with prices on sessions T−19 to T+1, by year and by delisting status, separately for the labelled window (from 2012) and earlier years. A shortfall MUST NOT be fixed by changing the study window.

**Final events**

- **FR-008**: G8 MUST exclude a clean purchase line whose price lies outside the day's as-traded low–high range widened by the registered tolerance (±10%), on the trade date. The pass rate over mapped clean purchases MUST be reported. Purchases at companies that cannot be priced skip G8.
- **FR-009**: Final detection MUST apply the plan's A, B1 and B2 rules (§6.4) to the purchases that pass G8, with entities and roles as of T, as in feature 002.
- **FR-010**: G7 MUST use the SIC code in the signal filing's header: exclude SIC 6770, 6722 and 6726, and companies whose header has no SIC code (D45). If the D45 check finds 3 or more operating companies among its 30, companies without a header SIC MUST instead take their current SIC code (§11 fallback). The choice MUST be a parameter. Signal filings without a stored header MUST be fetched before detection.
- **FR-011**: The tradability floors MUST be evaluated at the last trading session on or before T, using prices up to that session only: as-traded close at least $2, 20-session average daily dollar volume at least $100,000, and volume on at least 18 of the last 20 sessions, all from the parameter file.
- **FR-012**: The cooldown MUST suppress another event in the same group at the same company for 63 trading sessions, and MUST be started only by events that pass G7 and the floors.
- **FR-013**: Each final event MUST record its group, company, signal date T, last session on or before T, entry session (the first session after T), signal filing and acceptance time, member purchases, G7 result, floor values and results, and whether it is priced.
- **FR-014**: Events at companies without prices MUST be recorded as unpriced and counted by year and group, so that the worst- and best-case bounds can be computed later.
- **FR-015**: Rebuilding final events from data dated on or before T MUST give identical events, G8 results and floor decisions at or before T (truncation test, constitution Principle I).
- **FR-016**: A golden-set command MUST write 30 random final events (fixed seed), each with EDGAR links and blank verdict and notes columns, and a summary command MUST report the researcher's agreement.

**Delistings**

- **FR-017**: For every event company whose prices end before the latest session in the data, the system MUST classify the ending from the company's SEC filing history: acquired (a merger proxy, tender offer or merger registration in the 12 months before the last trade), performance-related (an exchange delisting notice or deregistration without merger evidence) or unknown (neither).
- **FR-018**: A company still filing quarterly reports after its last price MUST be flagged as a likely ticker change for re-mapping, not classified as delisted.
- **FR-019**: Each classified company MUST carry the registered delisting return for its class and venue (0% acquired; −30% NYSE or NYSE American; −55% Nasdaq; unknown takes the performance-related return), and the 0% and −100% bounds.
- **FR-020**: A delisting-audit command MUST write 30 companies across the three classes, with EDGAR links and blank verdict and notes columns.

**Company data**

- **FR-021**: For every event company, the system MUST store shares outstanding and the five items behind F26–F29 (equity, total assets, total liabilities, cash, net income), each with one fallback tag (plan §7.2), its period end and the date it was first filed. Only the first-filed value of each period MUST be used.
- **FR-022**: Market capitalisation at T MUST be the as-traded close at the last session on or before T times the latest shares outstanding first filed on or before T, and missing otherwise.
- **FR-023**: For every event company, the system MUST store its filing history (form types and dates), including quarterly and annual reports, delisting notices, deregistrations and merger filings.

**Reference data**

- **FR-024**: The system MUST store and load the Kenneth French data library's daily five factors, momentum and short-term reversal; equal- and value-weighted 49- and 12-industry portfolio returns; the SIC-to-industry definitions; and the NYSE market-cap breakpoints.
- **FR-025**: The system MUST store and load FINRA's Tick Size Pilot lists of stocks quoted in $0.05 increments (October 2016 – September 2018).

**Costs**

- **FR-026**: For every final event, the system MUST estimate the proportional bid–ask spread from daily high, low and close prices (Abdi & Ranaldo, 2017) over the 20 sessions to T, floored at one tick relative to the as-traded price ($0.05 for pilot stocks on pilot dates, else $0.01), with the Corwin & Schultz (2012) estimate as a cross-check.
- **FR-027**: For every final event, the system MUST compute daily return volatility over 63 sessions, the 20-session average daily dollar volume, and the round-trip cost c = S + 2·k·σ·√(Q / ADDV), with Q, k and the windows from the parameter file.
- **FR-028**: A cost report MUST show the estimated cost by price bucket over the development period, and report any jump at a price other than $2.

**Operation and rigour**

- **FR-029**: Each step MUST be one command that rebuilds only its own tables, logs its build, and checks that its inputs exist. Heavy steps MUST stay within the 5 GB memory ceiling, with the analysis database capped at 3 GB.
- **FR-030**: Every threshold MUST come from the parameter file, and any new research rule (including the delisting return for other venues; see Assumptions) MUST be added there before the pre-registration lock.
- **FR-031**: The feature MUST NOT compute post-event returns, labels, features or any statistic of performance after T (constitution Principle III).
- **FR-032**: Rebuilding this feature's tables from the stored raw files MUST work offline and give identical results, and this MUST be checked before the paid month ends (constitution Principle V).

### Key Entities *(include if feature involves data)*

- **Daily price**: one company's trading session from one source: as-traded and adjusted open, high, low and close, volume and split factor.
- **Corporate action**: a split or dividend with its date and ratio, used to rebuild as-traded prices.
- **Deletion register entry**: a stored Tiingo-derived file or table, with when it was created and when it was deleted.
- **Reference series**: a daily factor return, industry portfolio return or size breakpoint, and the SIC-to-industry definitions.
- **Tick-size pilot entry**: a stock quoted in $0.05 increments, with its pilot dates.
- **Company fact**: one company's value for one item and period, as first filed, with the filing date and the tag used.
- **Company filing**: a form filed by a company, with its type and date.
- **Final event**: group, company, signal date T, entry session, member purchases, G7 result, floor values and results, priced or not.
- **Delisting**: a company whose prices end early, with its last session, class, evidence, venue and delisting return.
- **Cost estimate**: one final event's spread, volatility, dollar volume, impact and round-trip cost.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: At least 90% of A and B1 events with signal dates from 1 January 2012, before floors, have prices on sessions T−19 to T+1, reported by year and delisting status.
- **SC-002**: At least 95% of mapped clean purchases pass the G8 price check.
- **SC-003**: All 30 golden-set events match EDGAR, or every difference is explained and fixed.
- **SC-004**: The researcher agrees with at least 90% of the 30 delisting classifications.
- **SC-005**: For 10 well-known companies at chosen dates, market capitalisation is within 5% of published figures.
- **SC-006**: The truncation test passes for final events at 20 random (company, T) pairs.
- **SC-007**: All Tiingo data is fetched within the paid month, every Tiingo-derived item is in the deletion register, and after the deletion command no such item remains.
- **SC-008**: This feature's tables rebuild offline from the stored raw files in under 30 minutes, with identical results, before the paid month ends.
- **SC-009**: No step uses more memory than the 5 GB ceiling.
- **SC-010**: The feature is complete by Tuesday 3 November 2026, so that the pre-registration can be locked on 4 November. The only later step is deleting the Tiingo data when the paid month ends (SC-007).

## Assumptions

- The researcher subscribes to Tiingo Power with auto-renewal off on Thursday 29 October 2026; the free sources (Yahoo, SEC, the French library, FINRA) can be fetched earlier.
- Price histories start on 1 January 2005, so that every event from 2006 has a year of earlier prices for look-back features and floors.
- Final events cover all years from 2006, because cooldowns and history-based features need earlier events; coverage targets apply to the labelled window from 2012.
- The D45 check result is known before final detection; until then G7 applies D45 as adopted, and the fallback is one parameter.
- Delisting returns for venues other than NYSE, NYSE American and Nasdaq (for example OTC), or an unknown venue, take the Nasdaq figure (−55%), the more conservative of the two registered values. The plan does not cover these venues, so this rule is added to the parameter file and the decision log before the lock (FR-030).
- Company facts and filing histories may come from the SEC's bulk archives or per-company requests; the choice is made in the plan.
- Yahoo prices are split-adjusted in open, high, low and close, with dividends removed only in the adjusted close (plan §5); Tiingo supplies raw and adjusted prices directly.
- The product's display of prices and scores, and its licensing, are out of scope (feature for Product v1).
