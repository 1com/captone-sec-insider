# Feature Specification: Daily data refresh

**Feature Branch**: `001-daily-data-refresh`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Fresh, complete and daily-updated data for the v2 platform. Today the data stops on different days: the prices used stop on 23 October 2026 because the trading calendar comes from an old SPY download (other price files reach 28 October and are dropped); Form 4 insider filings stop on 30 September because the SEC's insider data sets are quarterly; SEC filings, financial facts and the list of listed companies stop on 22 October. Yahoo has prices for only 6,285 of the 7,291 listed companies (just 28 of the 956 price-only stocks such as foreign ADRs); 294 listed companies have prices from no source; 78 more have only Tiingo prices that fail the identity check because they were renamed after they stopped filing with the SEC. And nothing updates: v2 has no download commands yet (v1's downloaders were not ported). Wanted: (1) a download command per source — SEC filing histories and financial facts, the SEC's list of listed companies (a snapshot each day), Form 4 filings as they are filed (not only the quarterly data sets), Yahoo daily prices for every listed ticker plus SPY and IWM, Tiingo while the paid plan lasts (until 26 November 2026), FRED series, the Cboe VIX and FINRA short volume — each storing the files unchanged in data/raw with a manifest line, within each provider's rate limits; (2) a one-off full refresh now, after which every table reaches the last completed trading session, Yahoo covers the listed companies it has data for, and the renamed companies get prices; (3) a daily update command that fetches only what is new, extends every layer, recomputes each company's latest values and republishes the serving database and the private export, giving exactly the same result as a full rebuild for that day, and changing nothing when rerun the same day; (4) a schedule that runs the update every weekday evening on this machine, with a log of each run that says what was fetched, what changed and what failed."

## Context

The platform answers questions about any US-traded stock, so its value depends on data that is
both complete and current. As of 29 October 2026 neither holds:

| Data | Last day held | Why |
|---|---|---|
| Prices used for every company | 23 Oct | the trading calendar comes from an index download made that day; later prices are dropped |
| Insider (Form 4) filings | 30 Sep | only the SEC's quarterly data sets were downloaded |
| SEC filings, financial values, list of listed companies | 22 Oct | one-off downloads |
| Short volume | 23 Oct | one-off download |

Coverage of the 7,291 listed companies (funds, ETFs and blank-check companies are out of scope by
design) has three gaps: one of the two price sources (Yahoo) holds prices for only 6,285 of them,
because only v1's companies were asked; 373 have no prices at all (294 because no source was asked
or had data, 78 because their only series failed the identity check, mostly after a rename, 1
because it listed after the calendar's end);
and 617 of the 636 priced "price-only" stocks (foreign companies that file nothing periodic with
the SEC, such as Hitachi and Deutsche Telekom) keep only their prices since September 2025,
although their series reach back a median of eight years (476 of them before 2025), because the
only evidence tying them to their ticker is the SEC's October list.

## User Scenarios & Testing *(mandatory)*

The user is the researcher who runs the platform on their own machine, and through the product,
anyone reading a stock page.

### User Story 1 - Every dataset reaches the latest trading day (Priority: P1)

The researcher runs one refresh and afterwards every dataset — prices, the trading calendar,
filings, financial values, insider filings, short volume, market and economic series — holds data
up to the last day its provider has published, and every company's latest values (price,
volatility, size, insider activity) are as of the last completed trading session.

**Why this priority**: every page, screener and forecast reads the latest values; stale data makes
everything else wrong, and the gap grows each day.

**Independent Test**: run the refresh on a weekday after the US close; check that the latest date
of each dataset equals the provider's latest published day, and that named companies show that
session's closing price.

**Acceptance Scenarios**:

1. **Given** prices stop on 23 October, **When** the refresh completes after the close of a later
   session, **Then** the trading calendar and the prices of every listed company that traded reach
   that session.
2. **Given** insider filings stop on 30 September, **When** the refresh completes, **Then** every
   Form 4 filed up to the last business day appears in the insider tracker.
3. **Given** one provider is unreachable, **When** the refresh runs, **Then** the other datasets
   still refresh, the unreachable one keeps its previous data, and the report names it with the
   date it stops on.

---

### User Story 2 - Prices for every listed company a source has (Priority: P1)

