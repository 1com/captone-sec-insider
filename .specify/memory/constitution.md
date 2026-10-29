# EDGAR-SENTINEL Constitution

The standing rules for EDGAR-SENTINEL v2, a market research platform for any US-traded stock
([docs/spec.md](../../docs/spec.md)). Version 1's constitution (3.2.0) was retired with v1 (decision V2-2).

## Core Principles

### I. Point-in-Time Integrity (NON-NEGOTIABLE)

- Every fact MUST record when it became public (`known_at`): a filing's acceptance time, a
  financial value as first filed, a macro value's release day, a results release once its report
  is filed.
- A feature or forecast for day D MUST use only facts with `known_at` on or before D's close.
- Price-level rules (floors, market value) use as-traded prices; returns use adjusted prices.
- The suite MUST include a truncation test: deleting every record after D leaves day D's features
  and scores unchanged.

Rationale: look-ahead bias is silent and invalidates every forecast and every test.

### II. Every Question Covers What Trades

- The universe is the security master: every security trading on a US venue that can be priced,
  and, for history, every one that traded since 2012 and has disappeared.
- No question's universe may be limited by another question's data. A company's coverage level
  (full, foreign filer, price only) is decided by the data that question needs.
- Companies and securities are distinct: share classes and ADRs (with their ratios) are securities.
- A filing that does not apply to a company leaves its features missing, never zero.

Rationale: v1 took its universe from insider filings and silently dropped large companies.

### III. Survivorship-Complete History

- Securities that disappeared MUST stay in the history, priced from Tiingo and matched to their
  companies by dates and name.
- An early-ending price series is classified (merger, failure, unknown); a data gap is never treated
  as a failure without evidence.
- Coverage MUST be reported by year and by status.

Rationale: dropping the companies that failed makes every risk look smaller than it was.

### IV. Honest Evaluation (NON-NEGOTIABLE)

- The risk forecasts follow the evaluation fixed in decision D60 and `config/risk_params.yaml` v5
  (tag `prereg-risk-v5`): rule, classic model and LightGBM on purged walk-forward years 2019–2022;
  the simplest level within one standard error of the best; calibration; bands with hit rates.
- The risk holdout (answers whose windows start in 2023 or later) MUST NOT be computed by any
  development step and MUST be evaluated exactly once, by a guarded and logged run.
- Forecasts are shown as bands and chances with their past hit rates, never as bare numbers (D62).
- Builds MUST be deterministic: rows sorted before modelling, seeds fixed, randomness averaged over
  seeds where a verdict depends on it.
- No return predictions or claims are made (v1 found no insider signal; decision V2-4).

Rationale: a forecast is only as useful as the honesty of its track record.

### V. Reproducibility

- Raw downloads MUST be stored unchanged under `data/raw/` with a manifest line each (URL without
  secrets, fetch time, size, SHA-256).
- Every layer MUST be rebuilt deterministically by idempotent commands from the layer below; the
  daily update MUST give the same result as a full rebuild for the same day.
- Dependencies are locked in `uv.lock`; model runs are logged in MLflow with their git commit and
  data version.
- An offline rebuild check (a clean clone plus the raw files) MUST pass before the Tiingo plan
  ends on 26 November 2026.

### VI. Lawful and Respectful Data Use

- SEC requests stay at or below 10 per second and carry a real contact in the User-Agent.
- Tiingo data is fetched only while the paid plan is active (26 Oct – 26 Nov 2026) and is private:
  values derived from it MUST NOT appear on any public page or export. Its terms (§1.6(b)) tie
  storage to an active paid plan; what happens to the stored files when the plan ends is the
  researcher's decision.
- Provider limits and terms (Yahoo, FRED, FINRA, Cboe) MUST be respected; raw prices are not
  redistributed.
- Secrets live only in `.env`, which stays git-ignored.

### VII. Simplicity

- One build database (DuckDB) plus a read-only serving copy; Parquet for exports; Python with uv;
  FastAPI with server-rendered pages. No database server.
- A new service or heavy dependency MUST be justified in [docs/decisions.md](../../docs/decisions.md).
- Scope follows [docs/plan.md](../../docs/plan.md) and its cut order.

## Development Workflow and Quality Gates

- **Layer by layer.** Each layer (architecture.md) is built with tests before the next starts.
- **Real-data checks.** Each layer's tests MUST include named real cases (for example Apple, ASML,
  Meta, Tesla, JPMorgan, a closed-end fund, a business development company, a disappeared company),
  not only synthetic rows. A data rule MUST be checked on real cases before it is registered.
- **Before merging to `main`:** unit tests, point-in-time tests (including the truncation test),
  data-quality tests (unique keys, row counts against the manifest, coverage reports) and
  holdout-guard tests pass; ruff passes.
- **Reports are generated** by commands, never edited by hand.
- **Commits** stay small and descriptive; `data/` and secrets are never committed.

## Governance

- **Precedence.** This constitution, then [docs/spec.md](../../docs/spec.md), then the other
  documents. Where they conflict, the higher one wins and the lower one is corrected.
- **Amendments** are made in their own commit, state the reason and bump the version; changes to
  Principles I or IV are also logged in [docs/decisions.md](../../docs/decisions.md).
- **Versioning:** MAJOR for removing or redefining a principle, MINOR for adding one or materially
  expanding guidance, PATCH for wording.

**Version**: 4.0.1 | **Ratified**: 2026-10-29 (v2) | **Last Amended**: 2026-10-29 (v1 retired, V2-2)
