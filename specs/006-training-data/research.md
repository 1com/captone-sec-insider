# Research and Decisions: Training Data (Labels, Features, ML Dataset)

**Feature**: [spec.md](spec.md) | **Plan of record**: `docs/initialplan.md` §6.6, §6.7, §7.2, §8.5, Appendix E

The plan fixes the method. This file records the details it leaves open, each decided **before** `prereg-v1`, so that no choice is made after seeing a return. Together they form decision entry **D53** in plan §12, approved with D45–D52 (task L.2).

## R1. The lock guard

- **Decision**: `sentinel labels`, `sentinel features` and `sentinel ml-dataset` stop with exit code 7 unless the git tag `prereg-v1` exists and `config/params.yaml` is byte-identical to its version at the tag. The guard sits in the CLI steps (also used by the offline rebuild); unit tests call the build functions on synthetic warehouses.
- **Rationale**: constitution III: no post-event return before the tag. Labels are post-event returns, and F10 uses past purchases' returns.
- **Alternative rejected**: checking the remote tag (needs the network; the offline rebuild must work).

## R2. Entry, exit and adjusted prices

- **Window**: entry at the adjusted open of session T+1 (`evt.event.entry_session`); exit at the adjusted close of session T+H, where T is `t_session` (the last session on or before the signal date) and session numbers come from `core.session`. H ∈ {5, 21, 63, 126, 252} (registered).
- **Adjusted prices** from `core.price_daily`: split-adjusted price = as-traded ÷ `cum_split_after`; the dividend factor of a day is `adj_close` ÷ split-adjusted close; adjusted open = split-adjusted open × that factor.
- **Unusable entry open** (zero, missing, or outside the day's low–high range, plan §8.5): entry at that session's adjusted close instead, flagged `entry_at_close`.
- **Gaps**: the exit price is the last adjusted close on or before the exit session.
- **Benchmarks SPY and IWM**: the same entry and exit sessions, from their Yahoo rows (adjusted open = open × `adj_close` ÷ `close`).

## R3. The industry benchmark

- **Decision**: the issuer's industry is the Fama–French 49 industry of `evt.event.g7_sic` (the SIC at T). SIC codes in no 49-industry range (for example 3990, 0000) go to industry 49 "Other", as the French library does for unclassified firms. The window return compounds the daily industry returns of sessions T+1 … T+H (close-to-close; the extra overnight move is documented in plan §6.6). Equal-weighted is primary; value-weighted is kept as a check.
- **F24** uses the 12-industry scheme the same way (industry 12 "Other").

## R4. The factor-model measure (FF5 + UMD)

- **Decision**: ordinary least squares of the stock's daily excess return (adjusted close-to-close minus `rf`) on `mkt_rf`, `smb`, `hml`, `rmw`, `cma` and `mom`, with an intercept, over sessions T−252 … T−21, needing at least 120 days with a stock return (registered). The abnormal return of a day is the excess return minus β′f, **without the intercept**: insiders tend to buy after falls, so a pre-event alpha would carry that drift into the expected return. CAR = sum of the daily abnormal returns over T+1 … T+H; day T+1 is measured open-to-close.
- **Missing**: fewer than 120 days, or a window day without factors, gives no CAR.

## R5. Delisting inside the window

- **Trigger**: the issuer's last price row is before the exit session.
- **Return**: the stock earns its buy-and-hold return to its last close, then the delisting return of `core.delisting` (by class and venue, registered values), then the benchmark for the rest of the window: BHAR = (1 + Rb_rest) × [(1 + Rs_to_end)(1 + DLR) − (1 + Rb_to_end)]. For CAR, the delisting return is added as the abnormal return of the last session, and later days add zero.
- **No row in `core.delisting`**: the unknown-class return of the venue (the registered rule).
- **Bounds**: each label row also holds the gross value with the delisting return set to 0% and to −100% (plan §6.7).

## R6. Net returns and the target

- **Net** = gross − the event's round-trip cost (`evt.event_cost.cost`). When the cost is null (fewer than 40 returns), net and the target are null and the event is counted, not imputed.
- **Target**: y = 1 if the 63-session net BHAR against the equal-weighted industry > 0 (plan §6.6).

## R7. The development boundary

- **Decision**: a label row exists only when its exit session is on or before 31 December 2022 and the signal date is on or after 1 January 2012. Holdout labels are written only by the guarded Step 18 job, into `hold`.
- **Events**: every priced event of groups A, B1 and B2 (the event study uses all three; the dataset uses A).

## R8. Purchase outcomes for F10

- **Decision**: `lab.purchase_outcome` holds, for every priced clean purchase (`core.priced_purchase`, G8 not failed), the 63-session BHAR against the equal-weighted industry from the open of the session after its filing date, net of the cost model evaluated at that filing date (same formula and inputs as `evt.event_cost`). Only windows ending by 31 December 2022.
- **F10** for an event at T: for each buyer entity, n = its earlier priced clean purchases at this issuer whose windows ended before T and whose net is known, h = those with net > 0; the entity's rate is (h + k·p̄) ÷ (n + k), k = 5; F10 = mean over the event's buyers. p̄ = the base rate of the primary label: the share of events (any group, any issuer) whose 63-session industry-adjusted net BHAR is > 0, among windows ending in the 36 months before T; 0.5 if there are none. The benchmark of a buyer's past purchase is the event's industry at T, so no later industry code is used.
- **Holdout events**: F10 is null here and filled by the guarded job.

## R9. Insider features

- **Buyers** are the event's entities (`evt.event_member`), with roles at T.
- **F3**: the largest entity's summed value ÷ the event total.
- **F4–F6**: entities whose role at T is `ceo_cfo`, `director` and `ten_pct` (one role per entity, its most senior).
- **F7**: per buyer, log(shares after its last purchase in the window ÷ shares before its first), using the summed holdings of `core.clean_purchase`; buyers with zero or unknown holdings before are left out; null if no buyer qualifies.
- **F8**: buyers whose first purchase in the window opens a position.
- **F9**: each owner on the event's purchase filings is classified at 1 January of T's year from their open-market purchases and sales at this issuer (codes P and S, original Forms 4, by trade date) in the three previous calendar years: *routine* if they traded in the same calendar month in each of the three years, *opportunistic* if they traded in each of the three years but not routinely, otherwise unclassified. An entity is opportunistic if any classified member is, routine if all classified members are; F9 = opportunistic share of classified buyers, null if none.
- **F11**: mean of (filing date − trade date) over the member filings' purchase lines.
- **F12**: value of code-S lines on original Forms 4 at the issuer filed in the 90 days before T (T − 90 < filing date ≤ T), any insider.
- **F13**: 1 if any of those sales was by an owner whose role at the sale's filing date was `ceo_cfo`.
- **F14**: clean purchase filings at the issuer filed in the 365 days before T, excluding the 14-day event window.
- **F15**: days since the latest 10-Q or 10-K (any amendment or transition form) filed on or before T; null if none.

## R10. Market and company features

- **F16, F17, F22, F23**: market cap, ADDV20, volatility and spread exactly as stored at T (`evt.event`, `evt.event_cost`).
- **F18** = F2 ÷ F17; **F25** = F2 ÷ F16.
- **F19**: adjusted return from session T−21 to T; **F20**: from T−252 to T−21 (last available prices on or before those sessions, null if the series starts later).
- **F21**: split-adjusted close at T ÷ the highest split-adjusted high over sessions T−251 … T; null with fewer than 63 sessions.
- **F26–F29**: per concept, the value of the latest period whose first filing date is on or before T (`core.xbrl_fact` holds first-filed values only). F26 = equity ÷ F16; F27 = 1 if the latest net income (shortest period when several end on the same day) is negative; F28 = liabilities ÷ assets, with liabilities = assets − equity when missing; F29 = cash ÷ assets.

## R11. The ML dataset

- **Rows**: group A events with a target (R6, R7).
- **Fixed preprocessing** (plan §7.2): F2, F12, F16 and F17 divided by SPY's close at T, then log(1 + x) so that zero sales stay defined.
- **Folds**: test years 2019, 2020, 2021, 2022 (registered as `rules.ml_test_years`). For test year Y starting on date S, the training window holds events whose 63-session window ends before S. Calibration slice: signal dates in [S − 6 months, S); tuning slice: [S − 12 months, S − 6 months); fit set: before S − 12 months. **Purging**: an event of the fit set is kept only if its window ends before the tuning slice begins, and one of the tuning slice only if its window ends before the calibration slice begins; others are marked `purged`.
- **Fold 1** is dropped if its fit set has fewer than 500 events (registered).
- **Weights**: each event's average uniqueness = mean over the sessions of its window of 1 ÷ (number of priced A events whose windows include that session); stored raw, and normalised to mean 1 within each fold's training window. The effective sample size (Σw)² ÷ Σw² is reported per fold.
- **Version**: each build writes `ml.dataset_version` (git commit, parameter-file hash, row counts) and a Parquet copy under `data/ml/`.

## R13. The multi-horizon table (D54)

- **Decision**: `ml.dataset_horizon` holds every group A cluster at each horizon in `rules.ml_horizons` (21, 63, 126, 252) that has a net label: the same 29 inputs, `horizon`, `y`, `net`, `gross`, `window_end` and `uniqueness` of that horizon's own window (the average over the window's sessions of 1 ÷ the number of priced A events whose windows of the same length cover it). `ml.dataset_horizon_fold` gives each (fold, event, horizon) its part, purged by that horizon's `window_end`, with weights normalised to mean 1 per fold and horizon. `ml.dataset_horizon_summary` reports events, positives and effective size per fold, horizon and part.
- **Model (Steps 15–16)**: one model per family on the stacked table with `horizon` as an input; weights as stored; selection by the registered log-loss and one-standard-error rule, with the extra trials counted.
- **Not a confirmatory result**: `ml.dataset` and the primary tournament are unchanged; everything from this table is exploratory.
- **Known limit**: events whose window would end after 31 December 2022 have no label at that horizon, so the 126 and 252 horizons lose the last months of 2022 (and more of the 2022 fold); the summary shows it.
- **Rounding**: weights and summaries use exact sums, so a rebuild gives identical rows (a version hash check found the float version failing).

## R14. Explanations by a language model (D55)

- **Scope**: the product only (task 8.4); never the research, never the dataset.
- **Inputs**: a fact sheet per event: company, date, buyers and roles, total value, F-values in words, score band, the top three drivers in words, the holdout hit rate and median net return by horizon for the band, caveats. No raw prices.
- **Output rules**: 80–150 words; plain English; only numbers present in the fact sheet (checked by a validator that extracts every number and matches it); no advice, no certainty; the words "research, not investment advice" are added by the template, not the model.
- **Storage**: `ml.explanation` (event, text, model id, prompt hash, fact sheet hash, created); regenerated only when the fact sheet changes.
- **Failure**: API error or failed validation: the template sentence.

## R12. Tiingo-derived rows

- **Decision**: every label, purchase outcome and price-based feature carries `price_source`; the tables are added to the Tiingo register (constitution VI; the researcher keeps the data, but the register stays complete).