Both price sources are asked about every ticker in the SEC's current list. A listed company is
priced whenever either source has data for its current ticker, including companies renamed since
they last filed with the SEC, and its history reaches back as far as that ticker's current listing
(to 2010 at most), not only to last year. A coverage report lists every listed company without
prices and the reason.

**Why this priority**: the platform promises coverage of whatever trades (constitution II); the
price-only level exists so that large foreign companies are not dropped (V2-11), and volatility
needs a long price history.

**Independent Test**: after the downloads, the coverage report shows how many listed companies are
priced by each source, lists the unpriced ones with reasons, and named cases are priced with full
history (Hitachi from 2012 and Deutsche Telekom from 2010; Standard Life (now abrdn) and NGK Spark
Plug (now Niterra), which were renamed).

**Acceptance Scenarios**:

1. **Given** 7,291 listed companies, **When** the downloads complete, **Then** every ticker in the
   SEC's current list has been asked of each source, and each listed company without prices
   appears in the coverage report with its reason (no source has the ticker; the series was
   rejected and why; listed too recently).
2. **Given** a company renamed after its last SEC filing whose listed ticker has prices, **When**
   prices are chosen, **Then** it is priced from that ticker.
3. **Given** a price-only stock whose ticker has traded since 2010 without another company using it,
   **When** prices are chosen, **Then** its history starts in 2010.
4. **Given** a symbol another company used before, **When** the current owner's history is chosen,
   **Then** it starts after the other company's last use, never earlier.

---

### User Story 3 - A daily update that matches a full rebuild (Priority: P1)

After each trading day, one update fetches only what is new from every source, extends every
layer, recomputes each company's latest values and republishes the product's database and the
private export. The result is exactly what a full rebuild from the same downloaded files would give,
and running it again the same day changes nothing.

**Why this priority**: the platform is meant to be live (decision D64); without a correct
incremental update the data is stale by the next day, and an update that drifts from a full rebuild
would make every forecast's track record untrustworthy (constitution V).

**Independent Test**: build up to day D−1, run the update for D, run a full rebuild from the same
downloaded files, and compare every published table; then rerun the update and confirm nothing
changed.

**Acceptance Scenarios**:

1. **Given** data through D−1, **When** the update runs after D's close, **Then** D's prices,
   filings and insider filings appear and each company's latest values are as of D.
2. **Given** the update already ran for D, **When** it runs again on D, **Then** no table changes
   and the log says there was nothing new.
3. **Given** the update ran for D, **When** a full rebuild runs from the same downloaded files,
   **Then** every published table is identical.
4. **Given** the machine was off for several days, **When** the update next runs, **Then** it
   catches up every missed day in order.
5. **Given** a company split its shares or paid a dividend on D, **When** the update runs, **Then**
   its price history is corrected so that returns before and after D stay right.

---

### User Story 4 - Insider trades the day after they are filed (Priority: P2)

Form 4 filings are collected every day from the SEC's filing system rather than waiting for the
quarterly data sets, so an insider purchase or sale appears in the tracker the evening after it is
filed. When the quarterly data set for that period is later published, each filing is kept once and
any difference between the two versions is reported.

**Why this priority**: the insider tracker is a Must feature of the product, and a tracker that is
up to three months late shows history, not activity. It ranks below the price stories because
prices feed every page and forecast.

**Independent Test**: pick filings made on a recent day; after that evening's update they appear in
the tracker with the right person, role, value and the day they became public.

**Acceptance Scenarios**:

1. **Given** a Form 4 filed on D, **When** the update runs that evening or later, **Then** the trade
   appears in the insider tracker, usable from the first session after its acceptance (or D itself
   when accepted before the close).
2. **Given** filings collected daily for a quarter, **When** the SEC publishes that quarter's data
   set, **Then** each filing appears once and the differences between the two versions are listed.

---

### User Story 5 - Runs by itself every weekday, with a log (Priority: P3)

The update runs automatically every weekday evening on the researcher's machine. Each run leaves a
record of what it fetched, what changed and what failed, and the researcher can see the recent runs
and how current each dataset is with one command.

**Why this priority**: until it runs on its own, the researcher must remember to start it; the
stories above deliver value when started by hand.

**Independent Test**: install the schedule, leave the machine on over two weekday evenings, and
read the two run records and the freshness overview.

