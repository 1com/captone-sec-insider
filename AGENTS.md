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
- **Ask pending decisions one at a time**, each explained on its own: what it is, a real example,
  what each option changes, and a recommendation with the reason. If the researcher is unsure,
  explain the trade-off in plain words and ask again (the researcher, 4 Nov).
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
  at 2 GB inside the code (`db.MEMORY_LIMIT`; the process holds 1.3–1.9 GB more): every
  `duckdb.connect` must set it, since DuckDB's default is 80% of RAM. Never run two heavy jobs at
  once. To see where a job peaks, sample its scope's `memory.stat` (`anon`) every 2 s.
- `data/sentinel.duckdb` has **one writer at a time**. If a command reports a lock, ask what
  holds it (often the daily update or a notebook); do not kill processes you did not start.
- **Ports 8000 and 8080 belong to other projects; never stop them.** Before giving any project a
  port, check it is free in WSL (`ss -ltn`) and on Windows (`/mnt/c/Windows/System32/netstat.exe
  -ano`, German output) (the researcher, 10 Nov). The stock research app (026, `sentinel web`)
  serves on 8100, Gemini's old app (`sentinel serve`) on 8090; both refuse a busy or reserved port.
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
done, merge it into `main` (pull request, after the researcher agrees), keep the branch (the
researcher, 12 Nov: no need to delete merged branches), and close its GitHub issue (#67–#87, one
per feature). Keep `docs/plan.md`, `README.md` and this
file in step.

## 7. Where things stand (12 November 2026; the audit of the work of 30 Oct – 3 Nov was on 4 Nov)

Between 30 October and 3 November another agent (Gemini) added models, daily scores, a report,
the app, Docker and option chains, pushing straight to `main` without pull requests. On
4 November Claude audited it (three independent reviews, the key findings checked by hand). What
holds and what does not:

- **Intact:** the holdout is sealed (no code reads or computes answers for windows from 2023;
  labels stop at 2022-12-30); `config/risk_params.yaml` equals tag `prereg-risk-v5`; no notebook
  output or Tiingo value is committed; the pipeline edits of 2 Nov are memory changes only.
- **Daily update (001):** the 10:00 runs of 2, 3 and 4 Nov were stopped at the 5 GB cap (the
  "fixed & verified" note was measured without fetching). Fixed on branch
  `001-daily-data-refresh` (fetch in a child process; scoring and options no longer break the
  run): on 4 Nov `sentinel update` was `complete` in 25.5 min, the same-day rerun
  `nothing_new`. `sentinel verify` was killed at the cap (its compare connection had no memory
  limit); with DuckDB at 2 GB it ran through (peak 3.9 GB) and showed that two full rebuilds from
  the same raw files differed: ties broken by row order (V2-44, fixed with tests). The daily
  export no longer deletes `data/exports/reference/` and `share/` (it did until 4 Nov).
  **T046 done on 5 Nov:** the 10:00 scheduled run `complete` in 47 min (19 of them Yahoo's
  downloads; the target is now 60, V2-47), 3.25 GB; verify then found two feature steps not
  identical (ties, floating-point sums: fixed, V2-44 of 5 Nov), the change report miscounted
  `app.daily_score` (fixed) and the daily update never asked Yahoo for new tickers' full
  histories (FR-008, 43 tickers: fixed); after an update with the fixes, `sentinel verify` found
  every table identical and the rerun was `nothing_new` with every `app` table unchanged. The EDA
  notebooks were re-run on that export. Data current to 4 Nov. 001 is done: merged by #91 (5 Nov).
