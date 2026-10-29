# EDGAR-SENTINEL

A market research platform for any US-traded stock: prices, financial statements as first filed,
SEC filings in plain English and an insider activity tracker in one place, with three forecasts a
retail investor cannot easily get elsewhere: **dilution risk**, the **expected results-day move**
and **expected volatility**. Updated every day.

This is version 2, rebuilt from scratch on 29 October 2026. Version 1 (an insider-trading study
that grew into this platform) is retired: its code, history, issues and demo site were removed from
GitHub on 29 October (decision V2-2); what it taught is in
[docs/lessons-from-v1.md](docs/lessons-from-v1.md).

The platform answers four independent questions, each for every stock the data allows: who among
the insiders is buying or selling (the tracker: rules, no model), how much the stock will move over
the next three months (volatility), how big its next results-day move will be, and whether the
company is about to issue many new shares (dilution).

## Documents

| Document | What it says |
|---|---|
| [.specify/memory/constitution.md](.specify/memory/constitution.md) | the project's non-negotiable rules (no look-ahead, honest evaluation, reproducibility, lawful data use) |
| [docs/spec.md](docs/spec.md) | what the platform does, for whom, which stocks get what, the data rules, how forecasts are judged |
| [docs/architecture.md](docs/architecture.md) | the six data layers, every table, the commands |
| [docs/decisions.md](docs/decisions.md) | the decision log (V2-1 …) |
| [docs/plan.md](docs/plan.md) | the plan of record: schedule, status, cut order |
| [docs/lessons-from-v1.md](docs/lessons-from-v1.md) | what went wrong in v1 and the rule v2 follows instead |
| [specs/](specs/) | one folder per spec-kit feature: spec, plan, research, data model, contracts, quickstart, tasks |

## Roadmap and progress (29 October 2026, evening)