**Acceptance Scenarios**:

1. **Given** the schedule is installed and the machine is on, **When** a weekday evening comes,
   **Then** the update runs without anyone starting it.
2. **Given** a run fails or a source is unreachable, **When** the researcher opens the run history,
   **Then** it shows which source failed and why, and the next run retries it.
3. **Given** an update is running, **When** another one starts, **Then** the second stops at once
   with a clear message.

---

### Edge Cases

- **US market holiday or weekend**: no new session; the run completes, records "no session", and
  still collects any filings published that day.
- **Data published after the run**: short volume (published around midnight Berlin time) and SEC
  filings accepted late in the US evening arrive after an evening run; the next run collects them.
- **Provider down, slow or rate-limiting**: retried with growing waits; if it still fails the run is
  recorded as partial, other sources complete, and the next run retries.
- **Run interrupted** (power cut, machine sleep): the next run resumes; the product's database is
  never left half-written.
- **Tiingo plan ends (26 November 2026)**: Tiingo is skipped from then on with a note; stored Tiingo
  files are kept; companies priced only from Tiingo are flagged in the coverage report as no longer
  updating.
- **New listing, ticker change, delisting** (seen in the daily SEC list): a new company gets its
  history; a renamed ticker continues the same company; a delisted company keeps its history and
  stops.
- **Splits and dividends**: adjusted histories change after the event; the stored history is
  corrected, as-traded prices stay as traded.
- **A filing amended later** (4/A, 10-K/A): handled by the existing rules for amendments; the
  original keeps the day it became public.
- **Disk nearly full**: the run stops before writing with a clear message instead of failing midway.
- **Clock changes** (Europe and the US switch daylight saving on different dates): runs are set in
  local time; nothing is lost because each run collects everything published since the last one.

## Requirements *(mandatory)*

### Functional Requirements

**Downloads (one command per source)**

- **FR-001**: The researcher MUST be able to download, with one command per source: the SEC's
  filing histories, the SEC's financial values, the SEC's list of listed companies, Form 4 filings
  by filing day, daily prices from Yahoo, daily prices from Tiingo, the FRED economic series, the
  Cboe VIX and FINRA short volume.
- **FR-002**: Every download MUST be stored exactly as received, with a record of its source, URL
  (without secrets), time, size and checksum; compressing a file for storage is allowed when
  decompressing returns the bytes received.
- **FR-003**: Downloads MUST respect each provider's limits and terms: at most 10 requests a second
  to the SEC with a real contact in each request; the paced batches used for Yahoo; Tiingo's plan
  limits; FRED's, Cboe's and FINRA's terms.
- **FR-004**: Tiingo MUST be asked only while the paid plan lasts (until 26 November 2026); stored
  Tiingo files MUST be kept afterwards.
- **FR-005**: Rerunning a download MUST skip what is already stored and current, and resume an
  interrupted download without duplicating files.
- **FR-006**: Secrets (API keys, the contact address) MUST never appear in stored files' records,
  logs or anything committed.
- **FR-007**: The SEC's list of listed companies MUST be kept as one snapshot per day, so new
  listings, ticker changes and delistings are dated.

**Completeness**

- **FR-008**: Yahoo MUST be asked for the full history (from 2010) of every ticker in the SEC's
  current list that it has not yet been asked for, plus the reference index funds (SPY, IWM).