- **Models (005–007) are not approved and must be redone in their notebooks, executed with
  outputs for the researcher:** 006 was evaluated with the look-ahead input `cum_split_after`
  (98 features in MLflow), so its numbers are void; the one-standard-error rule was not applied
  (for 005 it picks the Level 1 rule: 0.3263 against XGBoost 0.3119 ± 0.0290); the 80%
  volatility range was scaled in-sample (65–67% coverage); bands are fixed cut-offs without test-
  year hit rates (risk_params `reporting`, D47); the packaged models differ from the evaluated
  ones and carry `git_commit="frozen"`; the teammate's 007 notebook (`origin/007-dilution-model`,
  Jassin, 2 Nov) was never merged and `main` holds another 007 notebook. The numbers formerly
  quoted here are in MLflow (`data/mlflow.db`) for reference only. **Decided 4 Nov:** 007 is
  Jassin's notebook (V2-40); 006 is chosen by the mean log loss of its 5%/10%/20% chances
  (V2-41). **Decided 5 Nov:** 007 first, then 006, 005 only if time allows before the holdout
  test (V2-48); every model, calibration, band edge and range is a `sentinel.models.dated.Dated`,
  which learns only from answers known before its cutoff and forecasts only rows dated after it
  (V2-49). **007 approved on 5 Nov (V2-52): LightGBM**, log loss 0.225 against 0.302 for the
  offering rule, better in every test year; packaged in `src/sentinel/models/dilution.py` (the
  notebook imports it, same numbers). Merged by #92 (9 Nov), #78 closed. **006 started 9 Nov**
  (branch `006-results-move-model`): spec rewritten to V2-41/46/49/50, bands by the chance above
  10% (V2-53); plan with a design check on 2016–2018 only (one forecast of the log move per
  level, three Platt calibrations; from 2010; sector left out, not point-in-time); the three
  release-timing features left out (V2-54). Notebook rebuilt and run (9 Nov, 7 min, outputs
  for the researcher): **LightGBM chosen** by V2-50, mean log loss of the three chances 0.404
  against 0.409 ridge, 0.421 rule, 0.433 baseline, 0.469 base rates, better than the ridge every
  year (the textbook rule would keep the ridge); bands rise every year; H-R1 to H-R6 supported;
  frozen candidate passes the dry run. **006 approved on 9 Nov (V2-55): LightGBM**, packaged in
  `src/sentinel/models/results_move.py` (the notebook imports it, same numbers); `sentinel train` and
  `sentinel score results_move` work; the paused daily scores store the chance above 10% (V2-53)
  and live outcomes compare it with a move above 10%. Merged by #94 (9 Nov), #77 closed. **005 built
  9 Nov** (branch `005-volatility-model`, V2-48 cutoff: approved by 11 Nov evening or left out):
  deciding measure the mean absolute log error (V2-56); ridge and LightGBM forecast the change from
  past volatility; the 80% range on all earlier years' out-of-sample errors (walk-forward from
  2014, V2-10). First run: LightGBM worst in 2022, baseline chosen; macro left out after it
  (V2-57, after seeing the test years: as V2-36). Re-run: **LightGBM chosen**, 0.279 against 0.290
  ridge, 0.326 rule, 0.346 baseline, best every year; range coverage 78/72/84/88%. **005 approved
  on 9 Nov (V2-58)**, packaged in `src/sentinel/models/volatility.py` (the notebook imports it,
  same numbers); `sentinel train volatility` computes its range history from 2014 itself
  (minutes); the paused daily scores use its bands. Merged by #96 (9 Nov), #67 closed. All three
  models are approved and in `main`. **008 built 9 Nov** (branch `008-model-report`): each model
  notebook ends by recording its tables in MLflow (`sentinel.models.report.record`); `sentinel
  report` writes `docs/report/model_report.md`, figures and `model_card.json` from the newest
  non-trial records, in seconds, identical on identical records; it shows 010's holdout records
  (experiment `010-holdout`, contract in `specs/008-model-report/contracts/`) unedited when they
  exist. Re-run the three notebooks and `sentinel report` after any model change. Merged by #98
  (10 Nov), #79 closed. **010 built 10 Nov** (branch `010-holdout-test`; V2-59: the test scores
  the frozen objects the approved notebooks recorded; V2-60: every simpler level beside each
  model): `sentinel holdout --check` (everything but the answers; computes none),
  `--freeze-levels` (done once, 10 Nov: the simpler levels, moved unchanged from the notebooks into
  `src/sentinel/models/levels.py`, re-run on the export of 9 Nov kept in `data/frozen/2026-11-09/`
  (hashes equal to the frozen models' data hashes) gave every recorded test-year number (largest
  difference 6.6e-13), then were frozen for 2023 in MLflow, runs `frozen-levels`), `--run` (run once,
  on 12 Nov, V2-69: the 2023+ answers in memory by the development
  label functions with a later end date; every level and the frozen model per calendar year and
  over all; the rows left out counted; three records in experiment `010-holdout` and one line in
  `data/holdout/log.jsonl`, written only after all three are scored; a second run is refused),
  then `sentinel report` adds the results unedited (`specs/010-holdout-test/quickstart.md`). The
  app now serves on port 8090 (8000 and 8080 belong to other projects; `sentinel serve` refuses a
  busy port, the researcher, 10 Nov). 010 merged by #100 (10 Nov); run once on 12 Nov (V2-69), its report merged by the
  pull request of 12 Nov, which closes #69. Before the daily scores resume (009): train the approved
  models into `data/models/` (`sentinel train results_move`, `sentinel train dilution`; the folder
  still holds Gemini's unapproved files of 2 Nov) and give `prev4_mean` the moves after 2022 (sealed until
  the holdout test; usable since it ran, V2-69).
