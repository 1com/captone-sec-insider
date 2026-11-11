---

description: "Task list for feature 027, the price history repair, then retrain and test"
---

# Tasks: Price history repair, then retrain and test

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/audit.md](contracts/audit.md), [quickstart.md](quickstart.md).

**Tests**: requested (spec FR-002–FR-012, SC-001–SC-007; plan "Testing"): synthetic unit tests per
rule, named real cases, the truncation test and `sentinel verify`.

**Organization**: by user story (spec.md); research decisions R1–R14 quoted where they fix a rule.
Every heavy step runs under the memory cap (`systemd-run --user --scope -p MemoryMax=5G -p
MemorySwapMax=0`), one at a time, never during the 10:00 update; the branch stays green at 10:00.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story of spec.md (US1–US6)

---

## Phase 1: Setup

- [X] T001 Record the 11 Nov audit scripts' results as the baseline numbers in `specs/027-price-history-repair/contracts/audit.md` (done in planning) and check `git status` is clean apart from `notebooks/test.ipynb`; confirm the branch `027-price-history-repair` is based on `026-stock-research-app` (V2-63's code)

---

## Phase 2: Foundational (blocking)

**Purpose**: the segment table every rule writes into, the audit that measures before and after,
and the old tickers' prices the joins need.

- [X] T002 Segments: `core.price_choice` becomes one row per segment with columns `cik, seq, source, ticker, reason, trim_from, trim_to, listed, main, adj_factor` ("a company's segments do not overlap"; "`main` is unique per company"; `adj_factor` 1 for the main segment) in `src/sentinel/core/prices.py` `build_choice`, still one segment per company at this step (behaviour unchanged); `ref.security`, `core.price_coverage` (`build_security`, `build_coverage`) and `src/sentinel/validation.py` read the `main` row; new empty table `core.price_decision (cik, kind, ticker, source, day_from, day_to, other_cik, detail)` with `kind` in `joined, join_failed, cut_reuse, cut_hole, cut_blank_check, lost_to, kept_overlap`
- [X] T003 `build_daily` multiplies each segment's adjusted prices (`adj_close`) by its `adj_factor` in `src/sentinel/core/prices.py`; existing tests in `tests/unit/test_core_prices.py` pass unchanged (one segment per company)
- [X] T004 [P] The audit (research R12, contract `contracts/audit.md`): `src/sentinel/audit.py` computes, read-only on the build database, the families of the JSON layout (cuts with stored prices by cause and clear evidence, with company-months 2012–2022; ticker changes not joined and how many old prices are stored; holes over a year and 31–365 days; listed without price and with another ticker's data; disappeared prices ending over a year before the last report; disappeared US companies with Form 4s and no prices; ticker-days claimed twice; blank-check periods once T016 exists), five examples per family ordered by CIK; writes `data/audit/prices-<date>.json`; exit code 1 when a ticker-day is claimed twice or a named case fails
- [X] T005 [P] `sentinel audit` in `src/sentinel/cli.py` (refuses while another process writes the database, as the other read-only commands do)
- [X] T006 [P] Tests in `tests/unit/test_audit.py`: a synthetic world with one case per family gives each count once; the examples are stable across two runs
- [X] T007 Baseline: run `uv run sentinel audit` on the build of 11 Nov (before any rebuild) and check it reproduces the counts in `contracts/audit.md` (1,162 cut; 943 listing start; 219 other use; 256 clear; 370 ticker changes; 39 + 28 holes; 152 early ends; 83,024 ticker-days on 120 tickers); keep `data/audit/prices-2026-11-11.json` as the "before"
- [X] T008 [P] `fetch_former` in `src/sentinel/raw/tiingo.py` (research R9): for each ticker named by a company's own evidence (`ref.ticker_history`: `form4`, `sec_list`) with no stored Yahoo or Tiingo series, whose lines in Tiingo's list overlap the company's use, ask prices from `prices.history_start` and the description once; store `tiingo/former/<T>.csv.gz` and `tiingo/former_meta/<T>.json.gz` with manifest lines (`former/<T>`, `former_meta/<T>`, role `original`); refuse outside `[tiingo.paid_from, tiingo.paid_until)`; skip what is stored; the token only in a header
- [X] T009 [P] `sentinel fetch tiingo-former` in `src/sentinel/cli.py`; `former_meta` added to `TIINGO_META_DIRS` in `src/sentinel/staging/prices.py` (price files are found through the manifest already)
- [X] T010 [P] Tests for T008–T009 in `tests/unit/test_raw_tiingo.py` (or the existing Tiingo test file): outside the paid window nothing is asked; a stored ticker is not asked again; files and manifest lines land where staging reads them (with a fake HTTP client)
- [X] T011 Run `uv run sentinel fetch tiingo-former` once (about 1,400 requests, 12 minutes; Tiingo only before 26 Nov), then stage Tiingo under the memory cap (`sentinel build staging --only tiingo`); record the counts asked, stored, without data

**Checkpoint**: segments exist; the audit's "before" is kept; the old tickers' prices are staged.

---

## Phase 3: User Story 1 - A company that changed its ticker keeps its whole history (P1)

**Goal**: one continuous history across a company's tickers; SPAC months are not its history
(FR-001, FR-002, FR-007, FR-017).

**Independent Test**: MGP Ingredients, Viavi, Xcerra and Hanger span their tickers with no gap at
each switch; DocGo and Redwire start at their mergers.

- [X] T012 [P] [US1] Tests in `tests/unit/test_core_segments.py`: a rename joined when the provider's name matches the company's names (or the SEC list named the ticker for it) and the series meet ("at most 10 trading days" apart, "within a factor of 1.5 once a split recorded at the switch is allowed for"); refused with `join_failed` on a gap, on a level jump, and on a typo ticker whose provider name does not match; at most five segments; a disappeared company joined across its tickers too
- [X] T013 [P] [US1] Test in `tests/unit/test_core_segments.py`: the adjusted return across a switch equals the as-traded move (research R10), with a dividend and a reverse split after the switch
- [X] T014 [P] [US1] Test in `tests/unit/test_core_segments.py` (research R11): a company whose ticker changes after day D keeps every price and feature row up to D unchanged once the new ticker and its evidence are added
- [X] T015 [US1] Joins in `src/sentinel/core/prices.py` (research R2, R3): own tickers from `ref.ticker_history` (`form4`, `sec_list`) besides the main one; identity by `identity()` against `all_names` for Tiingo series, by SEC-list evidence for Yahoo series; the chain built backwards from the main segment, newest old ticker first; `adj_factor` of each earlier segment = later segment's adjusted ÷ as-traded close on its first day divided by the earlier segment's on its last day; `joined` and `join_failed` written to `core.price_decision`
- [X] T016 [P] [US1] Tests in `tests/unit/test_core_prices.py` for blank-check days (research R7, V2-66): a former name matching "`(ACQUISITION|ACQUISITIONS|MERGER) (CORP|CORPORATION|CO|COMPANY|INC|LTD|LIMITED|HOLDING|HOLDINGS|GROUP|TRUST)`, `SPAC` or `BLANK CHECK`" as whole words counts when it lasted "at most 3.5 years or the price sat between $9 and $11 on at least half of the name's priced days"; "OYO GEOSPACE CORP" and "AST SpaceMobile" do not match; a 7-year bank name with prices away from $10 does not count; no segment covers counted days; a SPAC ticker is never joined; current SIC 6770 still excludes the company
- [X] T017 [US1] `core.blank_check_period (cik, former_name, valid_from, valid_to, years, near_10, counted)` built in the price step of `src/sentinel/core/prices.py` from `ref.company.former_names` and the staged prices of the company's tickers; counted days cut from every segment (`cut_blank_check` with the former name)
- [X] T018 [P] [US1] `app.stock` gains `listed_via` and `listed_via_date` (the counted former name and its last day) in `src/sentinel/serving/publish.py`; the stock page shows "listed through a merger with <name> on <date>" in `src/sentinel/web/templates/` with a test in `tests/unit/test_web_app.py`

**Checkpoint**: ticker changes join on synthetic data; SPAC days excluded.

---

## Phase 4: User Story 2 - A history is cut only where another company really held the ticker (P1)

**Goal**: no cut at exchange moves, coverage starts, sister companies or typos; one ticker-day,
one company (FR-003, FR-004).

**Independent Test**: Palatin and AMN Healthcare from January 2010; Digital Realty from January
2010, its operating partnership without DLR prices; Fabrinet unchanged.

- [X] T019 [P] [US2] Tests in `tests/unit/test_core_segments.py`: an exchange move (two Tiingo lines back to back) and a coverage start (one line beginning in 2016 while Yahoo has 2010) do not cut; another company's use overlapping the company's own use, including one ending the same day, does not cut (`kept_overlap`); a use that ended before the company's own first use cuts (`cut_reuse`); the stray-filing test of V2-63 still passes
- [X] T020 [P] [US2] Tests in `tests/unit/test_core_prices.py` for one ticker-day one company (research R5): two companies on one series over overlapping days → the overlap goes to the one in the SEC list for the ticker, else to the one with more own Form 4 filings printing it during the overlap, else to the lower CIK; the loser's segment trimmed with `lost_to`; no (source, ticker, day) twice in `core.price_daily`
- [X] T021 [US2] In `src/sentinel/core/prices.py`: remove the Tiingo listing-start trim from `build_choice` (`listing_start` stays in `core.price_candidate` for the audit); `_other_use_ends` keeps only uses that ended before the company's own first use of the ticker (overlaps write `kept_overlap`); the pairwise resolution after all segments are chosen (R5)

**Checkpoint**: the US2 tests pass with the US1 tests.

---

## Phase 5: User Story 3 - One series never mixes two companies (P1)

**Goal**: the part of a series before a hole of over a year is not a company's unless its own
evidence covers it (FR-005).

**Independent Test**: Standard BioTools holds none of LaBranche's prices; Heidmar holds no 2010
block.

- [X] T022 [P] [US3] Tests in `tests/unit/test_core_segments.py`: a block before a gap of over 365 days without own evidence is cut (`cut_hole`); one covered by the company's own Form 4 span (widened by 400 days before and 90 after) or an SEC-list entry is kept; a gap of 31–365 days stays
- [X] T023 [US3] The hole rule in `src/sentinel/core/prices.py` (research R6), applied to every segment before the joins of T015 look for an earlier ticker

---

## Phase 6: User Story 4 - Every listed company with a usable series is priced, from its common stock (P2)

**Goal**: FR-006.

**Independent Test**: Telephone & Data Systems priced as TDS; Chatham Lodging as CLDT; foreign ADR
pairs unchanged.

- [X] T024 [P] [US4] Tests in `tests/unit/test_core_segments.py`: a US filer whose first SEC ticker has no data is priced from the next plain ticker with data; a preferred first and a plain one listed → the plain one; a foreign company with an ADR without data and an ordinary share with data stays unpriced
- [X] T025 [US4] In `build_candidates`/`choose` of `src/sentinel/core/prices.py` (research R8): for `filer_type = 'us'`, the main Yahoo candidate is the first SEC ticker with data, plain tickers before suffixed ones; other companies unchanged

---

## Phase 7: Rebuild and named cases (blocks US5's "after" and US6)

- [X] T026 Full checks before the rebuild: `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q` (the truncation test included)
- [ ] T027 Rebuild under the memory cap (quickstart step 3): reference, core, features, labels, publish, export; then `uv run sentinel verify` (a full rebuild equals the update)
- [ ] T028 [P] Named real cases in `tests/real/test_named_cases.py` (FR-012): MGP Ingredients and Viavi from 2010 under their old tickers; Ingersoll Rand from 12 May 2017; Digital Realty from 2010 and its operating partnership without DLR prices; Palatin and AMN Healthcare from 2010; Standard BioTools without LaBranche's prices; Heidmar without its 2010 block; Telephone & Data Systems priced; Chatham Lodging from CLDT; Xcerra and Hanger across their tickers; DocGo and Redwire from their mergers; Fabrinet from 2010; run with `uv run pytest -q tests/real`

---

## Phase 8: User Story 5 - Price coverage measured by one command (P2)

**Goal**: FR-011; SC-003, SC-006.

**Independent Test**: the "before" JSON (T007) equals the 11 Nov counts; the "after" shows the new
counts and every named case passing.

- [ ] T029 [US5] Named cases and coverage by year and status (listed, disappeared; priced, not) added to `src/sentinel/audit.py`; `docs/report/data_audit.md` written with counts and pass/fail only (no price, date or company derived from Tiingo values), before and after side by side
- [ ] T030 [US5] Run `uv run sentinel audit` on the rebuilt data; compare with the baseline; no ticker-day twice (SC-007); every remaining hole over a year has a recorded reason (SC-003)
- [ ] T031 [US5] Draw 30 remaining cuts at random (fixed seed) from `core.price_decision` and check each by hand against the SEC filings and the providers; record the share found wrong in `docs/decisions.md` (SC-006: at most 3)
- [ ] T032 [US5] Re-run the three EDA notebooks (`notebooks/004-eda-*.ipynb`, under the cap) and update their Findings where numbers move

---

## Phase 9: User Story 6 - Retrain, approve again, then the one holdout test (P1)

**Goal**: FR-013–FR-015; SC-008. Depends on Phases 2–8.

**Independent Test**: `sentinel holdout --check` passes on the new kept rows; the frozen objects'
data fingerprints equal the kept files'.

- [ ] T033 [US6] `KEPT` in `src/sentinel/holdout.py` read from the approved frozen models' `export_date` tag instead of the fixed "2026-11-09", with the kept files' hashes required equal to their `data_hash`; tests in `tests/unit/test_holdout.py`
- [ ] T034 [US6] Re-run `notebooks/007-dilution-model.ipynb`, `006-results-move-model.ipynb`, `005-volatility-model.ipynb` start to finish on the new export (unchanged; under the cap, one at a time), then `uv run sentinel report`
- [ ] T035 [US6] The researcher reads the three executed notebooks and approves each (or not); approvals logged in `docs/decisions.md`; only approved models count as frozen
- [ ] T036 [US6] Keep the export the approved models ran on in `data/frozen/<export date>/ml/` (`cp -p`), check its hashes against the frozen runs' `data_hash`; `uv run sentinel holdout --freeze-levels` (must reproduce the notebooks' records to 1e-9); `uv run sentinel holdout --check`
- [ ] T037 [US6] The researcher runs `sentinel holdout --run` once, by Tue 17 Nov if T026–T036 are done, otherwise after the hand-in (never on a partial repair); then `uv run sentinel report`

