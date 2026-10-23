# EDGAR-SENTINEL Constitution

## Core Principles

### I. Point-in-Time Integrity (NON-NEGOTIABLE)

- **Data cut-off.** Every input used for an event MUST have been public no later than the last trading session on or before its signal date T. This covers features, floors, entity definitions, insider roles and industry codes.
- **Entry.** Simulated entry MUST be at the open of the first session after T.
- **Prices.**
  - Price-level rules MUST use unadjusted (as-traded) prices: price floors, tick floors, price checks and market capitalisation.
  - Returns MUST use split- and dividend-adjusted prices.
- **Timestamps.** Every derived table MUST record when each fact became public (a filing date or a market date).
- **Truncation test.** The suite MUST include a truncation test: deleting every record dated after T leaves every event, entity, role, feature and floor decision at T unchanged.

Rationale: look-ahead bias is silent and invalidates every downstream result. It is cheaper to forbid it structurally than to detect it afterwards.

### II. Survivorship-Complete Data

- **Delisted stocks.** They MUST stay in the sample. Listed stocks are priced from Yahoo Finance and delisted stocks from Tiingo. The only exception is the MVP pilot sample (see Prototype Exception).
- **Early-ending price series.** Every series that ends before its label window does MUST receive a classified delisting return: acquired, performance-related or unknown. A data gap MUST NOT be treated as a failure without evidence.
- **Unpriced events.** These MUST be counted, compared with priced events, and bounded with worst-case and best-case results.
- **Coverage reporting.** Price coverage MUST be reported by year and by delisting status. A coverage shortfall MUST NOT be fixed by moving the study window after the fact.

Rationale: dropping companies that disappeared changes the answer, and the direction of the bias is not knowable in advance.

### III. Pre-Registration and a Sealed Holdout (NON-NEGOTIABLE)

- **Parameter file.** Every numeric parameter MUST live in `config/params.yaml` and in the spec's parameter register.
- **Pre-registration tag.** Before any post-event return is computed, the spec and parameter file MUST be (the only exception is the MVP pilot sample, see Prototype Exception):
  1. tagged `prereg-v1`;
  2. pushed to the remote;
  3. recorded by a GitHub Release of the tag, whose creation time GitHub records on its own servers.
- **Changes after the tag.** Any change after the tag MUST be logged in the spec's decision log, with its reason, and disclosed in the report.
- **Holdout.**
  - The holdout covers signal dates from 2023-01-01 to 2026-06-01.
  - Development work MUST use only label windows that end by 2022-12-31.
  - Holdout labels and outcomes MUST be computed only by the guarded holdout job, in the separate `hold` schema.
  - The holdout MUST be evaluated exactly once, and the run MUST be logged.
- **Hypotheses.** Only the five pre-registered hypotheses, with their fixed decision rules, are confirmatory. Every other analysis MUST be labelled exploratory.
- **Null results.** They MUST be reported with the same detail as positive ones.

Rationale: without a locked plan and an untouched test set, a backtest measures the researcher's persistence, not the signal.

### IV. Honest Statistics and Economics

- **Costs.** Every headline return MUST be reported net of the estimated round-trip trading cost, alongside the gross figure.
- **Overlap.** Inference MUST allow for events that overlap in time, using time-robust standard errors on monthly series or calendar-time portfolios. Treating overlapping events as independent is forbidden.
- **Multiple testing.** The confirmatory tests MUST apply the pre-registered Holm–Bonferroni correction.
- **Risk factors.** Any claim of abnormal performance MUST be checked against risk factors: Fama–French five factors, plus momentum and short-term reversal.
- **ML baselines.** An ML model MUST beat the pre-registered baselines, including the market-only model, before any claim of value is made.
- **Model selection** MUST follow the pre-registered rule: log loss, then the one-standard-error rule.
- **Trial count.** The number of configurations tried MUST be logged, so that Sharpe ratios can be deflated.

Rationale: in this field, most apparent effects disappear under costs, factor controls or honest standard errors. Results that survive them are the only results worth reporting.

