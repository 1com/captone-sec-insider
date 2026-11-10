# Roadmap: v2 to 17 November

The plan of record. Updated together with the README's summary and the GitHub issues (one per
feature, in five milestones). Working days Monday to Friday; the weekends of 31 Oct – 1 Nov,
7–8 Nov and 14–15 Nov are buffer. A feature is done when its tests pass, its named real-data checks
pass and its owner and the researcher have seen a plain summary.

## Team

| Who | Role |
|---|---|
| Researcher (`1com`) | owner of the project and its decisions; builds the **app and front end** |
| Teammate (`sonson033`) | builds the **data-science** track: EDA, the three models, the report |
| Coding agent (Claude Code) | builds the **data platform**; helps both tracks |

## How the tracks fit together

Three tracks run in parallel and meet only at three written contracts, so no one waits on another:

| Contract | Written by | Read by | Where it is defined |
|---|---|---|---|
| The training export: `data/exports/ml/*.parquet` (and `reference/` from 002) | data platform | data science | `data/exports/README.md` (generated), `docs/architecture.md` |
| The serving copy: `data/serving.duckdb`, schema `app` | data platform | app | `docs/architecture.md`, layer 6 |
| The forecast contract: the table and columns each forecast is published in | app (011), agreed with data science | app; filled by 009 | `specs/011-app-design/contracts/` |

The app is built against the serving copy as it is today, with forecast panels as placeholders;
when the daily scores (009) land, the placeholders fill without changing the pages.

Every feature has a fixed number; its spec-kit folder and branch use it (`specs/NNN-name/`,
branch `NNN-name`), so two people specifying at once never collide.

## Next steps (keep this list current)

