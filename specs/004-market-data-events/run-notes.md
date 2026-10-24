# Run Notes: Feature 004

Results of the real runs (tasks T021, T022, T036–T038, T047, T054, T060, T063, T066, T067). Every heavy step ran under `systemd-run --user -p MemoryMax=5G -p MemorySwapMax=1G`, with DuckDB capped at 3 GB.

## Free downloads (2026-10-23)

The feature 002 header fetch (T037) was paused at 19,000 of 27,281 filings to free the fetch lock, and resumed after these downloads. The fetch is resumable: stored headers are never fetched again.

| Source | Files | Size | Time |
|---|---|---|---|
| Kenneth French library | 8 zips | 5.7 MB | 1 min |
| FINRA tick-size pilot change file | 1 | 0.5 MB | under 1 min |
| SEC `companyfacts.zip`, `submissions.zip` | 2 | 2,982 MB | 21 min |
| Yahoo (yfinance): listed companies, SPY, IWM | 4,438 tickers stored; 46 returned no data (`data/raw/yahoo/failures.csv`) | 474 MB | 52 min |

## T063: Reference data (2026-10-23)

| Check | Result |
|---|---|
| Tick-size pilot | 1,249 G1–G3 intervals (FINRA change file, Sept 2016 – Apr 2019) |
| French daily factors | 148,044 rows (Mkt-RF, SMB, HML, RMW, CMA, RF, Mom, ST_Rev), **through 2026-08-31** |
| Industry returns | 3,210,674 rows (49 and 12 industries, value- and equal-weighted) |
| SIC ranges | 647 |
| NYSE size breakpoints | 24,180 (monthly, every 5th percentile) |
| Header SICs outside the 49 industries | `0000` (27 filings), `3990` (11) |
| Time | 4 s |

- **SIC 0000** is EDGAR's code for "no industry assigned". G7 now treats it as no SIC (D45; decision D51; test `test_g7_uses_the_signal_filings_header[0000-g7_no_sic]`).
- **SIC 3990** (miscellaneous manufacturing) is in no 49-industry range. The 12-industry scheme's "Other" covers it; it matters only for the industry benchmark, a later feature.

## T037 (part): Header re-fetch with the SGML fallback (2026-10-24)

The feature 002 fetch finished on 24 Oct with 3,677 failures, 3,672 of them HTTP 404, all for 2012–2014 filings (1,535 / 1,445 / 692). EDGAR's directory listing still names `{accession}-index-headers.html`, but its storage answers `NoSuchKey`. The bare SGML header `{accession}.hdr.sgml` is served and holds the same block the parser reads, without the industry name, which nothing downstream uses.

- **Change**: `ops.sec_headers_fallback_url_pattern`; `sec_headers._fetch_one` falls back to it on a 404 only. Tests: `test_a_missing_index_page_falls_back_to_the_sgml_header`, `test_a_bare_sgml_header_parses_without_the_industry_name`.
- **Run**: `sentinel fetch-headers --retry-failures`: 3,675 of 3,677 stored, all through the fallback; 2 failures left (`0001019687-13-004805`, HTTP 503 after 5 attempts; `0001144204-18-051629`, unparseable). 1 h 16 min (SEC 503s and time-outs); peak 415 MB.

| Check | Result |
|---|---|
| Signal filings from 2012 with a header | **27,288 of 27,290 (100.0%)**; 2012: 3 → 1,538, 2013: 8 → 1,456, 2014: 1,051 → 1,743 |
| No SIC / SIC `0000` / 6770 / 6722 or 6726 | 1,588 / 110 / 130 / 0 |
| Accepted at or after 16:00 ET / before 09:30 ET | 18,516 (68%) / 1,939 (7%) |

**Fetch failures kept with the raw files (later on 24 Oct).** The offline-rebuild rehearsal showed that fetch failures lived only in `core.header_failure`, so a rebuild from `data/raw` would not know them and `detect` would stop with "missing headers". They are now also written to `data/raw/sec/headers/failures.csv` (accession, reason, last attempt), which `load_headers` reads; a later success removes the line. Test `test_fetch_failures_survive_a_rebuild_from_raw_files`. `fetch-headers --final --retry-failures` then stored 2 of the 3 old failures; **27,289 of 27,290** signal filings from 2012 now have a header. The one left (`0001144204-18-051629`) is an unparseable page.