The detailed roadmap (every feature with its owner, dates, dependencies and done-when test) is
[docs/plan.md](docs/plan.md); GitHub has one issue per feature (#67–#86) in five milestones. The
three are updated together.

| Milestone (due) | Features | Owner | Status |
|---|---|---|---|
| *done 29 Oct* | steps 0–4: v2 started, every data layer built (#62–#66) | agent | done |
| 1 Data platform (30 Oct) | 001 daily data refresh (#68) · 002 reference datasets (#73) · 003 team workflow and CI (#75) | agent | 001 in progress; 002, 003 next |
| 2 Data science (13 Nov) | 004 EDA (#76) · 005 volatility (#67) · 006 results-day move (#77) · 007 dilution (#78) · 008 model report (#79) · 009 daily scores (#74) | teammate, with the agent | not started |
| 3 App (16 Nov) | 011 design and forecast contract (#80) · 012 API (#81) · 013 stock page (#70) · 014 insider tracker (#82) · 015 dilution check (#83) · 016 screeners (#84) · 017 forecasts and model card (#85) · 018 hosting (#86) | researcher, with the agent | not started |
| 4 Holdout and hand-in (18 Nov) | 010 holdout test (#69) · 019 report and hand-in (#71): product 17 Nov, report 18 Nov | all | not started |
| 5 Before Tiingo ends (25 Nov) | 020 offline rebuild and raw backup (#72) | agent | not started |

**What exists now.** Every layer is built in `data/sentinel.duckdb` from the raw files in
`data/raw/` (8.9 GB, with a manifest line per file): staging per source, companies and securities,
prices (Yahoo first, Tiingo as fallback), filings, financial values as first filed, insider trades
and clusters, macro and short-volume series, features for 11,000+ companies as of month-ends,
results eves and each company's latest day, and the development answers of the three questions
(windows ending by 31 December 2022). `data/serving.duckdb` holds the product's `app` tables;
`data/exports/` holds a private Parquet export (`ml/` training sets, `app/` copies).

**Where 001 stands** (tasks in `specs/001-daily-data-refresh/tasks.md`): the fetchers for every
source, the daily Form 4 parser with its reconciliation against the quarterly data sets,
`sentinel update`, `status`, `verify` and `schedule` are written and tested; every source is
fetched to 28–29 October and the first full update is running. Left: its named checks, a same-day
rerun (`nothing_new`) and `sentinel verify` (T028–T029, T035–T036, T046, T053–T054); installing
the weekday schedule, which needs the researcher's approval (T059); the final validation and the
merge into `main` (T063–T064).

## Working together

- **Three tracks, three contracts.** The data platform writes the training export and the serving
  copy; data science reads the export; the app reads the serving copy. The forecast contract
  (feature 011) fixes the columns each forecast is published in, so the app is built with
  placeholders while the models are made. Change a contract only by agreement, in its spec.
- **Fixed feature numbers.** Use the number from the roadmap for the spec-kit folder and branch
  (`specs/NNN-name/`, branch `NNN-name`), e.g. `/speckit-specify` for 005 with
  `SPECIFY_FEATURE_DIRECTORY=specs/005-volatility-model`.
- **Pull requests into `main`.** One branch per feature; open a pull request; CI (from feature 003)
  must pass; ask the other track to review when a contract changes. Merge, then delete the branch.
- **Data is never in git.** `data/` is git-ignored. The researcher shares the private export with
  the teammate directly (it holds Tiingo-derived prices: never publish it, never commit it). The
  build needs the raw files and `.env` keys, which stay on the researcher's machine.
- **Status lives in the issues.** Move an issue's checklist forward as tasks are done, close it when
  the feature merges, and update `docs/plan.md` and this table.

## For an agent continuing this work

Read, in order: this README, the constitution, `docs/spec.md`, `docs/architecture.md`,
`docs/decisions.md`, `docs/plan.md`, then the current feature's `specs/NNN-name/tasks.md`.

**How work is done.**

- Every piece of work is a spec-kit feature with its roadmap number: `/speckit-specify` →
  `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` (skills in `.claude/skills/`), on a
  branch named after the feature. Mark each task `[X]` in `tasks.md` as it is done.
- When a feature is done, merge it into `main` through a pull request and delete its branch. Only
  `main` and the branches of features in progress live on GitHub.
- Each feature is done when its tests pass, its named real-data checks pass
  (`tests/real/test_named_cases.py`), and the researcher has seen a plain summary. Before asking
  to continue, say in plain words what the next step does.
- Record significant choices in `docs/decisions.md`; keep `docs/plan.md`, this README and the
  GitHub issues in step.
- Reports and exports are produced by commands, so they can be regenerated from a clone plus the
  data.

**Rules that must not be broken.**

- No look-ahead: every fact carries `known_at`, the first trading day it could be used. The
  truncation test checks that features do not change when later records are removed.
- The risk holdout (answers whose windows start in 2023 or later) is never used to build, tune or
  choose a model. It is evaluated once, by a guarded and logged run (feature 010). The private
  reference copies of 002 are for personal work, never for the models.
- Raw files are never edited or deleted; Tiingo files included. A newer copy gets a new path.
  Every layer is rebuilt deterministically from the one below, and `sentinel update` must give
  the same tables as a full rebuild (`sentinel verify`).
- Secrets live only in `.env` (git-ignored), never in URLs, the manifest, logs or commits.
- Tiingo is a paid plan until 26 November 2026: it is asked only inside the window in
  `config/sources.yaml`, and Tiingo-derived values never appear on public pages or in public
  files. `data/exports/` is private.
- SEC requests stay under 10 a second with the contact in the User-Agent.
- Never delete or move the tag `prereg-risk-v5`: the risk pre-registration. The label code runs
  only while `config/risk_params.yaml` is byte-identical to its version at that tag, so the file
  (comments included) is never edited; a change needs a logged decision and a new tag.

**This machine** (WSL2 on Windows).

- Heavy jobs run under a memory cap: `systemd-run --user --scope -p MemoryMax=5G uv run sentinel …`.
  DuckDB is capped at 3 GB.
- `data/sentinel.duckdb` has one writer at a time. Browse `data/serving.duckdb`, read-only.
- Port 8000 belongs to another application; do not stop it.

## Setup

```bash
uv sync
cp .env.example .env    # SEC_USER_AGENT, FRED_API_KEY, TIINGO_API (Tiingo until 26 Nov 2026)
uv run pytest
```

Data lives in `data/` (git-ignored).

## Daily use

```bash
uv run sentinel update            # fetch what is new, rebuild, publish, export, record the run
uv run sentinel status            # recent runs, data as of, price coverage, next scheduled run
uv run sentinel verify            # rebuild from the raw files and compare: must be identical
uv run sentinel schedule install  # run the update on weekday evenings (Windows Task Scheduler)
```

Other commands: `sentinel fetch <source>`, `sentinel build <layer>`, `sentinel publish`,
`sentinel export` (see `docs/architecture.md`).
