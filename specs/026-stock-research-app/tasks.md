---

description: "Task list for feature 026, the stock research app"
---

# Tasks: Stock research app, dilution first

**Input**: [spec.md](spec.md), [plan.md](plan.md). **Tests**: requested (FR-023, SC-004 to SC-007).
The researcher asked for a presentable MVP first (10 Nov); tasks after the MVP are marked "later".

## Phase 1: Setup

- [X] T001 Branch `026-stock-research-app`, the spec and its checklist; V2-61 in `docs/decisions.md`
- [X] T002 Lightweight Charts 4.2.0 vendored in `src/sentinel/web/static/`; V2-62

## Phase 2: Foundational

- [X] T003 `src/sentinel/web/data.py`: read-only queries, one connection per request, `NoData`
- [X] T004 `src/sentinel/web/glossary.py`: every form type with 100+ filings and every 8-K item
  (`tests/unit/test_web_glossary.py`)
- [X] T005 `src/sentinel/web/forecast.py`: the frozen model's chance, band and reasons per company
- [X] T006 `sentinel web` in `src/sentinel/cli.py` on port 8100, checked free

## Phase 3: User Story 1 - Look up a stock and judge its dilution risk (P1)

- [X] T007 [US1] Search (ticker, name, former names; reused tickers listed first) and company facts
- [X] T008 [US1] The dilution panel: chance, band, the band's record per test year, reasons, or why absent

## Phase 4: User Story 2 - Price and volume history (P1)

- [X] T009 [US2] Split-adjusted price and volume chart, periods, legend, insider and offering markers

## Phase 5: User Story 3 - Insider patterns (P2)

- [X] T010 [US3] Monthly bought and sold chart, pre-planned sales hidden on demand, the trade table
- [ ] T011 [US3] Clusters highlighted (later)

## Phase 6: User Story 4 - Filings in plain English (P2)

- [X] T012 [US4] Filings list with names, explanations, 8-K items, kind tabs, links

## Phase 7: User Stories 5-7

- [X] T013 [US5] Short-sale share of volume (FINRA), explained
- [ ] T014 [US5] Short interest as a new source (later; researcher, 10 Nov: built last)
- [X] T015 [US6] Key financials as first filed (12 Nov): `data.financials`, `/api/financials/{cik}` and
  the page's table (last statement dates and fiscal years: revenue, net income, cash from
  operations, cash raised by selling shares, cash, long-term debt, the cover page's share count;
  a quarter's three months, else the reported year-to-date total with its length; never zero for a
  number not reported); tests in `tests/unit/test_web_financials.py`; the named-case check gained
  a financials section (every value a first-filed value in the data: all 13 cases pass)
- [X] T016 [US7] Diagnostics: the data behind the page and the dilution model's workings

## Phase 8: Polish

- [X] T017 Tests: `tests/unit/test_web_app.py` (search, facts, split adjustment, insider totals,
  filings, no volatility or results-day forecast, missing serving copy)
- [X] T018 Daily forecasts in the daily update (009, dilution only; V2-72, 12 Nov):
  `src/sentinel/scoring/daily.py` scores the companies still trading with the frozen approved
  model (V2-59) into `score.daily`, with every input's value and contribution; `sentinel publish`
  serves approved models' forecasts only (`app.daily_score`); the app reads them, never computes
  one, marks a forecast older than the company's data and says when a company in the question has
  none yet; `update.score` on. Tests in `tests/unit/test_daily_scores.py`, `test_serving.py`,
  `test_update.py`, `test_web_app.py`. On 12 Nov the dilution panel of all 6,922 current companies
  was identical before and after; the 13 named cases pass, now comparing every stored reason
  with the frozen model
- [X] T019 Ten named cases checked against the data (SC-002, SC-005): `src/sentinel/web/named_cases.py`
  (`python -m sentinel.web.named_cases`) compares every section of 13 named companies' pages, from
  the app's own endpoints, with the build database, the frozen dilution model and the SEC's files,
  and scans the template and scripts for typed-in dates; writes `docs/report/app_named_cases.md`
  (verdicts only). 12 Nov: the first run found two wrong reasons for a missing forecast (a
  blank-check company, a listed company without prices), fixed in `web/forecast.py`; all 130
  checks pass; tests in `tests/unit/test_web_named_cases.py`
- [X] T020 Docs (README, `docs/plan.md`, AGENTS.md); pull request after the researcher agrees (the
  MVP merged by #101, 10 Nov; the shared password, V2-63 and the docs by a second pull request,
  11 Nov)
- [ ] T021 Remove the old app (011-017) once the researcher approves the new one (FR-024)
- [X] T022 V2-73 (13 Nov), found by the first scheduled run with forecasts (009 T013): a page
  without a forecast names each rule every question applies that the company fails
  (`risk_params.yaml` `panel`: price, trading value, trading days, a recent filing), with its own
  value and date (`web/forecast.py`, `rules_failed`), instead of "the data is not complete"
  (1,536 pages on 13 Nov); no forecast of a day the company was still in the question is shown
  (the served copy, 009 T014; PDS Biotechnology, #1 on the landing page, had fallen below $1).
  The named cases check each reason against the build database's own row and the rules file; 14
  cases (GPUS added: a stock below $1), all 154 checks pass; on 13 Nov's data every current
  company has a forecast or a reason naming its rule. Tests in `tests/unit/test_web_app.py` and
  `tests/unit/test_web_named_cases.py`
- [X] T023 V2-74 (16 Nov): a company in the question without a share count gets no forecast and
  its page says why (`web/forecast.py`, `no_share_count`: a company that files no reports with a
  share count, or a US company whose filings give none yet); the named cases check the reason
  against the build database's row; Akzo Nobel added. Tests in `tests/unit/test_web_app.py` and
  `tests/unit/test_web_named_cases.py`. On 16 Nov's data the 15 named cases pass (0 failed,
  `docs/report/app_named_cases.md`)

## Phase 9: User Story 8 - One section at a time (the researcher, 16 Nov)

- [X] T024 [US8] Spec (User Story 8, FR-022 amended, FR-025, SC-009), plan ("The page in tabs") and
  these tasks
- [X] T025 [US8] `templates/index.html`: the company header with the dilution band, the tab bar and
  five tab panels; a version on the static files' addresses (`main.py`)
- [X] T026 [US8] `static/app.css`: the header, the sticky tab bar, cards, the list of key
  statistics, tiles, fold-outs and segmented controls; a phone layout
- [X] T027 [US8] `static/app.js`: tabs with their addresses; each section drawn into its tab; charts
  drawn when their tab opens; the reasons as bars; first rows with a button for the rest
- [X] T028 [US8] The landing page in the same style: the list of highest risks with a short guide to
  the bands
- [X] T029 [US8] Checks: ruff, the tests, the named cases; screenshots of each tab for three
  companies on a 1440 × 900 screen (scratchpad only, never committed: the charts can use the
  private price source). Done 16 Nov: 339 tests pass; no typed-in date in the page files;
  screenshots of every tab (Apple, Alaunos, MGP, Hyperscale Data without a forecast), the landing
  page, a tablet width and a phone width (390 pixels, in a frame); the fold-outs checked open
