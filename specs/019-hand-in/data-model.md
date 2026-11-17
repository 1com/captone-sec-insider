# Data Model: The hand-in (019)

No database tables change. The feature's things, their fields and their rules:

## Number (one row of the number sheet)

| Field | Meaning |
|---|---|
| id | a stable name such as `dil.ll.lightgbm` ([contracts/number-sheet.md](contracts/number-sheet.md)) |
| value | the exact value in its source |
| shown | the value as a slide shows it (fixed rounding per kind: log loss 3 decimals, AUC 2, shares as percentages, counts with thousands separators) |
| source | the generated file or the serving copy it comes from, with the table or section |
| meaning | one line in plain words |

Rules: every value is an aggregate over many companies; no value derived from the private price
source at the level of one company; the sheet is generated, never edited by hand.

## Slide

| Field | Meaning |
|---|---|
| n, title | order and title |
| time | minutes and seconds; all slides together about 8.5 minutes |
| content | what the slide shows |
| numbers | the number ids it uses (no number without an id) |
| notes | what to say, in plain words, with each term explained the first time |

## Demo step

| Field | Meaning |
|---|---|
| n, role | order and what it shows (for example "left out by a rule") |
| company | name, ticker and CIK of the company used |
| spare | the company used if the first one no longer fits the role |
| open, point at, say | what to click, what to show on the page, what to say |
| time | seconds; all steps together about 5 minutes |
| checked | the dates it was checked on the live app (the day before, the morning of) |

A step is *candidate* until checked on the live app, then *checked*; on the day it is *used* or
*spare used*.

## Backup shot

| Field | Meaning |
|---|---|
| step | the demo step it stands in for |
| file | a PNG in `data/handin/backup/` (git-ignored; never committed, never in the slides) |
| taken | the time it was taken and the data date it shows |

## Front page (the README's first part)

Sections in order: what the project answers; the one-time test's results (a table of the
dilution levels with log loss and AUC over all years from 2023, as the model card gives them,
rounded as on the number sheet, and one line for each other question); the app; how it works; the
rules; installation and commands; a map of the folders; the limits. Then "Working notes".