**D45 sheet.** `sentinel audit no-sic` counted only headers without a SIC; G7 also treats `0000` as none (D51), so the sheet now samples both (test case `[0000]`). `specs/002-insider-warehouse/audits/d45_no_sic.csv`: 30 companies, seed 2002, verdicts pending with the researcher.

## T021 (free part): Yahoo prices (2026-10-24)

`cap uv run sentinel prices` (the Yahoo pull itself is in the downloads table above):

| Check | Result |
|---|---|
| Rows | 12,432,111 Yahoo rows → **11,340,220** daily rows |
| Series chosen | yahoo_primary 3,513, yahoo_primary_late 136; unpriced 2,928 (Tiingo issuers, until T022) |
| `audit.price_issue` | open_outside_range 195, zero_open 2 |
| W14, W15 | hold (after the fix below) |
| Time, peak memory | 32 s, 4.0 GB |

**Deviation (bug fixed).** The first run failed W15 on 90,508 rows at 64 issuers: `cum_split_after` was stored as `round(cum, 10)` and as-traded prices with 6 fixed decimals. Stacked reverse splits make the factor tiny: OLOX's 8.33203125e-06 was stored as 8.332e-06, and some (BINI, WHLR, NUWE) as 0. Both now keep 10 significant digits (`prices._significant`); test `test_stacked_reverse_splits_keep_full_precision`.

T020, `cap uv run pytest -m slow tests/integration/test_prices_real.py`: 2 passed.

## T036 (free part): Final detection (2026-10-24)

**Deviation (bug fixed).** The first run stopped with a binder error in `final._inputs`: the header-failure predicate used alias `e` in a query aliased `c`. Only reached when `core.header_failure` exists, so no test covered it. Fixed; test `test_a_header_known_to_fail_is_not_requested_again`.

First pass of `cap uv run sentinel detect --fetch-missing-headers`, before the extra headers and before Tiingo:

| Check | Result |
|---|---|
| G8 | 197,182 of 268,705 lines pass (73.4%); **from 2012: 177,544 of 189,203 (93.8%)** |
| Candidates | 45,834: cooldown 14,356, event 13,962, unpriced 8,360, needs_header 5,771, g7_no_sic 1,589, floor_price 976, floor_liquidity 431, floor_activity 281, g7_issuer_type 108 |
| Kept events | A 4,643, B1 2,437, B2 6,882 (from 2011-07-01) |
| Coverage from 2012 (SC-001) | A 5,207 of 8,898 (58.5%), B1 2,714 of 4,096 (66.3%); delisted issuers wait for T022 |
| PayPal check | `1633917:A:2021-11-23` is an event (entry 2021-11-24, header SIC 7389, close 188.05, ADDV20 $4.44 bn, market cap $220.9 bn); the A candidate of 2022-02-22 is `cooldown` (61 sessions) |

- **Headers**: 5,769 signal filings still needed one, far more than research R1's 1,239: final candidates are tested on every date, and the preliminary cooldown had hidden most of them. Three automatic rounds fetched 5,768, 138 and 45 (1 h 18 min, one more permanent failure) and still left 44, all at OPKO Health, Valhi and two others: each round settled one event, which moved the cooldowns and exposed the next date.
- **Deviation (fixed)**: `sec_headers.final_targets` now returns, at each issuer with a `needs_header` candidate, that candidate and every later one without a header (853 at 4 issuers, 15 min), so one round settles the chain. Test `test_headers_are_requested_for_every_later_candidate_of_a_waiting_issuer`. The rerun converged; 3 candidates wait on the 3 permanent header failures.
- **G8 below SC-002 (95%)**:
  - All 58,520 lines traded 2005–2009 fail `no_session`, because prices start on 2010-01-01 (`rules.price_history_start`). They cannot reach a final candidate (detection starts 2011-07-01) but count in the total.
  - Since 2012, 6,687 `outside_range` lines at 983 issuers. The largest groups are share-class mismatches (Biglari Holdings, price ÷ day's mid ≈ 5.1; HEICO 0.79; Hamilton Beach and Hyster-Yale 0.66; First Citizens 0.86; Liberty Media's tracking stocks 0.55), depositary receipts (Adaptimmune 0.165 ≈ 1 ADS = 6 shares), and splits missing from Yahoo or typing errors (Professional Diversity Network 30, Stimcell 15, Zivo 0.013).
  - **Share-class mapping measured, not adopted (24 Oct):** of the 6,687 lines, 963 are at issuers with another Yahoo class stored, and another class's range fits only 515 of them: at most +0.3 points (93.8% → 94.1%). ADR ratios are not in the free data. The mismatches are accepted and documented.
  - **Change (agreed 24 Oct):** G8 checks only lines traded on or after `rules.price_history_start`; earlier lines skip it like unpriced issuers, with `g8_status = skipped_before_prices`. Test `test_trades_before_the_price_history_start_skip_g8`.
  - The other 4,972 failures since 2012 are `no_session`: the issuer's Yahoo history starts after the trade. The Tiingo fallback for late Yahoo series (T022) targets exactly these, so SC-002 is re-measured after T022.