- **FR-009**: The trading calendar MUST always reach the last completed US trading session.
- **FR-010**: A listed company MUST be priced from its current ticker (from the SEC's list) when
  either source has data for it, without requiring the source's company name to match the SEC's,
  so that companies renamed since their last SEC filing are priced.
- **FR-011**: A listed company's price history MUST reach back to the start of its current
  ticker's listing (2010 at most) and never before the last day another company used that symbol.
- **FR-012**: Every refresh and update MUST produce a coverage report: listed companies priced by
  each source, unpriced listed companies with the reason, and companies priced only from Tiingo
  (which stop updating when the plan ends).

**Daily update**

- **FR-013**: One update command MUST fetch everything published since the last successful run from
  every source, then extend every layer through to the product's database and the private export.
- **FR-014**: The update MUST catch up every day missed since the last successful run, in order.
- **FR-015**: The update MUST give the same tables as a full rebuild from the same downloaded files.
- **FR-016**: Rerunning the update when nothing new was published MUST change no table.
- **FR-017**: Every new fact MUST record the day it became public, and nothing published for day D
  may use a fact that became public after D's close.
- **FR-018**: A failing source MUST NOT stop the others; its datasets keep their previous data, the
  run is recorded as partial, and the next run retries it.
- **FR-019**: When a split or dividend changes a company's adjusted price history, the stored
  history MUST be corrected so returns stay right.
- **FR-020**: Form 4 filings collected daily MUST be reconciled with the SEC's quarterly data set
  when it is published: each filing counted once, differences reported.
- **FR-021**: The product's database and the export MUST be replaced in one step, so a reader never
  sees a partly updated version.
- **FR-022**: The update MUST NOT compute or change any risk label: development answers stay as
  built and the risk holdout stays sealed.

**Schedule and log**

- **FR-023**: The update MUST run automatically every weekday evening on the researcher's machine,
  at a configurable time after the US close.
- **FR-024**: Each run MUST leave a record: start and end time; per source, what was fetched (days,
  files, size); per table, rows added, changed and removed; each dataset's latest date; and every
  failure with its reason.
- **FR-025**: The researcher MUST be able to see the recent runs and each dataset's latest date with
  one command.
- **FR-026**: Only one update MAY run at a time; a second start MUST stop at once with a message.

### Key Entities

- **Source**: a data provider and what it publishes (prices, filings, financial values, insider
  filings, short volume, economic series), how often, its limits, and for Tiingo its paid window.
- **Stored download**: a file exactly as received, with its record (source, key, URL without
  secrets, time, size, checksum).
- **Ticker listing**: a company's ticker over a period, dated by the SEC's daily lists, its Form 4
  filings and the price sources; the basis for how far back a company's prices reach.
- **Update run**: one execution of the update: when, what each source gave, what each table
  gained or lost, each dataset's latest date, failures; complete or partial.
- **Coverage report**: per run, the listed companies by price source, the unpriced ones with
  reasons, and the companies that depend on Tiingo alone.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the one-off refresh, every dataset's latest date equals the last day its provider
  has published, and the prices used reach the last completed trading session (not 23 October).
- **SC-002**: After the refresh, every ticker in the SEC's current list has been asked of Yahoo, and
  the listed companies without prices fall from 373 to only those no source has data for, each
  listed with its reason.
- **SC-003**: After the refresh, price-only stocks keep the history their sources hold: at least 450
  of today's 636 have prices from before 2025 (today: 19), Hitachi's from April 2012 or earlier and
  Deutsche Telekom's from June 2010 or earlier.
- **SC-004**: A typical weekday update finishes within 30 minutes on this machine.
- **SC-005**: On a test day, every published table after the update is identical to the result of a
  full rebuild from the same downloaded files.
- **SC-006**: A second update on the same day reports zero rows added, changed or removed.
- **SC-007**: An insider purchase or sale appears in the tracker after the first update following its
  filing, instead of up to three months later.
- **SC-008**: Over two weeks of scheduled running, every weekday has a run record, and every day
  missed while the machine was off is caught up by the next run.
- **SC-009**: No run exceeds a provider's request limit, and no Tiingo download happens outside the
  paid plan.

## Assumptions

- The platform runs on the researcher's machine (Berlin time); there is no server. Runs happen only
  while the machine is on; missed days are caught up.
- The default run time is 23:00 Berlin time on weekdays, after the US close (22:00 Berlin time for
  most of the year); providers that publish later in the night are collected by the next run.
- The download behaviour starts from v1's downloaders (sources, limits, file layout), which are
  ported, not redesigned.
- Yahoo is the main daily price source after 26 November 2026; Tiingo history stays stored and used,
  and what happens to it when the plan ends is the researcher's decision (constitution VI).
- Financial values and filing histories are refreshed for the companies that filed that day, not by
  re-downloading the SEC's full files every day.
- Funds, ETFs and blank-check companies stay out of scope (docs/spec.md).
- Forecasts and their track record are not part of this feature: the risk models come in a later
  feature, and the update will add their daily scores once they exist.
- The required keys (the SEC contact, the FRED key, the Tiingo key) are already in the
  researcher's private settings file.
