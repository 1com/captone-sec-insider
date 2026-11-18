# EDGAR-SENTINEL

**Will this company soon issue many new shares?** For any US-listed company, EDGAR-SENTINEL
forecasts the chance that its shares outstanding rise by 10% or more within the next six months.
That is *dilution*: each existing share then owns a smaller part of the company. The forecast is
built only from public data (SEC filings, Yahoo prices, FRED, Cboe, FINRA) plus one paid month of
Tiingo prices, and the data updates itself every weekday.

The **app** shows one page per company: the dilution chance with its band, the band's record and
the reasons behind it, the price and volume chart, insider buying and selling, key financials as
first filed, the SEC filings in plain English and short selling. **It serves the dilution forecast
only.**

**The presentation** (15 minutes with a live demo; dry run on 18 November 2026): the
[slides as PDF](docs/presentation/slides.pdf), or as
[PowerPoint with the speaker notes](docs/presentation/slides.pptx).

## How well it forecasts: the one-time test

The answers from 2023 on were sealed while the models were built: never computed, never looked
at. On 12 November 2026 a command that refuses a second run scored the frozen models on them,
once: 148,067 company-months with a forecast at a month-end from 31 Jan 2023 to 30 Apr 2026, each
answered six months later; 12% of them were followed by a 10%+ rise in shares. The levels had
been compared, and LightGBM chosen, on the test years 2019–2022.

| Dilution level | Log loss, test years 2019–2022 | Log loss, one-time test | AUC, one-time test |
|---|---|---|---|
| Base rate: the same chance for every company | 0.343 | 0.369 | 0.50 |
| Offering rule: a share offering filed in the last 12 months | 0.301 | 0.311 | 0.76 |
| Logistic regression | 0.249 | 0.256 | 0.89 |
| **LightGBM, the approved model** | **0.226** | **0.229** | **0.91** |

Lower log loss is better; an AUC of 0.5 is a coin toss, 1 is perfect. LightGBM was the best level
in each of the four years 2023–2026; the tenth of companies with the highest chances diluted 5.1
times as often as all companies, and in the highest band 42% diluted against a forecast of 37%.
Nothing was changed after the test.

## The app

```bash
./scripts/start_web.sh    # or: uv run sentinel web; on Windows: "Start EDGAR-SENTINEL.bat"
./scripts/stop_web.sh     # or: "Stop EDGAR-SENTINEL.bat"
```