**Final run (free part)**, with the G8 scope change and the header-target fix: 8 min 4 s, peak 1.9 GB.

| Check | Result |
|---|---|
| G8 (SC-002) | 197,182 of 210,185 lines pass (**93.8%**, target 95%; by year 91.1–97.0%) |
| Candidates | 45,834: cooldown 15,784, event 14,639, unpriced 9,088, g7_no_sic 3,367, floor_price 1,715, floor_liquidity 676, floor_activity 415, g7_issuer_type 147, needs_header 3 |
| Kept events | A 4,926, B1 2,542, B2 7,171 (from 2011-07-01) |
| A events by period | warm-up 188; **development 3,076** (+ 3,309 unpriced); window crossing 2023: 94; holdout 1,421 (+ 186 unpriced); after 1 Jun 2026: 147 |
| Coverage (SC-001) | **61.1%** of 13,104 A and B1 events from 2012: listed issuers 97.5% of 8,205, unpriced issuers 0% of 4,899 (T022) |
| Market cap at T | 92.0% of priced events |
| Truncation test (W25), `pytest -m slow tests/integration/test_truncation_events_real.py` | **20 of 20** pairs identical |

- **Truncation test fix (test only)**: the test checked `src.core.issuer` with `warehouse.table_exists`, which takes `schema.table`, so all 20 pairs errored before comparing. It now asks the attached catalog directly (`_in_source`).
- **Coverage report fix**: the XBRL table in `coverage.md` divided by the size of each year's smallest (year, concept) group, giving shares such as 3,210%. It now divides by all of the year's events: shares outstanding 87.5–93.0%, equity and assets 94.0–99.6%, liabilities 72.0–88.7% (before the assets − equity fallback), cash 89.9–99.3%, net income 93.7–99.6%. Test `tests/unit/test_coverage_report.py`.
- **Expected development clusters after T022**: about 4,700–5,300: the 3,076 priced, plus the share of the 3,309 unpriced that Tiingo resolves (84% of delisted A/B1 companies matched its list) and that pass the floors (18% of priced development candidates fail them now).

## T054: Market capitalisation check (2026-10-24)

`company-facts` and `detect` as above; market cap at T exists for 92.0% of priced events. For SC-005, `ops.market_cap_examples` holds 10 single-class, Yahoo-priced event companies with shares filed since 2026-04-01, two per market-cap quintile of 2,202 candidates, drawn with seed 20261024. `sentinel audit market-caps` (`audits/market_caps.csv`, Yahoo values stored under `data/raw/yahoo/market_cap/`):

| Ticker | Ours ÷ Yahoo | Ticker | Ours ÷ Yahoo |
|---|---|---|---|
| JELD | 1.015 | PRCH | **1.167** |
| NSPR | 0.985 | PENG | **1.204** |
| LYTS | 0.989 | CVCO | 1.008 |
| RMBI | 1.048 | VTR | 0.997 |
| INVA | 0.999 | PFE | 1.002 |

**8 of 10 within 5%; both misses explained.** Prices agree (the same 23 Oct close); the share counts differ. Porch Group's own cover page (10-Q filed 2026-07-29) states 131,832,044 shares, Yahoo uses 113,519,836; Penguin Solutions' 10-K filed 2026-10-20 states 60,241,423, Yahoo uses 51,242,699. The pipeline follows the issuer's own latest filing, as plan §7.2 specifies.

## T060 (free part): Trading costs (2026-10-24)

