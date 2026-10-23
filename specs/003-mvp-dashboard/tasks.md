---

description: "Task list for feature 003: MVP prototype dashboard"
---

# Tasks: MVP Prototype Dashboard

**Input**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md)

**Tests**: the guards are required by the constitution's Prototype Exception (FR-022). The return arithmetic and ticker choice are also unit-tested.

## Phase 1: Setup

- [X] T001 Add the uv dependency group `mvp` to `pyproject.toml` (fastapi, uvicorn, jinja2, yfinance, scikit-learn, lightgbm, with pins from research.md R8) and add it to `default-groups`. Add `mvp/tests` to pytest `testpaths`. Run `uv sync`.
- [X] T002 Create the `mvp/` skeleton: `__init__.py`, `__main__.py` (typer CLI: `build`, `serve`, `check`), `params.yaml` and `config.py`. `config.py` holds paths under `data/mvp/`, loads `config/params.yaml` and `mvp/params.yaml`, and defines the `PILOT_LABEL` constant.

## Phase 2: Data pipeline (US1, US2 foundation)

- [X] T003 [US1] `mvp/pipeline/universe.py`: pilot (2006–2011) and recent (July–September 2026) events from `events_PROVISIONAL.parquet`, company names and tickers from the scratch database, today's listed CIKs from the SEC snapshot, and ticker choice (research R3).
- [X] T004 [US1] `mvp/pipeline/prices.py`: yfinance batches of 50, Parquet cache plus manifest, retries, failures list; loading with as-traded close rebuilt from splits (research R2). **Start the download in the background straight away.**
- [X] T005 [US3] `mvp/pipeline/insider.py`: one pass over the 83 archives extracting original-Form-4 P/S non-derivative lines joined to owners (name, roles, title) → `work/insider_tx.parquet`.
- [X] T006 [US1] `mvp/pipeline/returns.py`: the session at T, T+1-open entry, floors, Abdi–Ranaldo cost, abnormal paths from −20 to +252 against IWM and SPY, horizon BHARs gross and net. **Raise on any event dated from 2012** (research R4).
- [X] T007 [US1] `mvp/pipeline/study.py`: per group and horizon, n, mean, median, share positive, gross/net, and month-block bootstrap CIs; mean path plus bands; per-year means (research R5).
- [X] T008 [US2] `mvp/pipeline/features.py`: the Form 4 and price features as of T, for pilot and recent events (research R6).
- [X] T009 [US2] `mvp/pipeline/model.py`: logistic, LightGBM and market-only baseline, trained 2006–2010 (purged) and tested 2011; metrics, calibration, permutation importance; the selected model refitted on all pilot events and used to score recent events.
- [X] T010 [US3] `mvp/pipeline/companies.py`: profiles for event companies (quarterly buy/sell totals, the last 25 transactions, events) as JSON split into 16 files, plus a search index.

## Phase 3: Dashboard (US1–US4)

- [X] T011 [US1] Design system in `mvp/site/static/style.css`: tokens (light/dark), layout, nav, cards, KPI tiles, tables, banner, responsive behaviour.
- [X] T012 [US1] Chart and interaction layer in `mvp/site/static/app.js`: ECharts setup from CSS tokens, path-with-bands, bars, calibration, funnel, table toggles, theme toggle, screener filtering and sorting, company search and rendering.
- [X] T013 [US1–US4] Templates `mvp/site/templates/`: `base.html` (nav, theme, label banner, disclaimer, footer) plus `index.html`, `findings.html`, `model.html`, `screener.html`, `company.html` and `method.html`.
- [X] T014 `mvp/site/render.py`: renders both builds (local with vendored ECharts and the TradingView widget; Artifact with cdnjs ECharts and a TradingView link).
- [X] T015 [US4] `mvp/__main__.py` `build` orchestration (with step timings and cached steps) and `serve` (FastAPI static files on 127.0.0.1:8000).

## Phase 4: Checks and delivery

- [X] T016 [P] `mvp/tests/test_guards.py`: the returns builder raises for 2012+; stored outcomes ≤ 2011-12-31; no `mvp` import in `src/sentinel`; the label is on the overview, findings, model and screener pages of the built site.
- [X] T017 [P] `mvp/tests/test_returns.py` and `mvp/tests/test_universe.py`: path and BHAR arithmetic, as-traded close from splits, floors, cost floor, ticker choice.
- [X] T018 Run the full build, then `check`, ruff and pytest. Fix anything that fails.
- [X] T019 Start `serve` in the background and verify every page responds. Take screenshots if a headless browser is available, and review them.
- [X] T020 Publish the Artifact build as a private claude.ai Artifact.
- [X] T021 [US4] Write `mvp/DEMO.md` (5-minute script) and `specs/003-mvp-dashboard/run-notes.md` (coverage, results, timings, decisions). Make local commits on `003-mvp-dashboard`.