### V. Reproducibility

- **Raw data.** Raw downloads MUST be stored immutably under `data/raw/`, with a manifest recording the URL, fetch time and SHA-256 hash for each file.
- **Warehouse.** Every warehouse layer MUST be rebuilt deterministically, by idempotent commands, from the layer above it.
- **Environment.** Dependencies MUST be locked in `uv.lock`, and random seeds MUST be fixed.
- **Model runs.** Every model run MUST be logged in MLflow, with its git commit, parameter-file hash and data snapshot.
- **Offline rebuild.** A clean clone plus the archived raw snapshot MUST regenerate the key tables and figures without network access.
  - While the paid Tiingo plan is active, the snapshot includes the Tiingo files, and the Step 21 offline-rebuild check MUST be run and logged before the plan expires.
  - After the plan expires, the snapshot can no longer hold Tiingo files (Principle VI). A rebuild then excludes delisted-stock prices, and its outputs MUST say so prominently. It is not expected to reproduce results that depend on those prices.

Rationale: free data sources change over time and cannot be re-downloaded identically. The archived snapshot is the only way to reproduce results.

### VI. Lawful, Low-Cost and Respectful Data Use

- **Free sources by default.** The course version MUST use free data sources, with one exception: one month of Tiingo Power for delisted-stock prices (decision D39, 2026-10-22). Any other paid source requires an amendment to this constitution.
- **Tiingo storage.**
  - Tiingo data MAY be stored only while a paid Tiingo plan is active (Tiingo ToS §1.6(b)).
  - When the plan ends, all Tiingo data MUST be deleted from every system the project controls: `data/raw/`, the warehouse, caches and backups. The deletion MUST be logged in the decision log.
  - Derived tables holding per-security values computed from Tiingo prices (for example, labels of delisted-stock events) count as Tiingo data for deletion. Only aggregate results that can neither substitute for nor reconstruct Tiingo prices (report tables, figures, model metrics) MAY be kept (ToS §1.6(c)).
  - Without an active paid plan, Tiingo data, including its public ticker list, MUST be processed in memory only and never written to disk (ToS §1.6(a)).
- **SEC fair access.** SEC requests MUST:
  - stay at or below 10 requests per second;
  - send a `User-Agent` with a real contact address.
- **Limits and terms.** Provider limits and terms (Tiingo's allowance, Yahoo's terms) MUST be respected and MUST NOT be circumvented.
- **No redistribution.** The product MUST NOT redistribute raw Yahoo or Tiingo prices; charts use a widget licensed for public display.
- **Secrets.** These live only in `.env`, which MUST stay git-ignored.

Rationale: the project is public research. Its credibility depends on obtaining its data legitimately. The single paid exception is bounded in time and cost, and exists only because the free tier's terms forbid storing the delisted prices that Principle II requires.

### VII. Simplicity and Scope Discipline

- **Stack.** Prefer the smallest stack that does the job: DuckDB + Parquet, Python + uv, and FastAPI with server-rendered pages.
- **New dependencies.** A new service, database or heavy dependency MUST be justified in the decision log.
- **Scope.** Scope follows the spec's MoSCoW priorities and its pre-registered cut order. The ML core (dataset, tournament, baselines, calibration, explanations and holdout evaluation) MUST NOT be cut.

Rationale: four weeks leaves no room for infrastructure that does not serve the research question.

## Technical and Data Constraints

- **Language and tooling.** Python 3.14 managed with uv; ruff for linting; pytest for tests.
- **Storage and compute.** A single DuckDB warehouse plus Parquet. No database server.
- **ML and statistics.** scikit-learn, LightGBM, SHAP, statsmodels and MLflow (local).
- **Serving.** FastAPI, Jinja2 templates and HTMX, read-only over the warehouse.
- **Data sources.**
  - SEC Insider Transactions Data Sets (2006 Q1 – 2026 Q3);
  - SEC filing headers, submissions and company facts;
  - Yahoo Finance (listed stocks);
  - Tiingo Power, for one month (delisted stocks; decision D39). Outside the paid month, only Tiingo's public ticker list, in memory;
  - FINRA Tick Size Pilot lists;
  - the Kenneth French Data Library.
