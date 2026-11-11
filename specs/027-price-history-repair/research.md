# Research: Price history repair (027)

Decisions taken while planning (11 Nov), each checked on the build of 11 November (read-only), with
why and what else was considered. Counts are of listed companies (in today's SEC list or their last
stored one: 7,351, of which 7,038 priced) unless stated.

## R1 · A price history is a chain of segments

- **Decision**: `core.price_choice` holds one row per **segment** instead of one per company: a
  stretch of days `[trim_from, trim_to]` taken from one provider's series of one ticker, with the
  reason it was taken; a company's segments never overlap; one segment per company is `main` (the
  latest), which gives `ref.security` its ticker and source. `core.price_daily` keeps its join on
  (source, ticker, dates), so it reads segments without change; `ref.security`,
  `core.price_coverage` and `validation.py` read the `main` row. Every decision about a history
  (a join, a cut, a lost claim, a failed join, SPAC months) is written to a new table,
  `core.price_decision`, for the audit and the app's diagnostics.
- **Rationale**: the smallest change that lets one company hold several tickers; the daily-price
  step, the glitch rules and the split handling stay as they are.
- **Alternatives**: a stitched series per company built before `core.price_daily` (a second copy of
  every price); keeping one row per company and adding the old tickers' prices afterwards (two code
  paths for the same day).

## R2 · Which tickers a company used, and when

- **Decision**: the evidence is the company's own: its Form 4s' symbols (`ref.ticker_history`,
  `form4`: first to last filing that printed the symbol, from 2006), its SEC-list entries (stored
  since 22 Oct 2026 only: 11 lists) and its current listed ticker. A ticker found only in the
  company's own Form 4s becomes a segment only if (a) a provider's series of it exists, (b) the
  provider's company name matches one of the company's SEC names (`identity`, as today for
  disappeared companies), or the SEC's list assigned the ticker to the company (Yahoo series of
  listed tickers), and (c) the continuity check of R3 passes at the switch.
