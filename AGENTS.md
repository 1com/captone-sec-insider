# Instructions for any coding agent continuing EDGAR-SENTINEL

This file is the hand-over: what the project is, how the researcher wants to work, where things
stand, and **what to do next, step by step, to the end of the project**. It is read by every
agent (Gemini CLI loads it through `GEMINI.md`; Claude Code through `CLAUDE.md`). Keep it
current: when a step is done, tick it here and update "Where things stand".

## 1. The project in one paragraph

EDGAR-SENTINEL v2 is a market research platform for any US-traded stock, built from free data
(SEC EDGAR, Yahoo, FRED, Cboe, FINRA) plus a paid Tiingo month (26 Oct – 26 Nov 2026). It answers
four independent questions for any stock: insider activity (a tracker, no forecast), expected
volatility over the next three months, the expected size of the next results-day move, and the
chance of dilution (shares up 10%+ within six months). The data platform is built and updates
every weekday; the three forecasting models and the app are next. Hand-in: product v1 on
**17 November 2026**, report on **18 November 2026**.

## 2. Read these first, in this order

1. This file.
2. `docs/plan.md`: the roadmap (features 001–021, owners, dates, done-when) and **Next steps**.
3. `.specify/memory/constitution.md`: the rules that win over everything else.
4. `docs/spec.md`, `docs/architecture.md` (the six data layers), `docs/decisions.md` (every
   decision, V2-1 onwards, and the proposals waiting for the researcher).
5. The current feature's `specs/NNN-name/` folder (spec, plan, tasks).
6. `README.md` ("Working together", "For an agent continuing this work", "Daily use",
   "Notebooks").

## 3. The researcher and how to work with them

- **New to markets and data engineering.** Explain in plain words with a real example; define
  every market term the first time (ADR, 8-K, dilution, volatility...). Prefer one complete
  explanation over many small answers.
- **Before asking to continue, say in plain words what the next step does and why.**
- **Ask before** anything hard to undo or outward-facing: pushing, merging into `main`, opening or
  commenting on issues, deleting anything, installing schedules, changing a pre-registered
  definition. Decisions about the data or the method are the researcher's: propose with
  evidence, wait for the answer, then log it in `docs/decisions.md`.
- **Fix the method, never the answers.** The pipeline's data cleaning is **frozen at V2-32**
  (decision V2-33, 30 Oct): further cleaning (cutting extremes, dropping doubtful rows, missing
  flags) is part of each model's preprocessing, written in its notebook and moved into
  `src/sentinel/models/` with the model, so training and daily scoring clean alike. Rebuild the
  database only for an error that makes a large share of rows wrong, and only after the
  researcher agrees.
- **Models are built, run and tuned in their notebooks** (`notebooks/005-…`, `006-…`, `007-…`),
  executed start to finish so the researcher can read every table and chart. Only after the
  researcher approves a model does its code move into `src/sentinel/models/` (training,
  scoring, calibration by command); the notebook then imports that code and must give the same
  numbers. Never call the notebooks "only for trying ideas".
- **Every work item follows spec-kit** (section 6).
- **The scope is `docs/plan.md`.** The course repository is a template only; no tests with real
  users.
- **Reports and figures are produced by commands** and must run from a fresh clone plus the
  data and `.env` keys.
- **The app is built by the researcher with the agent**; the data-science track was meant for the
  teammate `sonson033` but the researcher has asked the agent to do it.
- `data/exports/` is shared with the teammate by the researcher, privately; do not raise it.

## 4. Rules that must never be broken

- **No look-ahead.** Every fact has `known_at` (the first trading day it may be used). A
  feature or cleaning rule for day D uses only what was known by D's close. The truncation test
  (removing later records changes nothing earlier) must keep passing.
- **The holdout is sealed.** Answers whose windows start in 2023 or later are never computed,
  read or used to build, tune or choose a model. They are evaluated **once**, by the guarded
  command of feature 010. The private reference copies (002) are never read by model code.
- **`config/risk_params.yaml` is never edited** (tag `prereg-risk-v5`, never delete or move the
  tag); the label code refuses to run if the file changes.
