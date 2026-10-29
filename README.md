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

## Plan and progress (29 October 2026, evening)

The full plan with its done-when tests is in [docs/plan.md](docs/plan.md); the two are updated
together. GitHub: one issue per piece of work, in three milestones (*v2 · 1 Data platform*,
*v2 · 2 Risk models*, *v2 · 3 Product and hand-in*).

| # | Work | Dates | Status | Issue |
|---|---|---|---|---|
| 0 | Fresh start: v1 archived, v2 documents | 29 Oct | done | #62 |
| 1–4 | Data layers: staging, reference, core, features, development labels | 29 Oct | done | #63–#66 |
| F001 | Daily data refresh and update (`specs/001-daily-data-refresh/`) | 29–30 Oct | code done; real runs under way | #68 |
| F002 | Reference datasets with every year, private | 30 Oct | agreed, next | #73 |
| F003 | Risk models: volatility, dilution, results-day move (D60) | 2–6 Nov | not started | #67 |
| F004 | Daily scores and outcomes | 9–10 Nov | not started | #74 |
| F005 | Risk holdout: the one sealed test | 12 Nov | not started | #69 |
| F006 | Product v1 | 12–16 Nov | not started | #70 |
| F007 | Hand-in: product 17 Nov, report 18 Nov | 17–18 Nov | not started | #71 |
| F008 | Offline rebuild from raw before Tiingo ends | by 25 Nov | not started | #72 |

**What exists now.** Every layer is built in `data/sentinel.duckdb` from the raw files in
`data/raw/` (8.9 GB, with a manifest line per file): staging per source, companies and securities,
prices (Yahoo first, Tiingo as fallback), filings, financial values as first filed, insider trades
and clusters, macro and short-volume series, features for 11,000+ companies as of month-ends,
results eves and each company's latest day, and the development answers of the three questions
(windows ending by 31 December 2022). `data/serving.duckdb` holds the product's `app` tables;
`data/exports/` holds a private Parquet export (`ml/` training sets, `app/` copies).

**Where F001 stands** (tasks in `specs/001-daily-data-refresh/tasks.md`): the fetchers for every
source, the daily Form 4 parser with its reconciliation against the quarterly data sets,
`sentinel update`, `status`, `verify` and `schedule` are written and tested. The real refresh is
running: every source has been fetched to 28–29 October. Left: the real update and its named
checks, a same-day rerun (`nothing_new`) and `sentinel verify` (T028–T029, T035–T036, T046,
T053–T054); installing the weekday schedule, which needs the researcher's approval (T059); the
final validation and the merge into `main` (T063–T064).

**Next.** F002 (reference copies with every year, holdout answers included, for the researcher's
own work; the models never read them), then F003, the risk models.

## For an agent continuing this work

Read, in order: this README, the constitution, `docs/spec.md`, `docs/architecture.md`,
`docs/decisions.md`, `docs/plan.md`, then the current feature's `specs/NNN-name/tasks.md`.

**How work is done.**

- Every piece of work is a spec-kit feature: `/speckit-specify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement` (skills in `.claude/skills/`), on a branch named after
  the feature. Mark each task `[X]` in `tasks.md` as it is done.
- When a feature is done, merge it into `main` and delete its branch. Only `main` (and the branch
  of the feature in progress) lives on GitHub.
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
  choose a model. It is evaluated once, by a guarded and logged run (F005). The private reference
  copies of F002 are for the researcher's own work, never for the models.
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