- **Report (008):** Gemini's typed-in report (numbers contradicting MLflow) was replaced by the
  generated one (#98, 10 Nov; see above).
- **Daily scores (009):** paused until the researcher approves the models (V2-42,
  `update.score: false`); when on, only companies still trading are scored. Live outcomes waited for
  the holdout test (010), run on 12 Nov (V2-69): they may now be computed. `score.daily` holds one
  day (4 Nov) from Gemini's models.
- **App (011–018):** serves Tiingo-derived prices (8.1 M rows, 4,840 companies) without a filter;
  a ticker shared by several companies opens an arbitrary one (`/stock/DIS` can be TWDC
  Enterprises, 2019); the price chart is broken (JSON escaped inside `<script>`); the insider
  feed reads columns that do not exist; the sector filter never matches (Fama-French codes);
  the model card is typed in; a missing `serving.duckdb` silently serves invented data (with an
  insider trade credited to a real person). Spec-kit documents exist only for 011. **Replaced by
  026** (V2-61, below); removed once the researcher approves 026 (FR-024, T021).
- **Stock research app (026, V2-61), 10–11 Nov:** a new, separate app (`src/sentinel/web/`,
  `sentinel web`, port 8100), one page per stock with dilution risk as its main feature and no
  volatility or results-day forecast: search (tickers, names, former names; a reused ticker lists
  each company), facts, the dilution panel (the frozen approved model's chance, band, the band's
  record per test year, reasons from the trees' contributions), a split-adjusted price and volume
  chart (TradingView Lightweight Charts 4.2.0, vendored, V2-62) with insider and offering markers,
  monthly insider buys and sells with the trade table, filings in plain English
  (`web/glossary.py`), FINRA's short-sale share, diagnostics. A missing serving copy shows an error
  and no data. MVP merged by #101 (10 Nov). It shows Tiingo-derived prices; since 12 Nov it runs
  on this computer only, http://localhost:8100, with no Tailscale or other link (the researcher;
  V2-71, replacing V2-64's password link; `scripts/start_web.sh` never touches Tailscale). Never
  share it again without the researcher's decision.
  The named cases checked (T019, 12 Nov): `python -m sentinel.web.named_cases` compares every
  section of 13 named companies' pages with the build database, the frozen model and the SEC's
  files; the first run found two wrong reasons for a missing forecast (a blank-check company, a
  listed company without prices), fixed; all 130 checks pass, no typed-in dates
  (`docs/report/app_named_cases.md`). Found on the way: a company that filed fund reports since
  2012 stays a fund (`ref.company.is_fund`) and gets no prices, so former funds now operating
  (Global Self Storage, Seven Hills Realty, NexPoint Diversified Real Estate; 7 listed in all)
  have no prices or forecast: a pipeline rule, for the researcher to decide. Left
  (`specs/026-stock-research-app/tasks.md`): key financials (T015), daily dilution forecasts in
  the update (T018), insider clusters (T011), short interest (T014, last), the old app removed
  (T021).
- **V2-63 (10 Nov):** a stray Form 4 of another company naming a ticker (DoorDash giving FN) no
  longer cuts a company's price history; rebuilt on 10 Nov with the researcher's agreement (121
  listed companies' histories restored).
- **027 price history repair (11 Nov; V2-65 option C, V2-66 SPAC months):** a read-only audit found
  the rules matching prices to companies cut or mixed many histories (ticker changes dropped
  everything before them; Tiingo's listing dates cut at exchange moves and coverage starts; sister
  companies and typos cut; series of two companies glued; 83,024 ticker-days given to two
  companies; the dilution file lacked 3-9% of company-months). Repaired on branch
  `027-price-history-repair` (`src/sentinel/core/segments.py`: a history is a chain of segments,
  joined across tickers, cut only for earlier holders, holes and SPAC days; one ticker-day one
  company; `sentinel audit`; `sentinel fetch tiingo-former` run once: 812 old tickers). After the
  rebuild of 11 Nov: 18 of 18 named cases pass, no ticker-day twice in one series, histories of
  BNY Mellon, Cencora, Gen Digital, Truist, MGP, Viavi, Palatin, Digital Realty restored (research
  R15). The holdout check refused on 11 Nov because the dilution notebook was re-run on 10 Nov
  11:50 (a second "approved" record on that day's data); superseded by the retraining. On 11 Nov
  evening: `sentinel verify` identical (after a tie fix found by verify); the export of 11 Nov kept
  in `data/frozen/2026-11-11/` (with `split_like.parquet`, 57 answers); the three model notebooks
  (commit d135609) and the EDA re-run on it: the same levels chosen, mean scores 0.2257, 0.4038,
  0.2749 against 0.2260, 0.4038, 0.2791 on 9 Nov, about 3% more rows; `sentinel report`
  regenerated; EDA Findings updated (two small known problems, research R15). The researcher
  approved the three re-run models (V2-68, 11 Nov); `--freeze-levels` reproduced every notebook
  number (largest difference 1.8e-13) and froze the levels; `--check` passes (frozen models from
  commit d135609, export of 11 Nov). #102 and 027 (#103) merged (11 Nov). **The holdout test ran once on
  12 Nov** (V2-69; the researcher asked the agent to run it): dilution LightGBM 0.2292 (2019–2022:
  0.2257), best every year; results-day move LightGBM 0.4672 (0.4038), the ridge better every
  year (0.4517) and the chances of a 10%+ move too low; volatility LightGBM 0.2522 (0.2749), the
  ridge 0.2529. `sentinel report` added the results unedited; a second run is refused. The
  records' files are in `mlruns/9/` at the project root (ignored by git, never delete; a copy in
  `data/backup/after-holdout/`). No model is changed after the test. Do not re-execute the model
  notebooks before the hand-in: each execution writes a new record, which the report would show
  instead of the approved one. **V2-70 (12 Nov):** the dilution answer partly catches up with
  sales already announced (41% of its answers of 1 had a share-sale filing after the start
  count); with nothing announced the model's AUC is 0.87 against 0.89 and its band 5 diluted 33%
  against 41% (2019–2022); `python -m sentinel.models.catching_up` writes
  `docs/report/dilution_catching_up.md`, for the report's limitations (019).
- **Options (023):** the spot price comes from a table that does not exist (falls back to the
  median strike or 100); the tables now live in schema `live` (a rebuild cannot reproduce them).
- **Process:** no pull requests since #90; three of the last five CI runs on `main` failed.
  Decided 4 Nov (V2-43): every change by pull request; `main` protected.
- **Found by the audit, older than Gemini (V2-18):** a company that leaves the SEC's current
  ticker list loses its whole price history at the next build (20 companies on 4 Nov, among them
  bankruptcies such as Advent Technologies): survivorship bias that grows daily and changes the
  training rows. Decided 4 Nov (V2-45): a company keeps the tickers of the last stored SEC list
  it was in, priced up to that list's day; implemented with tests, applied by the next daily
  rebuild.

**State as of 30 October (evening):**

- **Branches**: everything is merged into `main` (30 Oct: #88 001, #89 004, #90 022); only
  `main` exists. Still open in 001: T046 (check a weekday 10:00 run's log, a same-day rerun that
  says `nothing_new`, and `sentinel verify`); T059 (confirm the schedule). GitHub issues #68 and
  #76 still need closing comments (the agent's issue writes were blocked on 30 Oct).
- **Data**: every source current to 29 October 2026; the build, serving copy and export were
  rebuilt on 30 October with all cleaning rules (V2-22 to V2-32). The pipeline's cleaning is now
  frozen (V2-33): further cleaning belongs to each model's preprocessing.
- **Who builds what**: the teammate (`sonson033`) builds **007 (dilution)**; the researcher,
  with the agent, builds 005 (volatility), 006 (results-day move) and everything else.
  `data/exports/share/teammate-007-dilution-2026-10-30.zip` (private, git-ignored) holds the
  dilution training set, `latest`, `feature_snapshot` and the column guide, with
  `README-teammate.md` saying what to read and do; the researcher sends it privately.
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

### Step 2 · Finish 001 (merged 30 Oct; checks left)
- [X] T046 (5 Nov): the 10:00 run `complete` in 47 min (V2-47: 60 allowed); verify identical
  after the fixes of 5 Nov; the rerun `nothing_new` (details in the 001 tasks file).
- [X] T059 (5 Nov): the researcher keeps the schedule at weekdays 10:00.
- [X] T062–T063 (5 Nov): docs; the quickstart's checks and the full checks pass (201 tests).
- [X] Merged into `main` (#88, #89, #90; the checks of 4–5 Nov by #91), branches deleted; #68 and
  #76 closed (5 Nov).

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
- [X] 002 (#73): `sentinel export --reference` → `data/exports/reference/`: each question's
  rows for every year in the training files' exact columns plus `period` (development / gap /
  holdout), answers wherever windows have closed; never read by model code; log V2-21.
- [X] 003 (#75): GitHub Actions (ruff, format, unit tests on every pull request), `main`
  protected, pull-request template, a CI check that rejects notebooks with outputs (nbstripout is
  already installed as a filter), README "Working together". `main` protected (checked 10 Nov:
  the CI check and pull-request reviews required, admins included); issue #75 still open.

### Step 5 · The three models (007 dilution, 006 results-day move, 005 volatility if time)
For each, in order 007 → 006 → 005 (V2-48: 005 only if time allows before the holdout test):
1. spec-kit specify → plan → tasks (`SPECIFY_FEATURE_DIRECTORY=specs/00N-…-model`).
2. Fill its notebook (`notebooks/00N-*-model.ipynb`): the instructions on top say exactly what
   (rules, the EDA's findings for that model, the holdout, ten sections). Build, run and tune
   every level there: naive baseline → rule → classic model → LightGBM, walk-forward test years
   2019–2022 with the purge, the simplest level within one standard error of the best
   (V2-50: the standard error of the four yearly differences from the best level),
   calibration, bands with hit rates, MLflow, fixed seeds. End with a verdict per hypothesis of
   `docs/hypotheses.md` (V2-46): family checks and direction checks on the test years.
   **Splits only by `eda.folds` and `eda.check_folds`** (inner-train, gap, validation, purge,
   test: all cut by dates, checked; the holdout refused), and `eda.known_before(rows, question,
   day)` before every fit: the model, its settings, the calibration, the band edges, the
   volatility range, each with the start of the period it is judged on. **Every fitted step is a
   `sentinel.models.dated.Dated`** (V2-49): it refuses answers not known before its cutoff and
   rows dated before it, and refuses early stopping; settings are chosen by fitting on one block
   and predicting a later one, never by random cross-validation.
3. Show the researcher the executed notebook; wait for approval.
4. Move the approved model into `src/sentinel/models/` with tests and a command; the notebook
   imports it and gives the same numbers.

### Step 6 · 008 Model report, 009 Daily scores
- [X] 008 (#79): `sentinel report` regenerates the report from the notebooks' MLflow records
  (merged by #98, 10 Nov).
- [ ] 009 (#74): `sentinel update` scores every covered company daily into `score.daily`; paused
  (V2-42) until the approved models are trained into `data/models/`; `score.outcome` waited for
  the holdout test, run on 12 Nov (V2-69).

### Step 7 · The app: 026 stock research app (V2-61), with the researcher
- [X] 026 MVP (10 Nov, #101): search, facts, dilution panel, price and volume chart, insiders,
  filings in plain English, short-sale share, diagnostics; on this computer only (V2-71).
- [ ] 026 later tasks, in this order: key financials as first filed (T015); ten named cases
  checked against the data (T019, SC-002: done 12 Nov, 13 cases); the daily dilution forecasts
  in the update (T018,
  with 009); insider clusters (T011) and short interest (T014) if time allows; the old app
  removed once the researcher approves 026 (T021).
- Gemini's old app, kept until T021 (V2-61 replaces it; its faults are in section 7):
- [ ] 011–017 (built by Gemini, replaced by 026): on branch `011-app-design`. Design and forecast contract (`specs/011-app-design/contracts/`),
  FastAPI read-only API over `data/serving.duckdb` (`src/sentinel/app/`, on port 8090, refusing a busy port), stock research terminal
  with the four Sentinel intelligence panels, live interactive price chart, reported financials, Form 4 insider activity,
  and SEC filings. Multi-factor screener, market insider feed, and model card view. Tested with 8 unit tests in
  `tests/unit/test_app_api.py`. CLI entrypoint: `sentinel serve` (port 8090, this machine only by default).
- [ ] 018 (026 runs on this computer only, V2-71; Gemini's Docker files are the old app's): Hosting / production deployment configuration with no Tiingo-derived value on a public page. Dockerfile and docker-compose.yml serving read-only over port 8090, audited by test_public_data.py.

### Step 7b · 027 Price history repair, then retrain and test (V2-65, V2-66)
- [X] Spec, plan, tasks; the audit and its baseline; the repair with tests; the old tickers'
  download; the rebuild (11 Nov); 18 of 18 named cases.
- [X] `sentinel verify` identical (11 Nov); the EDA notebooks re-run, Findings updated; the hand
  check recorded (2 of 30 wrong, the pattern fixed); decision V2-67.
- [X] The three model notebooks re-run on the repaired export (11 Nov; kept in
  `data/frozen/2026-11-11/`); `KEPT` read from the approved records (T033).
- [X] The researcher's approval (T035, V2-68); `sentinel holdout --freeze-levels` and `--check`
  (T036, 11 Nov).
- [X] The holdout `--run` (T037), once, on 12 Nov (V2-69: run by the agent at the researcher's
  request); `sentinel report` regenerated.

### Step 8 · 010 Holdout test (run 12 November)
**Status: done (12 Nov, V2-69).** Built and merged by #100 (10 Nov); after the price repair (027) the
models were approved again (V2-68) and the levels frozen again; run once on `main` at `ed41646`, the
results added unedited to the model report by `sentinel report`; a second run is refused.
**Already true (checked 30 Oct):** the holdout rows (`feature_snapshot` from 2023 on, built from
`feature.snapshot` like the training files) have the training files' feature columns in the same
order and types; the holdout answers come from the same label code (`labels/risk.py`) with
`development.last_window_end` replaced by the latest closed window inside the guarded command
only. **Required of every model** (in each model notebook's instructions): features selected by
name, all preprocessing inside the saved model, one saved object with feature list, eligibility
flag, seed, commit and export date, one `predict(model, rows)` function, and a dry run on the
2023+ feature rows (no answers) before the test. **To build in 010:** the guarded command; a unit
test that the label code with a later end date gives exactly the development answers for
2012–2022 rows; the comparison of each model with its baselines on the holdout.

Build a guarded command: it refuses unless the models are frozen (approved, in
`src/sentinel/models/`, logged in MLflow with commit and data version) and no earlier holdout
run exists; it computes the 2023+ answers, scores the frozen models, writes the results and a
log entry; a second run is refused. The researcher triggers it. Results go into the report as
they came out; no model change afterwards.

### Step 9 · 019 Hand-in (17–18 November)
Product v1 on 17 November, report on 18 November, both regenerated by commands from a clone plus
the data. The report's limitations include the dilution answer's catching-up effect (V2-70,
`docs/report/dilution_catching_up.md`).

### Feature 023 · Options benchmark and on-demand option chains (3 Nov)
- [~] 023 (spot price wrong; tables moved to schema `live` on 4 Nov): On-demand option chain fetcher (`src/sentinel/raw/options.py`) downloading all expirations up to 365 days;
  stores raw Parquet snapshots in `data/raw/options/` with manifest lines; relational tables `live.option_chain`
  and `live.option_summary` in DuckDB (`src/sentinel/core/options.py`); 30d/60d/90d ATM implied volatility benchmarks;
  CLI command `sentinel options <ticker>` and API route `/api/options/{ticker}`. Tested with 4 unit tests (172 total tests pass).

### Later, if the researcher asks · 024 Offering-event question
A second dilution question, "will the company file a share offering in the next 6 months?",
measured from the offering filings themselves, whatever the size; see `docs/plan.md` row 024. The
10% definition stays for 007 (the researcher, 30 Oct).

### Step 10 · 020 Before Tiingo ends (by 25 November) and 021 (January 2027)
- [ ] 020 (#72): a fresh clone plus `data/raw/` rebuilds every layer identically; back up
  `data/raw/` to a second disk. Never delete Tiingo files (the researcher's decision).
- [ ] 021 (#87): quarterly refit with a logged comparison; first in January 2027.