- **Rationale**: a typo in one Form 4 must not attach another company's prices; the name and
  continuity checks are the guard the join needs (MGP's MGPI passes on both: SEC lists until
  4 Nov, Tiingo's name "MGP Ingredients").
- **Alternatives**: Tiingo's name search alone (finds renamed companies but also look-alikes);
  a hand-made list of renames (stale at once; rejected in R12 of 001 for the same reason).

## R3 · Joining across a ticker change, with a continuity check

- **Decision**: a history is built backwards from its main segment. Where the main segment starts
  after 1 January 2010 (after its own cuts), the company's other own tickers are tried, newest
  first: one whose series ends at most 10 trading days before the later segment's first day and
  whose last as-traded close is within a factor of 1.5 of the later segment's first close once a
  split recorded at the switch is allowed for, is joined up to the day before the later segment
  starts; the step repeats from the joined segment's start (at most five segments). A failed check
  writes `join_failed` with the reason (dates, level). Where a provider already carries the earlier
  history under the new ticker (Tiingo's IR from Gardner Denver's first day, 12 May 2017), the
  longer series is kept and no join is needed.
- **Rationale**: the same company's shares do not jump in level at a rename; a gap of weeks or a
  level that disagrees means another instrument or another company (the check is the guard of R2).
- **Alternatives**: join on evidence alone (attaches typos); require the same provider on both
  sides (MGP's earlier history is in Tiingo and Yahoo under MGPI, its later in Yahoo under CASK).

## R4 · Cuts: only where another company really held the ticker

- **Decision**: the start of a ticker's "current listing" in Tiingo's list no longer cuts (research
  R12 of 001 is replaced). A history is cut (1) on 1 January 2010; (2) after another company's
  last use of the ticker when that use ended before the company's own first use of it (a reuse:
  Chubb Corp's CB before Chubb Ltd's); (3) before a hole of more than a year (R6); (4) on blank-check
  days (R7). Another company's use that overlaps the company's own use in time no longer cuts
  (V2-63 widened from "strictly inside" to "overlapping", which also covers uses ending the same
  day: Digital Realty).
- **Rationale**: Tiingo's list dates are not company boundaries: 4 Jan 2016 is where its coverage
  of many small stocks begins (60 companies cut there, Sono-Tek and Eagle Financial among them,
  both on Nasdaq long before); an exchange move splits one line into two (Palatin, NYSE American
  1997–2025 then Nasdaq; Triller's two back-to-back lines on the same exchange); and it keeps two
  companies in one line (Heidmar's HMR line runs from 2008 with a 15-year hole). The cut dropped
  stored prices for 943 companies (39,090 company-months of 2012–2022). A real reuse leaves
  evidence the remaining rules see: the other company's own filings, or a hole.
- **Alternatives**: keep the listing cut but skip exchange moves (still cuts at coverage starts);
  cut at a Tiingo list boundary only when a gap separates two lines (Heidmar's single line shows
  that the lines do not separate companies either).

## R5 · One ticker-day belongs to one company

- **Decision**: after segments are chosen, two companies whose segments claim the same provider
  series over overlapping days are resolved pair by pair: the overlap goes to the one the SEC's
  list names for the ticker, if either; otherwise to the one with more own Form 4 filings printing
  the ticker during the overlap; otherwise to the lower CIK; the other's segment is trimmed and
  `lost_to` is written with the winner. A rebuild must leave no (source, ticker, day) with two
  companies.
- **Rationale**: on 11 Nov 83,024 ticker-days on 120 tickers were given to two or more companies:
  sister companies (twelve Atlas partnerships on ATLS; United Rentals and its subsidiary on URI;
  Digital Realty and its operating partnership), holding-company reorganisations where the old and
  the new company both kept the same days (Express Scripts, National Western Life, TCF). A share
  price has one issuer; the main issuer files most of the insider reports under its ticker.
- **Alternatives**: day by day resolution (fragments a history when the counts alternate); giving
  the days to both (today: double rows in every question).

## R6 · A hole of more than a year ends the earlier part

- **Decision**: in each segment's series, the part before the last gap of more than 365 calendar
  days is kept only when the company's own evidence for the ticker (its Form 4 span widened by the
  warm-up of 400 days before and 90 days after, or an SEC-list entry) overlaps it; otherwise it is
  cut (`hole`). Gaps of 31–365 days stay (trading halts) and are counted in the audit.
- **Rationale**: 39 listed and 28 disappeared companies had a hole of over a year; the samples are
  two companies glued together (Standard BioTools' LAB begins with LaBranche's 2010–2011 prices;
  Heidmar's HMR with a 2010 block of an earlier user). A real long halt keeps its earlier part
  because the company's own filings cover it (Sinovac).
- **Alternatives**: always cut before a long hole (loses real halts); never (keeps the glued
  prices).

## R7 · Blank-check (SPAC) days, by date (V2-66)

- **Decision**: a company is a blank-check company on the days of a former name (EDGAR's former
  names carry their dates) that matches, in capitals and as whole words,
  `(ACQUISITION|ACQUISITIONS|MERGER) (CORP|CORPORATION|CO|COMPANY|INC|LTD|LIMITED|HOLDING|HOLDINGS|GROUP|TRUST)`,
  `SPAC` or `BLANK CHECK`, provided the name lasted at most 3.5 years or the price sat between $9
  and $11 on at least half of the name's priced days; and on every day when its current industry
  code is 6770 (as today). No segment covers those days, so no question has a row on them and the
  app's history starts at the merger; a SPAC's ticker is not joined. The app shows a line "listed
  through a merger with <former name> on <date>".
- **Rationale**: whole words keep out Geospace ("OYO GEOSPACE") and AST SpaceMobile, which a plain
  substring caught. Of 686 matching names (658 companies; 242 with prices in their period), 172
  priced periods sat near $10 on at least 80% of days; SPACs that traded far above trust value are
  still SPAC months (Digital World, Kensington, Fortress: under 25% near $10, all under 3.5 years).
  The two conditions keep every real SPAC found, including those extended to 4.3 years (Southport:
  100% near $10), and leave out the four long-lived non-SPACs found: Skyline Bankshares (Parkway
  Acquisition Corp., a bank holding company, 7.2 years, 16% near $10), Trex Acquisition, Eastgate
  Acquisitions and Global Acquisitions (0%). The rule reconstructs the industry code a company had on
  each day, which the SEC keeps only for today; it uses no outcome. Its rows: 3,013 in the dilution
  file (2,105 eligible). The audit lists every company the rule touches, with its share of days
  near $10, so a wrong match can be seen.
- **Alternatives**: the name alone (catches Parkway's seven years of banking); the price alone (a
  stock near $10 is not a SPAC); the current industry code only (today: misses every merged SPAC).

## R8 · The common stock first, for US companies

- **Decision**: a listed US filer is priced from the first of its SEC tickers, in the SEC's order,
  that has a usable series, plain tickers (no class suffix after a dash) before suffixed ones
  (preferred `-P…`, units, warrants, rights). Foreign and price-only companies keep their first
  ticker only (an ADR and its ordinary share are different instruments: FR-006, no ratios).
- **Rationale**: Telephone & Data Systems' first SEC ticker, TDSPRV, has no data, so the company
  had no prices although TDS has; Chatham Lodging was priced by CLDT-PA from 2021 while CLDT trades
  since 2010. Of the 85 listed companies without a price though another ticker has data, most are
  foreign ADR pairs, which stay as they are.
- **Alternatives**: any ticker with data for every company (would price ADR companies by their
  ordinary shares without a ratio).

## R9 · Old tickers' prices: downloaded once from Tiingo

- **Decision**: a new fetch, `sentinel fetch tiingo --former`, asks Tiingo once for each ticker a
  company's own evidence names, with no stored series, that Tiingo's list carries with dates
  overlapping the company's use: 692 tickers for 681 companies on 11 Nov, about 1,400 requests
  (prices from 1 Jan 2010 and the description) at 2 a second, some 12 minutes. Files go to
  `tiingo/former/<T>.csv.gz` and `tiingo/former_meta/<T>.json.gz` with manifest lines; staging
  reads them like the other Tiingo files (`former_meta` added to the meta folders). Only inside the
  paid window (until 26 Nov); a stored file is never asked again.
- **Rationale**: only 33 of the 370 ticker changes had the old ticker's prices stored; Yahoo does
  not serve retired symbols (CASK came back with 8 days).
- **Alternatives**: Yahoo's history under the new symbol (it does not carry renamed histories
  reliably: MGP); leaving those gaps (the largest family).

## R10 · Adjusted prices across a switch

- **Decision**: the adjusted prices of an earlier segment are multiplied by the later segment's
  adjustment ratio (adjusted ÷ as traded) on its first day, divided by the earlier segment's on its
  last day, so the adjusted return across the switch equals the as-traded move; as-traded prices
  are rebuilt per company as now (split ratios from each segment's own records).
- **Rationale**: a provider's adjusted prices for a retired ticker include only the dividends and
  splits up to its last day; glued as they are, a later reverse split or years of dividends would
  appear as a jump at the switch.
- **Alternatives**: recompute adjusted prices from dividends and splits (a second adjustment method
  beside the providers').

## R11 · Point in time, and no drift

- **Decision**: features stay computed only from prices of days up to D (the truncation test of
  `core.price_daily` is unchanged). Which company a day's price belongs to is decided from who held
  the ticker that day (evidence dated in that period), never from what happened to the company
  later. A new test adds a ticker change after day D to a synthetic company and requires its rows
  up to D unchanged.
- **Rationale**: today a ticker change deletes the company's past rows (96 development rows lost
  between 9 and 10 Nov): survivorship by rename (constitution III).

## R12 · The audit command

- **Decision**: `sentinel audit` reads the build database read-only and prints, for the problem
  families of 11 Nov, their counts with five examples each, the named cases' pass or fail, coverage
  of listed and disappeared companies by year and status (constitution III), the companies the SPAC
  rule touched, and the ticker-days claimed twice; it writes the same as JSON to
  `data/audit/prices-<date>.json` (private: examples carry dates derived from Tiingo prices) and a
  counts-only Markdown summary to `docs/report/data_audit.md` (aggregates and pass/fail only). Run
  on the build of 11 Nov before any change, it records the baseline.
- **Rationale**: turns the one-off audit into a check after every build; the report quotes it
  instead of typed-in numbers.

## R13 · Retrain, approve, keep, freeze, test (V2-65, with the researcher's timing)

- **Decision**: after the rebuild, `sentinel verify`, the audit and the EDA re-run: the three model
  notebooks run start to finish on the new export (007, 006, 005, about 45 minutes), unchanged; the
  researcher reviews and approves each; the export they ran on is kept in
  `data/frozen/<export date>/ml/`; `holdout.KEPT` no longer holds a date: it is read from the
  approved frozen models' `export_date` tag, and the kept files' hashes must equal their
  `data_hash`; `sentinel holdout --freeze-levels` runs again on the new kept rows and must
  reproduce the notebooks' records; `--check`; then the one `--run` by the researcher, by Tuesday
  17 November if all of this is done, otherwise after the hand-in. The 9 November records and kept
  export stay as the earlier record; the extra dilution record of 10 November is superseded.
- **Rationale**: the frozen objects and the levels must come from the same rows (V2-59, V2-60).

## R14 · Order of work and the daily update

- **Decision**: Thu 12 Nov: code and tests for R1–R10 and R12, the former-ticker download, the
  baseline audit; Fri 13: rebuild, verify, audit, named cases, the hand check of 30 cuts, EDA re-run;
  Sat 14–Sun 15: the three notebooks, the researcher's review; Mon 16: approval, keep, freeze,
  check; Tue 17: the holdout run if ready, the report; the product (the app on the repaired data)
  on 17 Nov. The daily update runs the checked-out branch at 10:00: the branch is kept working at
  that hour (tests green before 10:00, or the previous branch checked out).