1. **001 done (5 Nov, #91):** the first scheduled run with the fixes `complete` in 47 minutes,
   `sentinel verify` identical, a rerun `nothing_new`; the schedule stays at weekdays 10:00; the
   EDA notebooks re-run on the new data.
2. **007, then 006, then 005 if time allows (V2-48)**, each redone in its notebook and approved by
   the researcher: spec-kit first; splits by `eda.folds` and `eda.check_folds`; every model,
   calibration, band edge and range a `sentinel.models.dated.Dated` (V2-49: it learns only from
   answers known before its cutoff and forecasts only rows dated after it); four levels (naive,
   rule, classic, LightGBM) on 2019–2022; the simplest within one standard error of the best;
   bands with their test-year hit rates (D47); a verdict per hypothesis (V2-46); MLflow runs with
   the commit and the export date. 007 is Jassin's notebook (V2-40); 006 has no `cum_split_after`
   and is chosen by the chances' log loss (V2-41).
3. **The approved models into `src/sentinel/models/`** with tests and a command; the notebooks
   import them and give the same numbers; a dry run on the 2023+ feature rows (no answers); the
   daily scores back on (`update.score`, V2-42).
4. **008 report** from the MLflow runs of the approved models (#79).
5. **010 holdout test (16 Nov)**: the guarded command, run once by the researcher, for every model
   frozen by then.
6. **011–018 app** with the researcher: the faults found on 4 Nov (AGENTS.md section 7); no
   Tiingo-derived value on a public page.
   With it, **025**: the unusual-volume tracker (V2-51).
7. **019 hand-in** (17–18 Nov); **020** before the Tiingo plan ends (25 Nov).

## Notebooks and code

- **Notebooks** (`notebooks/NNN-topic.ipynb`, numbered by feature) are where the EDA is done and
  where each model is built, run and tuned, with its tables and charts, so the researcher can
  follow and approve each choice (researcher, 30 Oct). They read the private Parquet export in
  `data/exports/`, run start to finish by one command, never commit their
  outputs (stripped by `nbstripout`; CI rejects a notebook with outputs: the repository is public
  and an output cell could publish Tiingo-derived values), and never write to `data/`.
- **Once the researcher approves a model, its code moves to `src/sentinel/models/`** and runs by
  command: training, the walk-forward test, calibration and daily scoring, with fixed seeds and
  MLflow logging, because `sentinel update` scores every company each night without a notebook
  and the repository must run from a clone. The model's notebook then imports this code and gives
  the same numbers.
- **Reports** (004, 008) may be notebooks if one command runs them start to finish
  (`jupyter nbconvert --execute`), so they regenerate from the data.
- **The app reads `data/serving.duckdb`** (read-only, reopened after each night's update), not the
  Parquet copies in `data/exports/app/`, which are for sharing and analysis.

## Data for each model

Every training set is a Parquet file in `data/exports/ml/` (private, written by `sentinel export`,
column list in the generated `data/exports/README.md`). One row per company and date; the features
come first, the answer last. Train and test only on rows where the question's flag is true (`eligible_volatility`, `eligible` for
the results move, `eligible_dilution`: V2-26, V2-27) and the answer is present. Never use the answer columns, `window_end` or the outcome columns as features.

| Model (feature) | File | Rows are | Answer | Naive baseline to beat | Excluded from the features |
|---|---|---|---|---|---|
| Volatility (005) | `ml/volatility.parquet` | month-ends, 2012 – Sep 2022 | `vol_63_future`: annualised volatility over the next 63 sessions (model its log) | `vol_63`, the past 63 sessions | `vol_63_future`, `window_end` |
| Results-day move (006) | `ml/results_move.parquet` | one per results release (the eve's features), 2010–2022 | `move`: market-adjusted absolute move | `prev4_mean`, the mean of the previous four moves (`n_prev` of them) | `move`, `close_after`, `filing_date`, `report_date`, `prev4_mean` as a feature only if declared |
| Dilution (007) | `ml/dilution.parquet` | month-ends, 2012 – Jun 2022 | `dilution`: shares up 10% or more within 182 days (true in about 10% of the learnable rows) | the base rate; then a rule | `dilution`, `window_end` |

- **Evaluation** (D60, `config/risk_params.yaml` v5, never edited): yearly walk-forward test years
  2019, 2020, 2021, 2022; training rows whose answer window ends after a test year starts are
  purged (`window_end`; for results moves the session after `filing_date`). Levels: rule, classic
  model, LightGBM; pick the simplest within one standard error of the best. Forecasts as bands or
  chances with hit rates (D62). Runs logged in MLflow; fixed seeds.
- **Scoring today:** `ml/latest.parquet` holds each company's newest row (the same feature
  columns). `ml/feature_snapshot.parquet` holds every feature row without answers.
- **Holdout:** rows from 2023 on have no answers in `ml/`. Never use them to build or choose a
  model; feature 010 tests once. The private `reference/` copies (002) hold every year's answers
  for personal analysis only.
- **Feature definitions:** `src/sentinel/features/` and `docs/architecture.md` (layer 4); answer
  definitions: `src/sentinel/labels/risk.py` and `config/risk_params.yaml`.

## Timeline

| Week | Data platform | Data science | App |
|---|---|---|---|
| Thu 29 – Fri 30 Oct | 001 daily refresh; 002 reference datasets; 003 team workflow and CI | (data shared privately) | 011 app design starts |
| Mon 2 – Fri 6 Nov | support | 004 EDA; audit (4 Nov); 001 checked; 007 dilution (V2-48) | 011 contract agreed; 012 API; 013 stock page |
| Mon 9 – Fri 13 Nov | support | 006 results-day move; 005 volatility if time (V2-48); 008 report; 009 daily scores | 014 insider tracker; 015 dilution check; 016 screeners; 017, 018 start |
| Mon 16 – Wed 18 Nov | | 010 holdout test (Mon) | 017 forecasts; 018 hosting; **product v1 on Tue 17**; **report on Wed 18** (019) |
| by Wed 25 Nov | 020 offline rebuild and raw backup | | |

## Features

### v2 · 1 Data platform (due 2026-10-30)

| # | Feature | Owner | Dates | Depends on | Done when | Status | Issue |
|---|---|---|---|---|---|---|---|
| 001 | **Daily data refresh and update**: A fetch command per source (SEC filings and financial values through the daily master index, the SEC ticker list, Form 3/4/5 filings as filed, Yahoo for every listed symbol plus SPY and IWM, Tiingo while the plan lasts, FRED, Cboe VIX, FINRA short volume); the one-off refresh; `sentinel update` (fetch what is new, re-stage changed sources, rebuild the upper layers, publish, export, record the run in `ops`); `sentinel status`, `verify`, `schedule` (weekday evenings). | coding agent; researcher (1com) approves the schedule | Thu 29 – Fri 30 Oct | — | every table reaches the last completed session; a rerun the same day is `nothing_new`; `sentinel verify` finds every table identical; the daily Form 4 parser matches the 2026q3 data set; named real checks pass; the schedule runs on two weekday evenings | done (5 Nov, #91): the scheduled run `complete` in 47 min (60 allowed, V2-47), `sentinel verify` identical, a rerun `nothing_new`; schedule kept at weekdays 10:00 | #68 |
| 002 | **Reference datasets with every year (private)**: Private reference copies per question (volatility, dilution, results-day move) for personal data-science work: every year to the latest day in the training files' exact layout, answers wherever the window has closed (the 2023–2026 holdout included), a `period` column (development / gap / holdout); `sentinel export --reference` → `data/exports/reference/` (git-ignored, Tiingo-derived: never published). The models never read them. Constitution IV amended, decision V2-21, disclosed in the report. | coding agent | Fri 30 Oct | 001 | three files with the training files' columns, types and order plus `period`; their development rows equal the training rows; tests | done | #73 |
| 003 | **Team workflow and CI**: Two people and an agent working in parallel: GitHub Actions running `ruff check`, `ruff format --check` and the unit tests on every pull request; `main` protected (pull request with green CI); a pull-request template (feature number, tests, data never committed); the README's "Working together" section; the teammate added as collaborator; how the private data is shared (not through git). Notebooks: a `notebooks/` folder; `nbstripout` as a git filter and a CI check that rejects any notebook with saved outputs (the repository is public and outputs could show Tiingo-derived values). | coding agent | Fri 30 Oct | — | a pull request from each person passes CI and merges into `main` | done except protecting `main`; no pull requests used since #90 (audit, 4 Nov) | #75 |

### v2 · 2 Data science (due 2026-11-13)

| # | Feature | Owner | Dates | Depends on | Done when | Status | Issue |
|---|---|---|---|---|---|---|---|
| 004 | **EDA and data-quality report**: Explore the development rows (2012–2022) of the three training sets in `data/exports/ml/`: coverage by year, sector, size and filer type; missing values per feature and why; outliers; answer distributions and base rates; feature–answer relations; leakage checks. A cleaning rule found here goes into the pipeline (it then applies to every year alike). The holdout years are not explored. | coding agent, with the researcher (the researcher's request, 30 Oct) | Fri 30 Oct | 001 | the report is generated by a command from the export; findings and any new cleaning rules (with tests) are logged in `docs/decisions.md` | done on its branch: notebooks and findings; cleaning rules V2-22 to V2-24 decided and in the pipeline; V2-25 to V2-27 await decisions; merges after 001 | #76 |
| 022 | **Validation round on named cases** (researcher, 30 Oct; V2-25): values that look normal but may be wrong, checked against the SEC filings and Yahoo for named companies: extreme returns (missing splits?), splits inside a dilution window, 5–6 results releases a year, share counts wrong from a company's first filing, insider trades no rule can judge, absurd Tiingo prices of small OTC stocks, the 194 companies where Yahoo and Tiingo disagree. Each real problem becomes a proposed rule for the researcher; accepted rules go into the pipeline with tests. | coding agent, with the researcher | Fri 30 Oct – Mon 2 Nov | 004 | `notebooks/022-validation.ipynb` with a pass/fail table per check and case; proposals logged; accepted rules implemented, rebuilt, EDA re-run | done on its branch: V2-28 to V2-32 in the pipeline; cleaning frozen (V2-33) | — |
| 023 | **Options benchmark and live track record** (requested 3 Nov): Yahoo option chains for any stock across all expirations for the next 365 days; raw snapshots stored in `data/raw/options/` with manifest lines; relational tables `core.option_chain` and `core.option_summary`; 3-month ATM implied volatility benchmark for Model 005; CLI `sentinel options <ticker>` and API `/api/options/{ticker}`. | coding agent | Tue 3 Nov | 001 | option chains fetched and stored in DuckDB; ATM IV benchmarks computed; API and CLI operational; tests pass | merged; spot price wrong (falls back to the median strike); tables in schema `live` (4 Nov) | — |
| 024 | **Offering-event question** (proposed 30 Oct; the researcher: possible extra after 007): "will the company file a share offering in the next 6 months?" (an offering prospectus 424B1/B3/B4/B5 that is not a debt deal, or a registration taking effect), whatever its size, from the SEC filings already staged; shown beside the 10% dilution chance. The 10% definition stays for 007 (pre-registered; routine creep from employee stock makes "any rise" uninformative: 67% of rows rise in a year, median 0.6%). A new question needs a logged decision before any of its results | coding agent, with the researcher | not scheduled | 007 | a label, a model under D60's evaluation, a band in the app | not started | — |
| 025 | **Unusual-volume tracker** (V2-51, researcher, 5 Nov): each day, stocks whose volume is far above their own normal (the median and a robust spread of the previous 63 sessions; at least 3× the median), for stocks above the trading floor; a table in the feature layer (not a model input), published to the app: on the stock page and as a market-wide list, Yahoo-priced stocks only on public pages | coding agent | Thu 12 – Fri 13 Nov, after 006 | 001 | the daily update fills it; the truncation test covers it; `sentinel verify` identical; the app shows it | not started | — |
| 005 | **Volatility model**: Expected volatility over the next three months under D60 and `config/risk_params.yaml` v5: the naive baseline (the past 63 sessions), a rule, a classic model and LightGBM on purged walk-forward test years 2019–2022; the simplest level within one standard error of the best; the 80% range calibrated on all earlier years (V2-10); MLflow runs with git commit and data version; deterministic. | teammate, with coding agent | after 006, if time allows (V2-48) | 004 | two runs give identical predictions; the results table is generated; the researcher and teammate approve the level | last, if time allows (V2-48); redo (audit, 4 Nov). Built 9 Nov: V2-56 (mean absolute log error), V2-57 (no macro in the models, after the first run); LightGBM chosen (0.279 against 0.346 for the baseline, best every year), range coverage 72–88%; approved 9 Nov (V2-58), packaged in `src/sentinel/models/volatility.py` with tests (the notebook gives the same numbers); merged by #96 (9 Nov) | #67 |
| 006 | **Results-day move model**: The expected size of the next results-day move (one row per release): baseline = the mean of the company's previous four moves, then rule, classic model, LightGBM as in D60; bands with hit rates (D62); MLflow; deterministic. | teammate, with coding agent | Mon 9 – Wed 11 Nov | 004 | two runs give identical predictions; the results table is generated; the level is approved | redo (audit, 4 Nov): evaluated with the look-ahead input `cum_split_after`; packaged model never evaluated; not approved. Restarted 9 Nov: spec and plan rewritten (V2-53, V2-54; design check on 2016–2018); approved 9 Nov (V2-55): LightGBM, mean log loss of the three chances 0.404 against 0.409 for the ridge, better every year; packaged in `src/sentinel/models/results_move.py` with tests (the notebook gives the same numbers); merged by #94 (9 Nov) | #77 |
| 007 | **Dilution model**: The chance that shares outstanding rise 10% or more within six months (base rate about 10% on the rows models learn from): baselines, rule, classic model, LightGBM as in D60; calibration; the chance shown in bands with hit rates; MLflow; deterministic. | teammate, with coding agent | Thu 5 – Sat 7 Nov (first, V2-48) | 004 | two runs give identical predictions; calibration checked; the level is approved | approved 5 Nov (V2-52): LightGBM, log loss 0.225 against 0.302 for the offering rule, better in every test year; packaged in `src/sentinel/models/dilution.py` with tests (the notebook gives the same numbers); merged by #92 (9 Nov) | #78 |
| 008 | **Model report and model card**: A generated report: the data, the methods, walk-forward results per question against the baselines, calibration, the chosen levels and why; the test hit rates that feed `app.model_card`. | teammate, with coding agent | Thu 12 Nov | 005, 006, 007 | one command regenerates the report from the data and MLflow runs | 9 Nov: rebuilt: the model notebooks record their tables in MLflow, `sentinel report` writes `docs/report/` (Markdown, figures, `model_card.json`) from them, no number typed in; Gemini's typed-in report removed; pull request next | #79 |
| 009 | **Daily scores and live outcomes**: Each day's forecasts from the chosen models inside `sentinel update`: `score.daily` (every forecast: company, question, model version, value, band, coverage level; append only), `score.outcome` (each forecast's outcome once its window closes: live hit rates), published in the columns the forecast contract (011) fixes. | coding agent, with teammate | Thu 12 – Fri 13 Nov | 005–007; the forecast contract of 011 | an update scores every covered company; a rerun the same day changes nothing; `sentinel verify` identical | in progress: scoring runs in the update with unapproved models; live outcomes wait for 010 | #74 |

### v2 · 3 App (due 2026-11-16)

| # | Feature | Owner | Dates | Depends on | Done when | Status | Issue |
|---|---|---|---|---|---|---|---|
| 011 | **App design and forecast contract**: The front-end stack; the page map and wireframes (search, stock page, dilution check, insider tracker, screeners, model card, "data as of"); the **forecast contract** with the data-science track: the table and columns the app reads for each forecast (value, band, chance, hit rate, model version, as of), so pages can be built before the models exist. The app reads only `serving.duckdb`. | researcher (1com), with coding agent | Fri 30 Oct – Mon 2 Nov | — | the contract is written under `specs/011-app-design/contracts/` and agreed by both tracks; wireframes approved | not started | #80 |
| 012 | **API over serving.duckdb**: Read-only endpoints (FastAPI): search, stock, prices, financials, filings, insider activity and feed, screener, freshness, model card. Port 8000 on the development machine belongs to another application. | researcher (1com), with coding agent | Tue 3 – Wed 4 Nov | 011 | endpoint tests pass on a synthetic serving copy | not started | #81 |
| 013 | **Stock page**: Search and the stock page: header, price chart, financials as first filed, the filings timeline in plain English, insider activity, "data as of"; forecast panels as placeholders per the contract (filled in 017). | researcher (1com), with coding agent | Thu 5 – Fri 6 Nov | 012 | page tests; the numbers match `serving.duckdb` for named companies (Apple, Meta, Hitachi) | not started | #70 |
| 014 | **Insider tracker pages**: The market-wide feed of insider events (several buyers, a CEO or CFO, an officer or director), buys and sells per company with role, value, plan and offering flags, holdings before and after, links to EDGAR. | researcher (1com), with coding agent | Mon 9 – Tue 10 Nov | 012 | page tests; Jamie Dimon's 2016 purchase shows correctly | not started | #82 |
| 015 | **Dilution check**: A standalone page for any ticker: share-count history, recent offerings, cash runway, and the dilution chance once 009 publishes it. | researcher (1com), with coding agent | Wed 11 Nov | 012 | page tests; a known diluting company shows its offerings | not started | #83 |
| 016 | **Screeners**: Filter stocks by risk band, sector, size and insider activity (extras are cut first if time runs short). | researcher (1com), with coding agent | Thu 12 Nov | 012 | page tests; filters match SQL on `app.screener` | not started | #84 |
| 017 | **Forecasts and model card in the app**: Volatility and the results-day move lead the stock page; dilution on its check; each forecast as a band or chance with its past hit rates (D62), never a bare number; the model card page. | researcher (1com), with teammate | Fri 13 – Mon 16 Nov | 009, 013 | pages show the live scores; the model card matches the report | not started | #85 |
| 018 | **Hosting and public-data rule**: Where the app runs and how it is deployed (by command); public pages never show Tiingo-derived values; a smoke test after each deploy. | researcher (1com), with coding agent | Fri 13 – Mon 16 Nov | 012 | the app is reachable at its address; the smoke test passes; no Tiingo-derived value is served publicly | not done: Docker files exist, but Tiingo-derived prices are served and nothing is deployed (audit, 4 Nov) | #86 |

### v2 · 4 Holdout and hand-in (due 2026-11-18)

| # | Feature | Owner | Dates | Depends on | Done when | Status | Issue |
|---|---|---|---|---|---|---|---|
| 010 | **Risk holdout test**: The one test of the chosen models on windows starting in 2023 or later: a guarded, logged run (constitution IV); the results go into the report as they came out. | researcher (1com) triggers; teammate and coding agent build | Mon 16 Nov | 008 | the guard log shows a single run; the report shows the results | not started | #69 |
| 019 | **Report and hand-in**: Product v1 on 17 November; the report on 18 November; both generated by commands from a clone plus the data. | researcher (1com), teammate, coding agent | Tue 17 – Wed 18 Nov | 008, 010, 017 | both handed in | not started | #71 |

### v2 · 5 Before Tiingo ends (due 2026-11-25)

| # | Feature | Owner | Dates | Depends on | Done when | Status | Issue |
|---|---|---|---|---|---|---|---|
| 020 | **Offline rebuild and raw backup**: Before the Tiingo plan ends (26 Nov): fetch commands for the sources still missing one (the French industry files, the first Tiingo download per company); a fresh clone plus the stored raw files rebuilds every layer, the serving copy and the export identically (constitution V); `data/raw/` backed up to a second disk or private storage. | coding agent | by Wed 25 Nov | — | the rebuild from a clean clone is identical to the working copy; the backup exists | not started | #72 |


### v2 · 6 After hand-in (due 2027-01-29)

| # | Feature | Owner | Dates | Depends on | Done when | Status | Issue |
|---|---|---|---|---|---|---|---|
| 021 | **Quarterly model refit**: retrain each chosen model with the form and settings fixed in development on every answer whose window has closed (after the holdout test, the 2023+ answers may be used); compare with the current version on the most recent data; replace only if no worse, as a deliberate, logged step (D64, spec §7). Daily scoring (009) does not retrain: the frozen model scores each day's new feature rows, and outcomes give live hit rates | teammate, with coding agent; researcher approves each replacement | first refit January 2027 | 005–007, 009, 010 | a refit command produces a candidate, its comparison and a recorded decision; a replacement shows in `model.registry` and in the next day's forecasts | not started | #87 |

## Done before the roadmap (29 October)

Steps 0–4 (issues #62–#66): v1 retired and v2 started (V2-1, V2-2); every data layer built from the
raw files: staging per source, reference, core (prices, filings, financial values with `known_at`,
results releases, the insider tracker's tables, macro, short volume), features as of month-ends,
results eves and latest days (V2-13), development answers to 2022, `sentinel publish` and
`sentinel export`. Named checks pass (Jamie Dimon 2016, Tesla's 2022 releases, Apple's split day,
Meta, TSMC, a BDC, a closed-end fund, Bed Bath & Beyond). One price series per company: share
classes and ADR ratios are not modelled, so a foreign filer's market value is missing.

## Cut order (if a feature slips)

1. Filing-triggered updates during the day.
2. Volatility at 1 and 6 months.
3. The price-only coverage level's pages (prices still kept).
4. Mapping foreign filers' IFRS financials.
5. Screener extras beyond risk band, sector, size and insider activity.

## Questions settled on 29 October

The 50% fall forecast is dropped (V2-9); the volatility range is scaled on all earlier years
(V2-10); the price-only level is in (V2-11); v1's issues, tags and demo site are removed (V2-2,
V2-12); the daily refresh follows V2-16 to V2-20; the researcher asked for private reference copies
with every year's answers (002, to be logged as V2-21); the work splits into three tracks with the
researcher on the app and a teammate on data science.
