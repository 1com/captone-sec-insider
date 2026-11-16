---

description: "Task list for feature 019, the hand-in (presentation, live demo, repository)"
---

# Tasks: The hand-in (presentation, live demo, repository)

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md).
**Tests**: included for the code this feature adds (the number sheet, the app's model section, the
README's results table). **Deadline**: the dry run on Wednesday 18 Nov 2026 needs Phases 1-4.

## Phase 1: Setup

- [X] T001 Branch `019-hand-in`; spec, checklist, plan, research, data model, contracts, quickstart and
  tasks in `specs/019-hand-in/`
- [X] T002 Record the hand-in as it now is (a presentation, a live demo and the repository; no written
  report; 15 minutes in all; the dry run on 18 Nov) in `docs/plan.md` (row 019, next steps, the
  timeline row of 16-18 Nov), `AGENTS.md` (section 7 and step 9) and the roadmap of `README.md`

## Phase 2: Foundational (the numbers every deliverable uses)

- [X] T003 [P] Tests in `tests/unit/test_presentation.py`: the sheet's values equal the model card's
  (`dilution`, `results_move`, `volatility` → `holdout`, and `dilution` → `test_years`) and the
  catching-up and audit reports' tables; `dil.best_years` and `mov.ridge_better_years` computed per
  year; the rounding of [contracts/number-sheet.md](contracts/number-sheet.md); identical inputs give
  an identical file; a missing input or an absent level, year or table is refused and nothing is written
- [X] T004 `src/sentinel/presentation.py` (`python -m sentinel.presentation`): writes
  `docs/presentation/numbers.md` per the contract, with a short "Terms" part (dilution, log loss, AUC,
  band, look-ahead, the one-time test) in plain words for questions (FR-005); the serving copy read
  read-only with `db.MEMORY_LIMIT`
- [X] T005 Generate `docs/presentation/numbers.md` on the data of 16 Nov (after the 10:00 update) and
  compare its dilution numbers with the model report's "The holdout test (010)" by eye. Done 16 Nov,
  after V2-74 was applied: data to 13 Nov, 6,917 companies still trading, 3,682 dilution forecasts;
  every dilution number equal to the report's tables (the rate of 12% is the bands' rows-weighted mean)

## Phase 3: User Story 1 - Follow the talk and judge the work (P1)

**Goal**: about 10 slides for about 8.5 minutes. **Independent test**: a timed run-through of the
slides alone; every number found on the sheet.