- **Study window.** Returns are studied for events from 1 January 2012 onward (decision D42): the earliest year in which every data source is complete without workarounds, XBRL share counts being the binding source. Insider history from 2006 onward feeds the features.
- **Parameter values.** The authoritative values (thresholds, floors, horizons, grids) are those in the parameter register of `docs/initialplan.md` and in `config/params.yaml`.

## Development Workflow and Quality Gates

- **Spec-driven features.** Each feature follows spec → plan → tasks → implement. Every plan MUST pass the Constitution Check before work starts.
- **Tests before merging to `main`.** These suites MUST pass:
  - unit tests for gates, entity merging and event detection;
  - point-in-time tests, including the truncation test;
  - data-quality tests: unique keys, funnel reconciliation, price checks and coverage reports;
  - holdout-guard tests.
- **Recorded audits.** Hand audits defined in the spec are recorded quality gates, not optional extras:
  - the 30-event golden set checked against EDGAR;
  - footnote filter samples (50 excluded and 50 kept);
  - delisting classifications.
- **Order of results.** Event-study results MUST be written up before any ML result exists.
- **Commits.** Commits stay small and descriptive. Generated data, `data/` and secrets are never committed.

## Prototype Exception (MVP)

A self-contained MVP prototype, built before the `prereg-v1` tag to show what the product will look like (decision D44, 2026-10-22), is bound by these rules instead of the parts of Principles II and III that they name.

- **Pilot sample only.** Post-event returns MAY be computed before `prereg-v1` only for events with signal dates **before the labelled-window start (2012-01-01)**. These events lie outside both the development period (2012–2022) and the holdout (2023-01-01 to 2026-06-01).
- **Survivors only, labelled.** The pilot sample MAY use listed-stock prices only (Yahoo Finance), without delisted stocks. Every MVP output that shows returns or model performance MUST carry the label "Pilot sample (2006–2011), survivors only — prototype, not research results".
- **Scoring, not outcomes, after 2011.** A model trained on the pilot sample MAY score recent events, including the live period after 2026-06-01. Outcomes (returns, labels, hit rates) MUST NOT be computed for any event dated 2012-01-01 or later until `prereg-v1`, and after that only under Principle III.
- **Containment.**
  - MVP code and outputs MUST live in `mvp/` and its own git-ignored data folder.
  - Production code (`src/sentinel`) MUST NOT import MVP code.
  - MVP results MUST NOT feed any pre-registered test, parameter or feature definition.
- **Disclosure.** The exception, and anything learned from the pilot that changes the design, MUST be recorded in the decision log before `prereg-v1` and disclosed in the final report.
- **Provider terms still apply** (Principle VI). The dashboard shows derived results such as averages, scores and aggregate return paths. Raw price charts come from an embeddable widget licensed for display.

Rationale: a working prototype is needed early for the course, but seeing study-period results before the plan is locked would defeat the pre-registration. The pre-2012 pilot sample gives a real demonstration without touching the data the confirmatory tests use.

## Governance

- **Precedence.** This constitution supersedes other practices. `docs/initialplan.md` is the detailed design and runtime guidance. Where it conflicts with this constitution, the constitution wins, and the spec MUST be corrected.
- **Amendments.** An amendment MUST be made in its own commit that states the rationale and bumps the version. Changes to Principles I or III after the `prereg-v1` tag MUST also be logged as deviations in the spec's decision log and disclosed in the final report.
- **Versioning** follows semantic versioning:
  - MAJOR: removing or redefining a principle;
  - MINOR: adding a principle or section, or materially expanding guidance;
  - PATCH: clarifications and wording.
- **Compliance review.** Every plan and code review MUST verify point-in-time integrity, holdout sealing and net-of-cost reporting. Any added complexity MUST be justified against Principle VII.

**Version**: 3.1.0 | **Ratified**: 2026-10-21 | **Last Amended**: 2026-10-23
