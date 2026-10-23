# Research: Market Data, Final Events, Delistings, Company Financials and Trading Costs

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-23

Live checks were run on 2026-10-23 against the warehouse built by feature 002, the SEC, Yahoo (through feature 003's findings), Tiingo, the French library and FINRA. Tiingo was queried with the free key **in memory only**, and only column and key names were printed (constitution VI).

## R1. Scope: from 1 July 2011, prices from 1 January 2010

- **Finding**:
  - Signal-filing headers (G7's SIC at T) are fetched only from the labelled-window start (feature 002, `signal_accessions`).
  - No feature uses earlier *final* events. F1–F29 read purchases, sales, filings and prices (plan §7.2); F10 reads earlier clean purchases, not events.
- **Decision**:
  - Final detection starts on **1 July 2011**, a six-month warm-up (about two cooldowns), so cooldowns are settled on 1 January 2012. Warm-up events are stored with `in_labelled_window = false` and never labelled.
  - Price histories start on **1 January 2010**. That covers the warm-up's 20-session floors, the 63-session volatility window and the 252-session look-back (F20, factor betas) of January 2012 events.
  - The price universe is every issuer with a preliminary event from 1 July 2011. Final candidates can only occur at these issuers: G8 only removes purchases, and the first candidate at any issuer always survives the preliminary cooldown.
- **Sizes** (warehouse query, 2026-10-23):

  | Issuers with preliminary events from 2011-07-01 | Count |
  |---|---|
  | Mapped to Yahoo | 3,671 (4,482 tickers, including share classes) |
  | Mapped to Tiingo | 2,783 |
  | Unmatched | 123 |
  | Preliminary events (A / B1 / B2) | 10,939 / 4,804 / 12,786 |
  | Extra headers needed for the warm-up (2011 H2 signal filings) | about 1,239 |

- **Alternatives**: start in 2006, as in feature 002. That needs about 8,000 more headers and older, sparser prices, for events no later step uses.

## R2. Yahoo prices (FR-001, FR-002)

- **Finding** (feature 003, research R2 and run notes):
  - `yfinance 1.7` on Python 3.14 downloads batches of 50 tickers. 1,183 tickers took 2 min 47 s and 214 MB of Parquet.
  - With `auto_adjust=False`:
    - Open, High, Low, Close and Volume are split-adjusted;
    - Adj Close is also dividend-adjusted;
    - Stock Splits gives each split's ratio on its date.
  - Yahoo has no history for delisted stocks: SIVB, FRC and BBBY returned nothing.
- **Decision**:
  - `sentinel fetch-prices --source yahoo` downloads every Yahoo-mapped ticker in the universe, plus SPY and IWM, from 2010-01-01.
  - One Parquet file per ticker, exactly as the library returns it, goes in `data/raw/yahoo/`, with a manifest line. The key is the ticker; the URL field records the library call and its arguments.
  - Reruns skip stored tickers. Failures are retried three times with back-off, then listed in `data/raw/yahoo/failures.csv`.
  - The MVP's cache (`data/mvp/raw/yahoo/`) is **not** reused: the constitution's Prototype Exception keeps MVP outputs out of the study. A fresh pull takes about 10 minutes.
  - **As-traded prices**: for each session, `cum_split_after` = the product of the split ratios dated after that session. Then:
    - as-traded open, high, low and close = Yahoo's value × `cum_split_after`;
    - as-traded volume = Yahoo's volume ÷ `cum_split_after`;
    - dollar volume is unchanged.
    Values are rounded to 6 decimals.
  - **Primary ticker**: an issuer with several current tickers (share classes) gets one primary series. It is the current ticker most often reported in the issuer's own Form 4 filings, with ties broken alphabetically. The others are stored but not used.
- **Dependency**: `yfinance` moves from the `mvp` group to the main dependencies. It is already pinned in `uv.lock` and named in plan §8.3, so it is not a new dependency.

## R3. Tiingo prices and ticker resolution (FR-003, FR-005)

- **Finding**:
  - **Price endpoint**: `GET https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate=…&format=csv`, authenticated with an `Authorization: Token …` header. The CSV columns, checked live, are `date, close, high, low, open, volume, adjClose, adjHigh, adjLow, adjOpen, adjVolume, divCash, splitFactor`. The unprefixed prices are raw (as-traded).
  - **Meta endpoint**: `GET /tiingo/daily/{ticker}` returns `ticker, name, exchangeCode, startDate, endDate, description`. It has no permanent identifier.
  - **Ticker list**: `supported_tickers.zip` has 41,413 US tickers; 1,319 of them have more than one listing interval, because tickers get reused. Of the 2,790 delisted event companies that resolve against the list (all years), **274 (10%) resolve to a reused ticker**.
  - **Limits** (Power plan): 10,000 requests per hour, 100,000 per day, 110,346 unique symbols per month.
- **Decision**:
  - **Paid-month guard.** `ops.tiingo_paid_from` (2026-10-29) and `ops.tiingo_paid_until` (filled in when the researcher subscribes). Every command that writes Tiingo data refuses to run outside that window. The token goes in the header, so it never appears in URLs or the manifest.
  - **List.** On the first paid day, the list is stored once as `data/raw/tiingo/supported_tickers.zip`.
  - **Resolution.** Each Tiingo-mapped issuer's SEC tickers are tried as they are and with a `Q` suffix (feature 002's `match()`). The **resolved ticker** is the matching candidate whose listing interval ends last while still overlapping the issuer's filing span; Tiingo files a delisted company's history under its final ticker. Other matching tickers are kept as fill-ins for sessions before the resolved series starts.
  - **Identity check.** A series is accepted when both hold; otherwise it is rejected with a reason (`dates`, `name`, `no_data`), and the issuer becomes unpriced:
    - its meta `startDate`–`endDate` overlaps the issuer's filings under that ticker;
    - its meta `name` shares a significant word with the SEC name, after dropping words such as *inc*, *corp*, *co*, *ltd*, *holdings*, *group*, *the* and *class*.
  - **Fallback for listed issuers** (FR-003): a Yahoo-mapped issuer whose Yahoo file is missing, or starts after the issuer's first event in the universe, is also resolved and fetched from Tiingo. The choice is recorded (R4).
  - **Storage.** For each ticker:
    - the meta response (JSON) and the price CSV, stored gzip-compressed under `data/raw/tiingo/`;
    - one manifest line each with `source = tiingo`, recording the SHA-256 of the stored file.
    About 3,000 tickers × 2 requests is about 6,000 requests, under one hour at the hourly limit.
  - **Rate.** 2 requests per second (7,200 per hour) on a shared limiter, under the 10,000-per-hour cap.
- **Alternatives**:
  - **Trust Tiingo's ticker without checks**: about 10% of resolutions are reused tickers, so another company's prices would enter silently.
  - **Fetch only the dates of the issuer's filings**: insiders often stop filing months before a stock delists, so the series would end too early and every delisting date would be wrong.

## R4. One price series per issuer (FR-006)

- **Decision**:
  - **Typed provider rows.** `stg.price_yahoo` and `stg.price_tiingo` hold typed copies of the raw files, one row per ticker and session.
  - **Series register.** `core.price_series` holds one row per (issuer, source, ticker): first and last session, row count, the identity check, `chosen` and `reason`. The choice:
    1. Yahoo's primary ticker for Yahoo-mapped issuers, unless the Tiingo fallback applies (R3);
    2. Tiingo's resolved ticker for Tiingo-mapped issuers;
    3. no accepted series → the issuer is unpriced.
  - **Price table.** `core.price_daily` holds one row per (issuer, session) from the chosen series and its fill-ins. Columns: as-traded OHLC and volume, adjusted close, `cum_split_after`, split ratio on the day, dividend, dollar volume, `price_source` and ticker.
  - **Conflicts.** For duplicate sessions within one file, the last row in file order is kept. Rows with a non-positive close, or with high < low, are dropped. Both are counted in `audit.price_issue`.
- **Rationale**: all later steps read one table with one meaning per column. The provider tables keep everything for audits and for re-choosing.

## R5. Session calendar

- **Decision**: `core.session` is SPY's Yahoo sessions from 2010-01-01, numbered consecutively (`session_no`). It gives:
  - the last session on or before T;
  - T+1;
  - the cooldown distance, in sessions;
  - the 20- and 63-session windows.
- **Point-in-time note**: the exchange calendar is published in advance, so the calendar is **not** truncated in the truncation test. Prices are (§R8).
- **Alternative**: a holiday library. That is a new dependency, and it can disagree with the prices actually stored.

## R6. G8 price check (FR-008)

- **Decision**:
  - **Checked lines.** G8 runs on each `core.transaction` line that passes the line gates (G1–G6a), at an issuer with a chosen series.
  - **Rule.** The reference session is the last session on or before the trade date. The line passes when `low × (1 − tol) ≤ price ≤ high × (1 + tol)`, using that session's as-traded low and high and `tol = registered.g8_tolerance` (0.10). A line whose issuer has prices but none on or before its trade date fails with reason `no_session`.
  - **Rebuilt purchases.** `core.priced_purchase` is built like `core.clean_purchase`, from lines passing G1–G6a and G8, with the G6 minimum ($25k) applied again. Issuers without prices keep their clean purchases unchanged: G8 is skipped and flagged.
  - **Pass rate (SC-002).** Lines passing G8 ÷ lines checked, over clean-purchase lines at priced issuers. It is reported in total and by year.
- **Rationale**: plan §6.2 defines G8 on the reported price, which lives on the line. Re-applying G6 keeps "≥ $25k per entity per filing" true after removals.

## R7. Final detection: candidates, G7, floors, cooldown (FR-009 – FR-015)

- **Decision**:
  - **Candidates.** `prelim.find_events` gains a `keep` argument (the cooldown policy). With it switched off, it returns every candidate (issuer, group, T) from `core.priced_purchase` from 2011-07-01, with entities and roles as of T as in feature 002.
  - **Sequential pass.** Within each issuer and group, in date order. The first matching outcome wins:
    1. **Cooldown.** The last kept event is fewer than `registered.cooldown` (63) sessions earlier, counting session numbers of the last sessions on or before each T → `cooldown`.
    2. **G7.** The signal filing's header gives SIC 6770, 6722 or 6726 → `g7_issuer_type`. The header has no SIC → `g7_no_sic` under D45, or the issuer's current SIC (from submissions, R10) when `rules.g7_no_sic = current_sic`. No stored header → `needs_header`.
    3. **Unpriced.** The issuer has no chosen series, or no price row in sessions T−19 … T → `unpriced`. The candidate **is kept**, as an unpriced event, and starts a cooldown: its floors are unknown, and the bounds need unpriced events counted the same way as priced ones.
    4. **Floors**, at the last session on or before T, using rows up to that session only. Each failure leaves the candidate available for the next date:
       - as-traded close < $2 → `floor_price`;
       - ADDV20 < $100,000 → `floor_liquidity` (ADDV20 is the mean of close × volume over the 20 sessions; missing rows count as 0);
       - fewer than 18 of 20 sessions with volume > 0 → `floor_activity`.
    5. Otherwise → `event`, which starts a cooldown.
  - **Missing headers.** `sentinel detect` reports `needs_header` signal filings and stops with exit code 3. `sentinel fetch-headers --final` fetches them, and `detect` runs again; the warm-up adds about 1,239. `detect --fetch-missing-headers` loops automatically, at most 3 rounds. An offline `build` never fetches: it reports missing headers as an error.
  - **Outputs.**
    - `evt.event_candidate` holds every candidate with its outcome.
    - `evt.event` holds the kept ones (`event` and `unpriced`), with entry session = the session after T, priced flag, floor values, G7 SIC and source, and market capitalisation (R9).
    - `evt.event_member` holds their purchases.
    - `audit.event_funnel` counts outcomes by year and group.
  - **Coverage (FR-007, SC-001).** The same pass is run **without floors**: every priced candidate that passes G7 is kept. For each A and B1 event from 2012 it records whether the chosen series spans sessions T−19 to T+1, that is, first row ≤ T−19 and last row ≥ T+1. Results go to `audit.price_coverage`, by year and by delisting status (R11).
- **Rationale**:
  - "Floors failing does not start a cooldown" is FR-012.
  - Unpriced events start a cooldown so that their count does not balloon through near-duplicate candidates on consecutive days.
  - Coverage is about data availability, not trading activity. The activity floor handles the latter.
- **Alternative rejected**: applying floors after a 63-session cooldown. A failed candidate would then suppress a valid event weeks later, which plan §6.4 does not intend.

## R8. Truncation test for final events (FR-015, SC-006)

- **Decision**:
  - Builders take `cutoff` and `issuers`, as in feature 002. A cutoff truncates filings, headers and XBRL facts filed after T, and `core.price_daily` rows after the last session on or before T. It does not truncate the calendar (R5).
  - **What is compared**: candidates and events dated on or before T, their outcomes, floor values and G8 results for lines traded on or before T.
  - **Synthetic cases**: a reverse split after T, a floor that passes only with later prices, and a cooldown chain crossing T.
  - **Real test**: 20 random (issuer, T) pairs with seed 20261023, marked `slow`, run under the 5 GB ceiling.
- **Point-in-time note**:
  - As-traded prices are facts of their own session. They are computed once from the full raw file, so truncating rows changes nothing at or before T.
  - Return ratios within a past window are unaffected by later dividend or split adjustments, because both are multiplicative.

## R9. SEC company facts and filing histories (FR-021 – FR-023)

- **Finding** (HEAD requests, 2026-10-23):

  | Archive | Size | Last modified |
  |---|---|---|
  | `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` | 1.41 GB | 2026-10-23 04:19 GMT |
  | `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` | 1.57 GB | 2026-10-23 04:27 GMT |

  - SEC responses run at about 2 per second today (the header job: 12,500 in 97 minutes, with occasional 503s). Per-company requests for about 6,600 issuers × 2 would take about 2 hours. The two archives are 2 requests.
  - The submissions file for Twitter (CIK 1418091) lists filings made *about* the company as well as by it: SC 13D and 13G, Form 4, and the exchange's 25-NSE. It shows DEFM14A (2022-07-26), PREM14A, 25-NSE (2022-10-28) and 15-12G. Its `exchanges` and `tickers` are empty now that it is delisted. Older filings sit in extra pages (`CIK…-submissions-001.json`), which the bulk archive includes.
- **Decision**:
  - **Download.** `sentinel fetch-company` streams both archives to `data/raw/sec/company/` through feature 001's `stream_to_file`, with manifest lines and the SEC User-Agent. These are 2 requests, sharing the SEC limiter with any running header job.
  - **Extraction.** `sentinel company-facts` reads only the universe's members from the zips, one company at a time. Peak memory is one company's JSON, at most about 300 MB.
  - **`core.xbrl_fact`** holds one row per issuer, concept, unit, period start and end, **first-filed only**: the earliest `filed`, then the smallest accession. Columns: `value`, `filed`, `accession`, `form`, `fp`, `tag_used`. Concepts and tags (plan §7.2):
    - shares outstanding: `dei:EntityCommonStockSharesOutstanding`;
    - equity: `StockholdersEquity`, else `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`;
    - total assets: `Assets`;
    - total liabilities: `Liabilities`, else assets − equity, computed at use;
    - cash: `CashAndCashEquivalentsAtCarryingValue`, else `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`;
    - net income: `NetIncomeLoss`, else `ProfitLoss`.
    The fallback tag is used only for periods where the main tag has no value.
  - **`core.company_filing`** holds every filing in the issuer's submissions except insider forms (3, 4, 5, 144 and their amendments): accession, form, filing date, report date, 8-K items.
  - **`core.issuer`** holds each issuer's name, current SIC and label, current exchanges and tickers (from submissions).
  - **Market capitalisation at T** (FR-022) is computed in `detect` and stored on `evt.event`: as-traded close at the last session on or before T × the shares-outstanding value with the latest `filed` on or before T (then the latest period end). It is null if there is none. Shares are reported only where the cover-page tag is present; multi-class companies often lack it, and F16 is then missing, as plan §7.2 says.
- **Market-cap check (SC-005)**: 10 single-class, currently listed event companies. Yahoo's reported market capitalisation (yfinance `fast_info`) is fetched once and stored raw, then compared with this pipeline's value at the latest session, within 5%. `sentinel audit market-caps` writes the comparison.
- **Alternative**: per-company `data.sec.gov` requests. About 2 hours at today's SEC speed, versus minutes; it is kept only as a fallback if a bulk download fails.

## R10. G7 inputs and the D45 fallback (FR-010)

- **Decision**:
  - `rules.g7_excluded_sic: [6770, 6722, 6726]`.
  - `rules.g7_no_sic: exclude` (D45 as adopted), or `current_sic` (the §11 fallback, using `core.issuer.sic`). The researcher's D45 sheet result (feature 002, due about 29 October) sets it before final detection. With `current_sic`, an issuer with no current SIC is still excluded.
  - Each event records `g7_sic` and `g7_sic_source` (`header` / `current`).

## R11. Delisting classification (FR-017 – FR-020)

- **Decision**:
  - **Ends early**: the chosen series' last session is more than `rules.delisting_end_gap_sessions` (5) sessions before the last session in `core.session`. Unpriced issuers are not classified: they are covered by the unpriced bounds.
  - **Evidence** comes from `core.company_filing`. Forms match by prefix, so amendments (`/A`) count.
    - **Merger evidence**: DEFM14A, DEFM14C, PREM14A, PREM14C, SC 14D9, SC TO-T, SC 13E3, 425, filed in the 12 months before the last trade (`registered.merger_lookback`).
    - **Performance evidence**: 25, 25-NSE, 15-12B, 15-12G, 15-15D, filed from 12 months before to 12 months after the last trade (`rules.delisting_notice_after_months: 12`). Exchanges file 25-NSE days after the last trade, and Form 15 follows it.
  - **Class**, in order:
    1. Re-map: a 10-Q or 10-K filed more than `rules.remap_after_days` (90) after the last price → `remap`. During the paid month the issuer's other SEC tickers are tried in Tiingo. If none is found, the class becomes `unknown` and is flagged.
    2. Merger evidence → `acquired`.
    3. Performance evidence → `performance`.
    4. Neither → `unknown`.
  - **Venue**, for the performance return:
    - Tiingo issuers: the exchange of the issuer's last exchange-listed ticker in Tiingo's list. NYSE, NYSE MKT, AMEX and NYSE ARCA count as NYSE or NYSE American; NASDAQ counts as Nasdaq; anything else is `other`.
    - Yahoo issuers: the SEC snapshot's exchange.
  - **Delisting return**:
    - acquired: 0%;
    - performance: −30% (NYSE or NYSE American) or −55% (Nasdaq);
    - `other` and unknown venues: −55% (`registered.delisting_returns.other_venue_treated_as: performance_nasdaq`; a new register row, see the spec's Assumptions);
    - unknown class: the performance return.
    Bounds of 0% and −100% are stored with every row.
  - **Audit**: `sentinel audit delistings` draws 30 issuers (10 per class, seed 20261024), with EDGAR filing-index links, the evidence form and date, and blank `verdict` (`agree` / `disagree` / `unclear`) and `notes` columns.
- **Rationale**:
  - The plan's merger window looks back only, and its performance forms come after the last trade.
  - The Twitter check shows that subject-company filings appear in the submissions data, so tender offers and 425s are visible.

## R12. Reference data (FR-024)

- **Finding** (downloaded 2026-10-23):
  - Daily data runs through **2026-08-31** ("created by using the 202608 CRSP database"), which covers 63-session windows of holdout events up to about 1 June 2026.
  - Base URL `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/`. Files:
    - `F-F_Research_Data_5_Factors_2x3_daily_CSV.zip`
    - `F-F_Momentum_Factor_daily_CSV.zip`
    - `F-F_ST_Reversal_Factor_daily_CSV.zip`
    - `49_Industry_Portfolios_daily_CSV.zip`
    - `12_Industry_Portfolios_daily_CSV.zip`
    - `Siccodes49.zip`
    - `Siccodes12.zip`
    - `ME_Breakpoints_CSV.zip`
  - **Format**: each CSV starts with free-text lines and holds one or more sections; the industry files have "Average Value Weighted Returns -- Daily" and "Average Equal Weighted Returns -- Daily". Dates are `YYYYMMDD`, values are in percent, and −99.99 means missing. Siccodes files list each industry number and short name, then SIC ranges (`0100-0199 …`).
- **Decision**:
  - `sentinel fetch-reference` stores the zips under `data/raw/french/`, with manifest lines.
  - `sentinel reference` loads them into:
    - `core.ff_factor_daily` (date, factor, return as a decimal);
    - `core.ff_industry_daily` (date, scheme 12/49, industry, weighting EW/VW, return);
    - `core.sic_industry` (scheme, industry number, short name, SIC from–to);
    - `core.me_breakpoint` (month, percentile, value).
  - The SIC check reports header SICs that map to no 49-industry portfolio.

## R13. Tick Size Pilot (FR-025)

- **Finding**:
  - FINRA's daily list is discontinued; the current `TSPilotSecurities.txt` is empty.
  - `https://tsp.finra.org/finra_org/ticksizepilot/TSPilotChanges.txt` (510 KB) is **cumulative from September 2016 to 1 April 2019**: 7,141 pipe-delimited records with ticker, name, listing exchange, effective date, deleted date, group, old group and reason.
  - 1,235 distinct tickers were ever in test groups G1–G3. Phase-in happened on 3, 17 and 31 October 2016, and every stock returned to control (C) on 1 October 2018.
- **Decision**:
  - Store the file under `data/raw/finra/`, with a manifest line.
  - `core.tick_pilot` holds (ticker, group, from, to) intervals for G1–G3, built from effective and deleted dates.
  - All three test groups were *quoted* in $0.05 increments, so all get the $0.05 tick. A stock-day matches when the issuer's primary ticker equals the pilot ticker on that date.

## R14. Spreads and costs (FR-026 – FR-028)

- **Decision**, for each priced event, over sessions up to the last session on or before T:
  - **Abdi–Ranaldo**: with c the log close and η the mean of log high and log low (split-adjusted, so a split between two days does not create a jump):
    - for each consecutive session pair in the 20-session window, the two-day estimate is 4 × (c_t − η_t) × (c_t − η_{t+1});
    - S_AR = √max(mean of the two-day estimates, 0).
  - **Corwin–Schultz** (2012), with the overnight adjustment, as a cross-check: its median ratio and rank correlation to S_AR are reported, not used.
  - **Tick floor**: S = max(S_AR, tick ÷ as-traded close at T), where tick is $0.05 for a pilot stock-day (R13) and $0.01 otherwise.
  - **Volatility** σ: standard deviation of daily log returns of adjusted close over 63 sessions (`registered.volatility_window`). At least 40 returns are needed, otherwise the cost is null and flagged.
  - **Cost**: ADDV20 as in R7, and c = S + 2·k·σ·√(Q ÷ ADDV20) with Q = $10,000 and k = `registered.impact_coefficient` (1.0).
  - All values go to `evt.event_cost`, with `price_source`.
- **Report**: `specs/004-market-data-events/costs.md` gives the median and quartiles of S and c by as-traded price bucket ($2–3, 3–5, 5–10, 10–20, 20–50, 50+, plus a below-$2 bucket from candidates failing only the price floor) over development events (2012–2022). It flags any bucket boundary other than $2 where the median cost changes by more than half. It is a table, with no plotting dependency; figures belong to the report step.
- **Check**: the plan's §6.8 illustration ($2, 1% spread, 4% volatility, ADDV $100k → about 3.5%) is a unit test.

## R15. Tiingo deletion register and deletion (FR-005, SC-007)

- **Decision**:
  - **The register** has two parts:
    1. every manifest line with `source = tiingo` (raw files);
    2. a fixed list in code, `TIINGO_DERIVED`: each warehouse table that can hold Tiingo-derived per-security values, with its deletion predicate (`price_source = 'tiingo'`, or the whole table for `stg.price_tiingo` and `core.tiingo_listing`).
    Every such table carries a `price_source` column. A test fails if a table with `price_source` is missing from the list.
  - **Status.** `sentinel tiingo-status` lists the register (files, bytes, rows per table) and the days left until `ops.tiingo_paid_until`.
  - **Deletion.** `sentinel tiingo-delete --yes`:
    1. deletes the registered rows and tables;
    2. rewrites the warehouse into a fresh file (`COPY FROM DATABASE`) and replaces the old one, because DuckDB does not reliably return freed blocks;
    3. deletes `data/raw/tiingo/`;
    4. appends `role = deleted` manifest lines;
    5. checks that nothing remains;
    6. prints the decision-log line for the researcher to record.
  - **Invariant W12** changes: "no Tiingo data outside `data/raw/tiingo/` and the registered tables. Outside the paid window, none at all."
- **Rationale**: constitution VI counts per-security values derived from Tiingo prices (for example floor values, costs and labels) as Tiingo data. Only aggregates can be kept.

## R16. Memory and run plan

- **Estimated rows**:
  - `stg.price_yahoo`: about 15 M (4,482 tickers × about 3,500 sessions);
  - `stg.price_tiingo`: about 7 M;
  - `core.price_daily`: about 18 M.
- **Decision**:
  - Load raw files in chunks of 250 tickers, one transaction each, into shadow tables, then swap, as feature 002's staging does.
  - Every heavy command runs under `systemd-run --user -p MemoryMax=5G -p MemorySwapMax=1G`, with DuckDB at 3 GB and 4 threads.
  - Parsing the companyfacts archive is single-threaded Python and streams by company.

## R17. Audit sheets (FR-016, FR-020)

- **Decision**:
  - **Golden set.** `sentinel audit golden` draws 30 final events from the labelled window (seed 20261025), stratified 10 A, 10 B1 and 10 B2 where possible, to `specs/004-market-data-events/audits/golden_set.csv`. Columns:
    - per event: event id, group, issuer and name, T, entry session, each member's entity, role, accession, value and EDGAR link;
    - blank `insiders_ok`, `dates_ok`, `amounts_ok` and `notes`.
  - **Delistings.** `sentinel audit delistings` writes `delisting_audit.csv` (R11).
  - **Summaries.** `audit golden-summary` and `audit delistings-summary` report agreement. Sheets are never overwritten without `--force`, as in feature 002.

## R18. Parameter file additions

Added before `prereg-v1`. See [contracts/params-rules.md](contracts/params-rules.md).

- **`rules` section**:
  - `final_detection_start: 2011-07-01`
  - `price_history_start: 2010-01-01`
  - `g7_excluded_sic`
  - `g7_no_sic`
  - `delisting_merger_forms`
  - `delisting_performance_forms`
  - `delisting_notice_after_months`
  - `delisting_end_gap_sessions`
  - `remap_after_days`
  - `tick_size_usd: 0.01`, `tick_size_pilot_usd: 0.05`
  - `min_volatility_returns: 40`
- **`registered.delisting_returns`** gains `other_venue_treated_as: performance_nasdaq`, with a matching row in plan Appendix E, so `check_register` stays green.
- **`ops` section**:
  - `tiingo_paid_from`, `tiingo_paid_until`
  - `tiingo_requests_per_second: 2`
  - `yahoo_batch_size: 50`
  - `reference_symbols: [SPY, IWM]`
  - SEC bulk URLs, French base URL and file list, FINRA URL