- **Raw files are never edited or deleted** (Tiingo's included); every layer rebuilds
  deterministically from the one below; `sentinel update` must equal a full rebuild
  (`sentinel verify`).
- **Tiingo data is private**: never in a public page, file, notebook output or commit.
  Notebooks are committed without outputs (nbstripout filter, `.gitattributes`); written
  findings quote aggregates only. Tiingo is called only until 26 November 2026.
- **Secrets** live only in `.env` (git-ignored).
- **SEC**: at most 10 requests a second, contact in the User-Agent.

## 5. This machine (WSL2 on Windows, 10 GB RAM)

- **Every heavy job runs under the memory cap, with no swap**, or WSL and VS Code crash:
  `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 <command>`. DuckDB is capped
  at 3 GB inside the code. Never run two heavy jobs at once.
- `data/sentinel.duckdb` has **one writer at a time**. If a command reports a lock, ask what
  holds it (often the daily update or a notebook); do not kill processes you did not start.
- **Port 8000 belongs to another application; never stop it.**
- The daily update runs by itself on weekdays at 10:00 (Windows Task Scheduler, `sentinel
  schedule show`); its log is `data/logs/update-<date>.log`. It runs the code of whatever branch
  is checked out, so do not leave a broken branch checked out at 10:00.
- Rebuild after a pipeline change (about 11 minutes):
  `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 bash -c 'uv run sentinel build core --only <steps> && uv run sentinel build features && uv run sentinel build labels && uv run sentinel publish && uv run sentinel export'`
- Run a notebook: `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run jupyter nbconvert --to notebook --execute --inplace notebooks/<name>.ipynb`
- Checks before every commit: `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run pytest -q`.

## 6. How work is done (spec-kit)

Every feature has a fixed number from `docs/plan.md` and goes through, in order:
**specify → (clarify) → plan → tasks → implement**, with its documents in `specs/NNN-name/` on a
branch `NNN-name`. The step instructions are in `.claude/skills/speckit-*/SKILL.md`:

- In **Gemini CLI**: `/speckit:specify <description>`, `/speckit:plan`, `/speckit:tasks`,
  `/speckit:implement`, `/speckit:clarify`, `/speckit:analyze` (defined in `.gemini/commands/`).
- In **Claude Code**: `/speckit-specify`, `/speckit-plan`, … (skills in `.claude/skills/`).
- Any other agent: open the matching `SKILL.md` and follow it.

Mark each task `[X]` in `tasks.md` as it is done; commit small and often; when the feature is
done, merge it into `main` (pull request, after the researcher agrees), delete the branch, and
close its GitHub issue (#67–#87, one per feature). Keep `docs/plan.md`, `README.md` and this
file in step.

## 7. Where things stand (30 October 2026, evening)

- **Branches** (nothing is merged into `main` yet; `main` is the 29 October state). They are
  stacked: `001-daily-data-refresh` → `004-eda` → `022-validation` (each contains the one
  before); **`022-validation` is the newest code**. All three are pushed.
  - 001 (daily data platform): left T046 (check a weekday 10:00 run, rerun, `sentinel verify`),
    T059 (the schedule is installed; confirm with the researcher), T062–T064 (docs, checks,
    merge).
  - 004 (EDA): done; left T017 (merge).
  - 022 (validation round): done: checks, verdicts, rules V2-28 to V2-32 implemented and rebuilt,
    notebooks re-run; left T007 (merge).
  - Merge order, with the researcher's go-ahead: 001, then 004, then 022 (pull requests).
- **Data**: every source current to 29 October 2026; the build, serving copy and export were
  rebuilt on 30 October with all cleaning rules (V2-22 to V2-32). The pipeline's cleaning is now
  frozen (V2-33): further cleaning belongs to each model's preprocessing.
- **Teammate**: `data/exports/share/dilution-2026-10-30.zip` (private, git-ignored) holds the
  dilution training set, `latest`, `feature_snapshot` and the column guide, with
  `README-dilution.md` saying what to read and do; the researcher sends it privately.
- **Decisions waiting for the researcher** (`docs/decisions.md`, "Proposed by the EDA"):
  V2-25 (named cases for the validation round, listed there). Decided on 30 October: V2-26,
  price-only stocks are eligible for volatility on the price rules alone (`eligible_volatility`);
  V2-27, foreign filers are left out of the dilution question (`eligible_dilution`; the app shows
  no dilution chance for them). Each model trains only on its question's flag.

## 8. What to do next, step by step

Do the steps in order unless the researcher says otherwise. Each step: say what it does and why,
do it, show a plain summary, tick it here.

### Step 1 · Finish 004 (EDA), branch `004-eda`
- [X] T024: the three EDA notebooks re-run on the cleaned export, Findings rewritten.
- [X] T023: V2-22 to V2-24 recorded as decided in `docs/decisions.md`, with rules and counts.
- [X] `docs/plan.md` and `README.md` updated. Left only T017, the merge (step 2).
- After any later pipeline change: rebuild, re-run the three EDA notebooks, and update their
  Findings if numbers move.

### Step 2 · Finish 001 and merge both branches
- [ ] T046: after a weekday 10:00 run, read `data/logs/update-<date>.log` and `uv run sentinel
  status`: status `complete`, SEC staging without "filers read" lines (only new files), duration
  under 30 minutes; run `uv run sentinel update --no-fetch` (expect `nothing_new`), then
  `systemd-run … uv run sentinel verify` (expect every table identical). Report the three.
- [ ] T059: confirm with the researcher that the 10:00 weekday schedule stays; tick.
- [ ] T062–T063: docs, then the full checks and `specs/001-daily-data-refresh/quickstart.md`.
- [ ] T064 and 004's T017: with the researcher's go-ahead, push, open pull requests, merge
  `001-daily-data-refresh` then `004-eda` into `main`, delete both branches, comment on and close
  issues #68 and #76.

### Step 3 · Validation round on named cases (feature 022, branch `022-validation`)
**Status: done (30 Oct).** Verdicts in `notebooks/022-validation.ipynb` section 8; V2-28 to V2-32
decided, implemented with tests, rebuilt once; EDA and validation notebooks re-run. Left: merge.

Original description:
The EDA checks what statistics can show; this checks values against the SEC filings and Yahoo.
Pick 20–30 named companies on purpose: disappeared companies priced from Tiingo (right company?
right last day?), small companies with reverse splits, rows with a split inside a dilution
window (25% dilute vs 9.7% overall: real or counting error?), extreme returns (+1,000% in a
month), foreign filers with ADRs, companies with 5–6 results releases a year, the absurd Tiingo prices
of two small OTC stocks (CLS Holdings, NFiniTi), share counts wrong from a company's first
filing, and the 194 companies where Yahoo and Tiingo disagree
(`core.price_check`). Output: `notebooks/022-validation.ipynb` with a pass/fail table; fixes as
proposals in `docs/decisions.md` for the researcher; then fix in the pipeline with tests,
rebuild, re-run the EDA. Add 022 to `docs/plan.md` first.

### Step 4 · 002 Reference datasets (private) and 003 Team workflow and CI
- [ ] 002 (#73): `sentinel export --reference` → `data/exports/reference/`: each question's
  rows for every year in the training files' exact columns plus `period` (development / gap /
  holdout), answers wherever windows have closed; never read by model code; log V2-21.
- [ ] 003 (#75): GitHub Actions (ruff, format, unit tests on every pull request), `main`
  protected, pull-request template, a CI check that rejects notebooks with outputs (nbstripout is
  already installed as a filter), README "Working together".

### Step 5 · The three models (005 volatility, 006 results-day move, 007 dilution)
For each, in order 005 → 006 → 007:
1. spec-kit specify → plan → tasks (`SPECIFY_FEATURE_DIRECTORY=specs/00N-…-model`).
2. Fill its notebook (`notebooks/00N-*-model.ipynb`): the instructions on top say exactly what
   (rules, the EDA's findings for that model, the holdout, ten sections). Build, run and tune
   every level there: naive baseline → rule → classic model → LightGBM, walk-forward test years
   2019–2022 with the purge, the simplest level within one standard error of the best,
   calibration, bands with hit rates, MLflow, fixed seeds.
3. Show the researcher the executed notebook; wait for approval.
4. Move the approved model into `src/sentinel/models/` with tests and a command; the notebook
   imports it and gives the same numbers.

### Step 6 · 008 Model report, 009 Daily scores
- [ ] 008 (#79): one command regenerates the report (data, methods, results per test year
  against the baselines, calibration, the choices) and the hit rates for `app.model_card`.
- [ ] 009 (#74): `sentinel update` scores every covered company daily into `score.daily` and
  records outcomes in `score.outcome`, in the columns of the forecast contract (011); a rerun
  changes nothing; `sentinel verify` identical.

### Step 7 · The app (011–018), with the researcher
011 design and the forecast contract (`specs/011-app-design/contracts/`), 012 FastAPI read-only
API over `data/serving.duckdb` (never port 8000), 013 stock page, 014 insider tracker, 015
dilution check, 016 screeners, 017 forecasts and model card, 018 hosting with no Tiingo-derived
value on a public page. Details and done-when in `docs/plan.md`.

### Step 8 · 010 Holdout test (16 November)
Build a guarded command: it refuses unless the models are frozen (approved, in
`src/sentinel/models/`, logged in MLflow with commit and data version) and no earlier holdout
run exists; it computes the 2023+ answers, scores the frozen models, writes the results and a
log entry; a second run is refused. The researcher triggers it. Results go into the report as
they came out; no model change afterwards.

### Step 9 · 019 Hand-in (17–18 November)
Product v1 on 17 November, report on 18 November, both regenerated by commands from a clone plus
the data.

### Later, when the researcher asks · 023 Options benchmark and live track record
Proposed on 30 October, deferred by the researcher. Free Yahoo option chains (`yfinance`
`Ticker.option_chain`, `Ticker.calendar` for the next earnings date) give the market's own forecast:
the expected results move (an at-the-money straddle expiring just after the release, divided by
the price) and 3-month implied volatility. Daily snapshots, stored in `data/raw/` with manifest
lines and kept private, plus a timestamped log of our forecasts, would let every closed window be
scored three ways: options market, our baseline, our model. Past option prices cannot be
downloaded, so the sooner it starts the longer the track record. Theory for the researcher's
questions: volatility clustering and mean reversion (GARCH: Engle 1982, Bollerslev 1986; HAR:
Corsi 2009), results-day information (Beaver 1968; implied volatility around earnings: Patell and
Wolfson 1979), equity issuance (pecking order: Myers and Majluf 1984; market timing: Baker and
Wurgler 2002).

### Step 10 · 020 Before Tiingo ends (by 25 November) and 021 (January 2027)
- [ ] 020 (#72): a fresh clone plus `data/raw/` rebuilds every layer identically; back up
  `data/raw/` to a second disk. Never delete Tiingo files (the researcher's decision).
- [ ] 021 (#87): quarterly refit with a logged comparison; first in January 2027.