- [X] T006 [US1] The slides as a claude.ai Slides artifact (private), from the outline in
  [plan.md](plan.md): 10 slides, a chart of log loss per level on the one-time test and a chart of the
  bands' forecast against what happened, speaker notes with times; every number by id from
  `docs/presentation/numbers.md`; no value derived from the private price source. All 10 written by
  16 Nov (slide 3's counts from the sheet of 16 Nov); checked by T007, reviewed by T008
- [X] T007 [US1] Number check (SC-002): slide, id, number shown and the sheet's value, compared one
  by one, recorded in `specs/019-hand-in/slides-check.md`. Done 16 Nov on the deck's version 12:
  39 ids in 44 places, 0 differences; the other numbers checked against their sources; seven
  slides' wording corrected (none a number); the notes' times 13:40 of 15 minutes
- [ ] T008 [US1] The researcher's review (the names on the title slide; the lessons slide) and the
  changes; PDF and PowerPoint downloaded the day before the dry run as the offline copy

## Phase 4: User Story 2 - See the app answer for real companies (P1)

**Goal**: a 5-minute demo path on the live app that shows the one-time test's record. **Independent
test**: one timed run of `demo.md` on the live app.

- [X] T009 [P] [US2] Tests in `tests/unit/test_web_app.py`: a company page's data carries
  `model.card.holdout` (`results`, `bands`, `rows`, `first_row`, `last_row`, `date`) from the model
  card; the page script reads them and holds no typed-in result
- [X] T010 [US2] `src/sentinel/web/static/app.js` per
  [contracts/app-model-section.md](contracts/app-model-section.md): the dilution panel shows the
  company's band's record on the one-time test beside the test years'; the model section adds the
  one-time test's log loss and AUC per level and year and its calibration table; the limits sentence
  names the test's date; unchanged when `holdout` is absent
- [ ] T011 [US2] Pick the demo companies on the data of 16 Nov by the roles in [plan.md](plan.md),
  each with a spare, and write `specs/019-hand-in/demo.md`: per step the company (name, ticker, CIK),
  the spare, what to open, what to point at, what to say and the time; no exact chance or price
- [ ] T012 [US2] Add the demo companies not yet among the named cases to
  `src/sentinel/web/named_cases.py`; `python -m sentinel.web.named_cases` passes in full;
  `docs/report/app_named_cases.md` regenerated (verdicts only)
- [ ] T013 [US2] Backup screenshots of each step in `data/handin/backup/` (git-ignored; Chrome on
  Windows, headless), never committed and never in the slides
- [ ] T014 [US2] Timed walk-through of `demo.md` on the live app (about 5 minutes), checked on
  17 Nov and on the morning of 18 Nov; spares used where a company no longer fits

## Phase 5: User Story 3 - Open the repository as a grader (P2)

**Goal**: a front page a newcomer understands in a few minutes; a fresh copy installs and passes.
**Independent test**: quickstart sections 4 and 5; the first screen names the question and the
dilution model's one-time test result.

- [ ] T015 [P] [US3] `tests/unit/test_readme_numbers.py`: the README's results table equals the model
  card's one-time test numbers, rounded as on the number sheet
- [ ] T016 [US3] `README.md` front page per [research.md](research.md) R6: what the project answers
  (the app serves the dilution forecast only, V2-61, V2-72), the one-time test's results, the app and
  how to start it, how it works, the rules, installation and commands, a map of the folders, the
  limits; the current sections under "Working notes"; no screenshot of the app
- [ ] T017 [US3] A fresh copy of the public repository in the scratchpad, installed by the README,
  passes ruff, the format check and the unit tests without `data/` (quickstart section 4)
- [ ] T018 [US3] Only once the researcher approves the new app (026 T021, FR-015): remove
  `src/sentinel/app/`, `tests/unit/test_app_api.py`, the old app's other tests, `Dockerfile`,
  `docker-compose.yml` and the `sentinel serve` command in `src/sentinel/cli.py`; docs updated;
  `specs/011-app-design/` kept as history

## Phase 6: Polish

- [ ] T019 Privacy scan (quickstart section 5) of the repository, the number sheet and the slides;
  `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q`
- [ ] T020 Docs in step (`docs/plan.md`, `AGENTS.md`, `README.md`); pull request after the researcher
  agrees; #71 closed with the researcher's agreement after the final presentation
- [ ] T021 After the dry run: its feedback applied to the slides and the demo; the final slides' PDF
  committed to `docs/presentation/` if the researcher wishes (aggregates only)

## Dependencies

- T004 (the numbers) before T006, T007 and T016; T003 with T004.
- T010 (the app shows the test) before T011, T013 and T014; T009 with T010.
- T011 before T012, T013 and T014.
- T018 waits for the researcher's approval of 026.
- User Stories 1 and 2 are independent of each other once Phase 2 is done; User Story 3 needs only
  Phase 2.

## Parallel opportunities

- T003 and T009 and T015 (three test files).
- After Phase 2: the slides (T006-T008) and the app change and demo path (T009-T012).

## Implementation strategy

1. For the dry run (18 Nov): Phase 2, then the app change (T009-T010), the demo path (T011-T012), the
   slides (T006-T007), then the backup and the timed walk-through (T013-T014) and the researcher's
   review (T008).
2. Before the final presentation: User Story 3 (T015-T017; T018 on approval), the dry run's feedback
   (T021), Phase 6.