It opens at http://localhost:8100 and runs on one computer only: its price charts include prices
from the paid source, which may not be published (decision V2-71), so this page has no
screenshots. It needs the data (see [Installation](#installation-and-commands)) and reads only the
serving copy, `data/serving.duckdb`, picking up each weekday's new copy by itself. The forecasts
are made by the daily update with the frozen approved model, never by the app. A company without
a forecast is told on its page why: a rule set before the models were built (a price below $1, for
example), no share count, or a share count that its trading rules out. On the data of 16 Nov 2026
the app covered 6,915 companies still trading, 3,669 of them with a dilution forecast. With
`WEB_PASSWORD` in `.env` every page asks for that password.

## How it works

1. **Data.** Every weekday at 10:00 an update downloads what is new: filings, financial facts and
   insider trades from the SEC, prices from Yahoo, market and macro series from FRED and Cboe,
   short-sale volume from FINRA. Tiingo's prices (one paid month, 26 Oct–26 Nov 2026) add the
   companies no longer listed and a second source for the others. The files are kept exactly as
   downloaded (11 GB, the first of six layers), and the other five are rebuilt from them: one
   table per source; companies, prices, filings, financial values and insider trades, each with
   the first day it may be used; features as of month-ends, results eves and each company's
   latest day; the answers, models and daily forecasts; the serving copy the app reads
   ([architecture](docs/architecture.md)).
2. **The question.** Its definition (a rise of 10% or more in shares outstanding within six
   months) was fixed before any model was built, in
   `config/risk_params.yaml`, tagged `prereg-risk-v5` in git; the code that computes the answers
   refuses to run if the file changes.
3. **The model.** It was built in a notebook (`notebooks/007-dilution-model.ipynb`) as a ladder
   of levels: a base rate, a simple rule (a share offering filed in the last 12 months), a
   logistic regression, LightGBM. Every level was trained only on earlier years and tested on
   2019, 2020, 2021 and 2022 in turn; the simplest level within one standard error of the best
   was chosen. The approved code lives in `src/sentinel/models/dilution.py`, and the
   [model report](docs/report/model_report.md) is generated from the notebook's records.
4. **The one-time test** scored the frozen models once, on the sealed answers from 2023 on
   (above).
5. **Daily forecasts.** Since 12 Nov 2026 the update makes the dilution forecast of every company
   in the question with the frozen model, and keeps each forecast with its inputs and their
   contributions, to be compared with what happened once its six months have passed.

## The rules

- **No look-ahead.** Every fact carries the first trading day it may be used (`known_at`): a
  quarterly report's share count, for example, only from the day the report was filed. A test
  removes later records and checks that nothing earlier changes.
- **Definitions fixed first.** `config/risk_params.yaml` was tagged `prereg-risk-v5` before any
  model was built and is never edited.
- **One sealed test, run once.** The answers from 2023 on were never computed while the models
  were built; `sentinel holdout --run` scored them on 12 Nov 2026 and refuses a second run. No
  model was changed after it.
- **Reproducible.** Raw files are never edited; every layer is rebuilt from the one below, and the
  daily update must give the same tables as a full rebuild (`sentinel verify`). Reports are
  generated by commands, never typed in.
- **Private data stays private.** Tiingo's prices and everything derived from them never appear in
  this repository or on a public page; notebooks are committed without outputs; secrets live only
  in `.env`.
- **Every decision logged** in [docs/decisions.md](docs/decisions.md) (V2-1 onwards), with the
  alternatives considered and their consequences.

## Installation and commands

Needs [uv](https://docs.astral.sh/uv/), which installs Python 3.14 and the locked packages:

```bash
git clone https://github.com/1com/captone-sec-insider && cd captone-sec-insider
uv sync
uv run pytest -q                    # the tests that need the private data skip themselves
uv run ruff check src tests && uv run ruff format --check src tests
```

The data is not in the repository (`data/` is ignored by git): 11 GB of raw files, part of them
from a paid source that may not be shared, plus the frozen models' records. To build it, copy
`.env.example` to `.env`, fill in the keys, and use the commands below. Heavy commands run under a
memory cap on the 10 GB computer this was built on
(`systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel …`).

| Command | Does |
|---|---|
| `uv run sentinel fetch all` | download every source into `data/raw/` (Tiingo only until 26 Nov 2026) |
| `uv run sentinel build <layer>` | rebuild a layer from the one below: `staging`, `reference`, `core`, `features`, `labels` |
| `uv run sentinel update` | the daily update: fetch what is new, rebuild, forecast, publish, export (weekdays at 10:00) |
| `uv run sentinel verify` | rebuild everything from the raw files and compare with the build: must be identical |
| `uv run sentinel status` | recent runs, each dataset's latest date, price coverage, the next scheduled run |
| `uv run sentinel web` | the app, on this computer only: http://localhost:8100 |
| `uv run sentinel report` | regenerate the model report from the notebooks' records |
| `uv run sentinel holdout --check` | check the one-time test's guards (the test ran once and refuses to run again) |
| `uv run python -m sentinel.presentation` | regenerate the hand-in's number sheet, `docs/presentation/numbers.md` |
| `uv run python -m sentinel.web.named_cases` | compare 21 companies' pages, section by section, with the data |

More commands, and every table, are in [docs/architecture.md](docs/architecture.md).

## Map of the repository

| Where | What |
|---|---|
| `src/sentinel/raw/`, `staging/`, `reference/`, `core/`, `features/`, `labels/` | the data layers: downloads, one table per source, companies and facts with `known_at`, features, answers |
| `src/sentinel/models/` | the approved dilution model (`dilution.py`), its simpler levels, the model report, the catching-up check; `volatility.py` and `results_move.py` are two models of the researcher's own for later work (volatility over three months, the size of the next results-day move), not part of the course project and not served |
| `src/sentinel/scoring/`, `serving/`, `update/` | the daily forecasts, the serving copy and export, the daily update |
| `src/sentinel/web/` | the app |
| `src/sentinel/holdout.py`, `audit.py`, `presentation.py` | the one-time test, the price audit, the number sheet |
| `config/` | the sources, the insider tracker's rules, the pre-registered definitions (`risk_params.yaml`) |
| `notebooks/` | the EDA (004) and the dilution model's notebook (007); 005 and 006 belong to the two later-work models; all committed without outputs |
| `docs/` | the spec, the architecture, the plan, the decision log, the lessons from version 1 |
| `docs/report/` | generated: the model report and model card, the catching-up report, the price audit, the app's named cases |
| `docs/presentation/` | the slides (`slides.pdf`; `slides.pptx` with the speaker notes) and the hand-in's number sheet (`numbers.md`, generated) |
| `specs/` | one folder per feature (spec, plan, research, tasks), numbered as in `docs/plan.md` |
| `tests/` | unit tests on made-up rows, and checks on named real companies (skipped without the data) |
| `scripts/` | start and stop the app |

## Limits

- **The dilution answer partly catches up with sales already announced.** 41% of the answers of 1
  (2012 to mid-2022) had a share sale filed by the forecast date that no published share count yet
  showed. With nothing announced, the approved model's AUC on the test years 2019–2022 is 0.87
  (0.89 on all rows) and its highest band diluted 33% of the time (41% on all rows)
  ([the check](docs/report/dilution_catching_up.md)).
- **Foreign filers are left out** of the dilution question: they report their share count once a
  year, so most of their months have no answer to learn from. Their pages say so.
- **Share counts.** Some companies report their share count in thousands without saying so, or a
  placeholder; when a company's trading rules out its count (more than 10 times its market value
  traded a day), no forecast is shown and the page marks the count as doubtful. A repair at the
  source is planned.
- **Prices of companies no longer listed** come from the paid source used for one month; they
  complete the histories but cannot be published, so the app runs on one computer. 335 companies'
  price histories are still cut short although older prices are stored (1,162 before the repair of
  11 Nov; [the audit](docs/report/data_audit.md)).
- **The live record starts later:** the first daily forecasts' six months end in May 2027.
- A course project, not investment advice.

## Working notes

The project's history, its way of working and the notes for the coding agents that helped build it.

### History

This is version 2, rebuilt from scratch on 29 October 2026. Version 1 (an insider-trading study
that grew into this platform) is retired: its code, history, issues and demo site were removed from
GitHub on 29 October (decision V2-2); what it taught is in
[docs/lessons-from-v1.md](docs/lessons-from-v1.md).

The platform answers four independent questions, each for every stock the data allows: who among
the insiders is buying or selling (the tracker: rules, no model), how much the stock will move over
the next three months (volatility), how big its next results-day move will be, and whether the
company is about to issue many new shares (dilution). The app serves the tracker and the dilution
forecast (V2-61).

### Documents

| Document | What it says |
|---|---|
| [.specify/memory/constitution.md](.specify/memory/constitution.md) | the project's non-negotiable rules (no look-ahead, honest evaluation, reproducibility, lawful data use) |
| [docs/spec.md](docs/spec.md) | what the platform does, for whom, which stocks get what, the data rules, how forecasts are judged |
| [docs/architecture.md](docs/architecture.md) | the six data layers, every table, the commands |
| [docs/decisions.md](docs/decisions.md) | the decision log (V2-1 …) |
| [docs/plan.md](docs/plan.md) | the plan of record: schedule, status, cut order |
| [docs/report/model_report.md](docs/report/model_report.md) | the generated model report: data, methods, results per question, the one-time test |
| [docs/presentation/numbers.md](docs/presentation/numbers.md) | the generated number sheet: every number of the hand-in with its source |
| [docs/lessons-from-v1.md](docs/lessons-from-v1.md) | what went wrong in v1 and the rule v2 follows instead |
| [specs/](specs/) | one folder per spec-kit feature: spec, plan, research, data model, contracts, quickstart, tasks |

### Roadmap and progress (17 November 2026)

The detailed roadmap (every feature with its owner, dates, dependencies and done-when test) is
[docs/plan.md](docs/plan.md); GitHub has one issue per feature (#67–#87) in six milestones. The
three are updated together.

| Milestone (due) | Features | Owner | Status |
|---|---|---|---|
| *done 29 Oct* | steps 0–4: v2 started, every data layer built (#62–#66) | agent | done |
| 1 Data platform (30 Oct) | 001 daily data refresh (#68) · 002 reference datasets (#73) · 003 team workflow and CI (#75) | agent | done: 001 (#91), 002, 003 (`main` protected: pull requests with CI) |
| 2 Data science (13 Nov) | 004 EDA (#76) · 005 volatility (#67) and 006 results-day move (#77), the researcher's later extensions (V2-78) · 007 dilution (#78) · 008 model report (#79) · 009 daily scores (#74) | teammate, with the agent (004: agent) | 004–008 done: the three models approved (V2-52, V2-55, V2-58), packaged in `src/sentinel/models/`, the model report generated by `sentinel report`; 009: since 12 Nov the update makes the daily dilution forecasts with the frozen approved model (V2-72) |
| 3 App (16 Nov) | **026 stock research app** (V2-61), replacing Gemini's 011–017 (#80–#85, #70) · 018 hosting (#86) | researcher, with the agent | 026 merged (#101, #109–#112, #115), on this computer only (V2-71): key financials as first filed, 14 named cases checked, the daily dilution forecasts (V2-72), each left-out company told its rule (V2-73), the page in tabs (16 Nov), no forecast when the trading rules out the share count (V2-75); approved by the researcher on 17 Nov and the old app removed (V2-76); the first page lists no companies (V2-77); each factor explained by a "?" (18 Nov); left: insider clusters, short interest |
| 4 Holdout and hand-in (18 Nov) | 010 holdout test (#69) · 019 hand-in (#71): a presentation with a live demo (15 minutes, dry run 18 Nov) and this repository; no written report | all | 010 run once on 12 Nov (V2-69), the results in the model report; 019: the number sheet, the slides and the demo ready for the dry run (16–17 Nov), this front page (17 Nov), merged by #112 and #113; the slides as PDF and PowerPoint in `docs/presentation/` (18 Nov, #114); the talk tells the whole product, the research app and its data first (18 Nov, V2-80) |
| 5 Before Tiingo ends (25 Nov) | 020 offline rebuild and raw backup (#72) | agent | not started |
| 6 After hand-in (Jan 2027) | 021 quarterly model refit (#87): the models score daily but retrain only quarterly, by a logged comparison | teammate, with the agent | not started |

**What exists now.** Every layer is built in `data/sentinel.duckdb` from the raw files in
`data/raw/` (11 GB, with a manifest line per file): staging per source, companies and securities,
prices (Yahoo first, Tiingo as fallback), filings, financial values as first filed, insider trades
and clusters, macro and short-volume series, features for 11,000+ companies as of month-ends,
results eves and each company's latest day, and the development answers of the three questions
(windows ending by 31 December 2022). `data/serving.duckdb` holds the product's `app` tables;
`data/exports/` holds a private Parquet export (`ml/` training sets, `app/` copies).

**Where things stand** (details in [AGENTS.md](AGENTS.md), section 7, and
[docs/plan.md](docs/plan.md)): the data updates itself every weekday; the three forecasting models
are approved, packaged in `src/sentinel/models/` and described by the generated model report (two
of them, volatility and the results-day move, are the researcher's later extensions, not part of
the hand-in: V2-78); the
holdout test (010) ran once on 12 November (V2-69); the stock research app (026), one page per
stock with dilution risk as its main feature, was approved by the researcher on 17 November
(V2-76); the hand-in (019) is a presentation with a live demo, dry run on 18 November.

### Working together

- **Three tracks, three contracts.** The data platform writes the training export and the serving
  copy; data science reads the export; the app reads the serving copy. The forecast contract
  (`specs/009-daily-scores/contracts/score-contract.md`) fixes the columns each forecast is
  published in. Change a contract only by agreement, in its spec.
- **Fixed feature numbers.** Use the number from the roadmap for the spec-kit folder and branch
  (`specs/NNN-name/`, branch `NNN-name`), e.g. `/speckit-specify` for 005 with
  `SPECIFY_FEATURE_DIRECTORY=specs/005-volatility-model`.
- **Pull requests into `main`.** One branch per feature; open a pull request; CI (from feature 003)
  must pass; ask the other track to review when a contract changes. Merge, and keep the branch
  (the researcher, 12 Nov).
- **Models are built in notebooks, then moved to `src/`.** The EDA and each model (built, run
  and tuned) are in `notebooks/`, with outputs stripped on commit (they could publish private
  data); once the researcher approves a model, its code moves to `src/sentinel/models/` and runs
  by command, and the notebook imports it. Details in `docs/plan.md`.
- **The app reads `data/serving.duckdb`**, rebuilt by each weekday's update; `data/exports/app/`
  holds Parquet copies of the same tables for sharing and analysis.
- **Data is never in git.** `data/` is git-ignored. The researcher shares the private export with
  the teammate directly (it holds Tiingo-derived prices: never publish it, never commit it). The
  build needs the raw files and `.env` keys, which stay on the researcher's machine.
- **Status lives in the issues.** Move an issue's checklist forward as tasks are done, close it when
  the feature merges, and update `docs/plan.md` and this table.

### For an agent continuing this work

**Start with [AGENTS.md](AGENTS.md)**: the step-by-step hand-over (where things stand, what to do
next, the researcher's way of working). Gemini CLI loads it through `GEMINI.md`, Claude Code
through `CLAUDE.md`; spec-kit steps are `/speckit:*` commands in Gemini (`.gemini/commands/`).

Start with [docs/plan.md](docs/plan.md): its **Next steps** list says what to do now, and its
**Data for each model** table says which file, rows, answer and baseline each model uses. Then
read the constitution, `docs/spec.md`, `docs/architecture.md`, `docs/decisions.md`, and the
current feature's `specs/NNN-name/tasks.md`. The GitHub Project *EDGAR-SENTINEL v2 roadmap* shows
every feature's track, dates and status.

**How work is done.**

- Every piece of work is a spec-kit feature with its roadmap number: `/speckit-specify` →
  `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` (skills in `.claude/skills/`), on a
  branch named after the feature. Mark each task `[X]` in `tasks.md` as it is done.
- When a feature is done, merge it into `main` through a pull request; branches are kept after the
  merge (the researcher, 12 Nov).
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
  choose a model. It was evaluated once, by a guarded and logged run (feature 010, 12 Nov). The
  private reference copies of 002 are for personal work, never for the models.
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

- Heavy jobs run under a memory cap: `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel …`.
  DuckDB is capped at 2 GB (`db.MEMORY_LIMIT`).
- `data/sentinel.duckdb` has one writer at a time. Browse `data/serving.duckdb`, read-only.
- Ports 8000 and 8080 belong to other projects; do not stop them. Check a port is free (in WSL
  and on Windows) before giving it to anything. The stock research app (026) uses 8100;
  `sentinel web` refuses a busy or reserved port and stops nothing.

### Daily use

```bash
uv run sentinel update            # fetch what is new, rebuild, forecast, publish, export, record
uv run sentinel status            # recent runs, data as of, price coverage, next scheduled run
uv run sentinel verify            # rebuild from the raw files and compare: must be identical
uv run sentinel schedule install  # run the update on weekdays at 10:00 (Windows Task Scheduler)
```

Other commands: `sentinel fetch <source>`, `sentinel build <layer>`, `sentinel publish`,
`sentinel export` (see `docs/architecture.md`).

```bash
uv run sentinel audit             # price coverage: problem families, named cases, coverage by year
uv run sentinel audit --before data/audit/prices-2026-11-11-before.json   # + docs/report/data_audit.md
uv run sentinel fetch tiingo-former   # once (done 11 Nov): old tickers' histories, Tiingo only until 26 Nov
```

The app's pages are checked section by section against the build database, the frozen model and
the SEC's files for 21 named companies (`uv run python -m sentinel.web.named_cases`, report in
`docs/report/app_named_cases.md`).

### Notebooks

The EDA of each training set (feature 004) ends with its findings:
`notebooks/004-eda-volatility.ipynb`, `004-eda-results-move.ipynb`, `004-eda-dilution.ipynb`. They
read `data/exports/ml/` and run start to finish with one command each, under the memory cap:

```bash
uv run nbstripout --install --attributes .gitattributes   # once per clone: commits never hold outputs
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 \
  uv run jupyter nbconvert --to notebook --execute --inplace notebooks/004-eda-volatility.ipynb
```

The three model notebooks build, compare and freeze the approved forecasts (`007-dilution-model`,
`006-results-move-model`, `005-volatility-model`); their code lives in `src/sentinel/models/`,
which they import. Each ends by recording its tables in MLflow (`data/mlflow.db`) for the model
report (feature 008).

### Model report

`docs/report/model_report.md` (with `figures/` and `model_card.json`, the numbers the app's model
card shows) is generated from those records, never edited by hand. From a fresh clone plus the
data: build and export the data, run the three model notebooks start to finish (above, about 45
minutes in all), then

```bash
uv run sentinel report   # seconds; the same records give identical files
```

Re-run it after any model notebook is re-run, and after the holdout test (feature 010), whose
results it adds as they came out (`specs/008-model-report/quickstart.md`). The front page's results
table is checked against `model_card.json` by `tests/unit/test_readme_numbers.py`.

`docs/report/dilution_catching_up.md` measures a limit of the dilution answer (V2-70): a share sale
made before the forecast date but not yet in a published share count is answered 1 too, so part of
the forecast catches up with a sale already announced. It is generated, never edited by hand, in
about five minutes (the four test years are refitted with the approved code and checked against
its record; read-only, no MLflow record written):

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run python -m sentinel.models.catching_up
```

### Holdout test (run once, 12 November)

The one test of the approved models on the answers from 2023 on, sealed until then: each frozen
model and every simpler level beside it, per calendar year and over all
(`specs/010-holdout-test/quickstart.md`). It ran once, on 12 November 2026 (V2-69); a second run is
refused. Its records are in `data/mlflow.db` (experiment `010-holdout`), their files in `mlruns/9/`
at the project root (ignored by git; never delete; a copy in `data/backup/after-holdout/`).

```bash
uv run sentinel holdout --check   # any time: everything but the answers (computes none)
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel holdout --run   # once
uv run sentinel report            # adds the results to the model report, unedited
```

`sentinel holdout --freeze-levels` proves the packaged simpler levels give the notebooks' recorded
numbers on the export the frozen models were built on, kept in `data/frozen/<export date>/` (the
date is read from the approved models' records; `--check` refuses if the kept rows are missing or
changed), and freezes them for 2023. It was first run on 10 November on the export of 9 November; after
the price repair (027, V2-65) the models were retrained on the export of 11 November, approved
again (V2-68), that export kept in `data/frozen/2026-11-11/` and the levels frozen again
(11 November). Do not re-execute the model notebooks before the hand-in: each execution writes a
new record, which the report would show instead of the approved one (reading them is fine).