---

## Phase 10: Polish and hand-over

- [ ] T038 [P] `docs/decisions.md`: the price-matching rules of 027 as one decision (segments, joins, cuts, one ticker-day, common stock first), with the before and after counts; `docs/architecture.md` layer 3b updated (segments, `core.price_decision`, `core.blank_check_period`)
- [ ] T039 [P] `docs/plan.md` (027 status), `README.md` (`sentinel audit`, `sentinel fetch tiingo-former`), `AGENTS.md` (where things stand; step for 027); this file's boxes ticked
- [ ] T040 Pull request into `main` after #102 is merged and the researcher agrees (CI green); then delete the branch

---

## Dependencies and order

- Phase 2 (T002–T011) blocks everything; T007 (baseline) must run before any rebuild.
- US1 (T012–T018), US2 (T019–T021), US3 (T022–T023) and US4 (T024–T025) all change
  `src/sentinel/core/prices.py`: done one after another (US3's hole rule before US1's joins look
  for earlier tickers; US2's resolution after all segments). Their tests ([P]) can be written
  together.
- Phase 7 (rebuild) needs US1–US4; US5's "after" (T030–T032) and US6 (T033–T037) need Phase 7.
- T033 can be done any time before T036.

## Parallel examples

- After T002–T003: T004–T006 (audit), T008–T010 (download) in parallel files.
- Tests T012, T013, T014, T016, T019, T020, T022, T024 in parallel (one test file, separate tests).
- T028 (named cases) with T029 (audit summary) after the rebuild.

## Implementation strategy

1. Thu 12 Nov: Phase 2, the baseline audit (before the 10:00 update is not needed: it reads only),
   the download; US3, US1, US2, US4 with their tests; full checks green before any 10:00 run.
2. Fri 13 Nov: rebuild (T027), verify, audit after, named cases, hand check, EDA re-run.
3. Sat 14 – Sun 15 Nov: the three notebooks (T034); the researcher's review (T035).
4. Mon 16 Nov: keep, freeze, check (T036). Tue 17 Nov: the holdout run if ready (T037); product v1.
5. MVP: if time runs short, the repair (US1–US4) and the audit still improve the app for 17 Nov; the
   holdout waits (never on a partial repair).