`cap uv run sentinel costs`: 14,639 priced events, 14,515 with a cost (124 with fewer than 40 returns), median round trip **0.73%**; 233 on tick-pilot days; 1 s, peak 854 MB. `costs.md` (development events):

| As-traded price at T | Events | Cost (median) | Cost (IQR) |
|---|---|---|---|
| below $2 (failed only the price floor) | 670 | 3.43% | 2.10–5.37% |
| $2–3 | 311 | 2.32% | 1.09–3.88% |
| $3–5 | 533 | 1.68% | 0.81–3.16% |
| $5–10 | 1,264 | 1.23% | 0.55–2.40% |
| $10–20 | 2,166 | 0.70% | 0.25–1.68% |
| $20–50 | 3,008 | 0.49% | 0.13–1.28% |
| $50+ | 2,226 | 0.26% | 0.05–1.00% |

- **Jumps at a price other than $2**: none, so the data support the $2 floor.
- **Corwin–Schultz cross-check**: median CS ÷ AR 0.77, rank correlation 0.31.
- Tiingo-priced events get costs after T022.

## T067 (so far): Peak memory per step (2026-10-24)

Cgroup peak (`systemd-run --user -p MemoryMax=5G -p MemorySwapMax=1G`, RAM plus file cache), DuckDB capped at 3 GB:

| Step | Peak | Time |
|---|---|---|
| `fetch-headers --retry-failures` (3,677 headers) | 415 MB | 1 h 16 min |
| `prices` | 4.0 GB | 32 s |
| `reference` | 956 MB | 5 s |
| `company-facts` | 3.6 GB | 2 min 36 s |
| `detect --fetch-missing-headers`, three fetch rounds | 3.1 GB | 1 h 18 min |
| `detect` (final run, 853 headers) | 1.9 GB | 8 min |
| `delistings` (Yahoo issuers only) | 1.5 GB | 4 s |
| `costs` · `coverage` | 854 MB · 205 MB | 1 s each |
| `pytest -m slow` (prices, truncation) | 3.8 GB | 25 s |
| `pytest` (offline suite) | 1.0 GB | 1 min 20 s |
| `pytest -m slow` offline rebuild rehearsal (all steps, scratch warehouse) | 5.0 GB, 359 MB swap | 8 min 40 s |

All are under 5 GB (SC-009). The 23 Oct downloads (`fetch-prices --source yahoo`, `fetch-reference`, `fetch-company`) ran outside a cgroup, so they have no recorded peak; they stream to disk. Still to record: the Tiingo pull, `delistings` with Tiingo, and `build`.

## T066 (rehearsal): Offline rebuild (2026-10-24)

`systemd-run … unshare -rn uv run --offline pytest -m slow tests/integration/test_rebuild_identical.py --basetemp=data/rebuild_tmp/run`: every step from feature 002's staging to `costs`, into a scratch warehouse, with no network namespace; then each of the 25 feature 004 tables compared with the live warehouse as multisets. The scratch folder is on disk because `/tmp` is a 4.9 GB tmpfs. Three findings, each fixed before the next run:

| Run | Result | Cause and fix |
|---|---|---|
| Before running | `detect` would stop on "missing headers" | Fetch failures lived only in `core.header_failure`: now also in `data/raw/sec/headers/failures.csv` (see T037 above) |
| 1 | `core.price_daily`: 22 rows differ, all VIVK (stacked reverse splits, factor 5.7e-6), in the 10th significant digit | A window `product()` multiplies in a run-dependent order, and the last bit decided a rounding. `cum_split_after` is now `exp` of an exact DECIMAL(38, 18) sum of logs |
| 2 | `evt.event_candidate`: 289 rows differ in the last bit of `addv20` | Float `sum()` order. `addv20` now uses `warehouse.exact_sum`; the cost step's two spread means and the volatility (now two passes: mean, then squared deviations) use exact sums at scale 18 (`exact_sum` gained a `scale` argument) |
| 3 | **Pass**: all 25 tables identical; 8 min 40 s; peak 5.0 GB with 359 MB swap | — |

Every rebuild of the live tables after these fixes gave unchanged counts (events A 4,926, B1 2,542, B2 7,171; 14,515 costs, median 0.73%). The official T066 run follows T022, with Tiingo data, before the paid month ends. The memory peak is at the 5 GB ceiling: close the second VS Code window first, and if it still reaches the ceiling, raise WSL to 14 GB and the cap to 7 GB.
