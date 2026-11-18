# Slides check (T007, SC-002)

*16 Nov 2026. The deck: the private claude.ai Slides artifact, version 12 (10 slides). The sheet:
`docs/presentation/numbers.md` of 16 Nov (data to 13 Nov 2026). Every number on a slide, in its
footer or in its speaker notes was compared with the sheet's "as shown" value. This file holds only
numbers that are already on the sheet or in the committed model card; the slides themselves stay
private.*

## Result

- **39 ids of the sheet appear on the slides, in 44 slide-and-id pairs: every number equals the
  sheet.** `python` check below: each id's value here equals the sheet's, and each number shown is
  found on its slide.
- **The other numbers** (the question's definition, dates, the worked example, the times) were
  checked against their sources (section 2).
- **Wording corrected by this check** (versions 11 and 12; section 3): 7 slides, none of them a
  number.
- **17 Nov, after V2-75:** the sheet was regenerated on 17 Nov's data (to 16 Nov) and slide 3's
  three numbers (`app.companies`, `app.forecasts`, `app.date`, on the slide and in its notes) were
  changed to it (deck version 16); the rows below show them. No other slide holds a number that
  changed: every other id on the sheet is the same as on 16 Nov.
- **17 Nov, after V2-77:** the app's first page lists no companies, so slide 10's first step
  ("Today's highest dilution chances, and a search for any US stock") became "Search any US stock
  by its ticker or name, even a former one", and its notes now open a company by search
  (Alaunos Therapeutics, as in `demo.md`) instead of from the list (deck version 18; version 17
  was a save outside this check that changed no slide). No number changed.
- **17 Nov, after V2-78:** the talk presents the data platform and the dilution model only (the
  researcher: the volatility and results-day models are not part of the project). Slide 8, "The
  other two models", removed: its six ids (`vol.*`, `mov.*`, the rows marked below) are no longer
  on the deck, which now shows 33 ids in 38 slide-and-id pairs. Slide 3's third box, "Four
  questions", became "The dilution question", with its notes. Slide 9's second lesson (now slide
  8) was about the results-day model; it is now the daily update reported as fixed and verified
  that had stopped on three mornings in a row (source in section 2). The deck has 9 slides; the
  notes' times: slides 1-8 take 7:45, with the demo and the close 12:55 of 15 minutes (deck
  version 20; version 19 was a save outside this check that changed no slide). No remaining
  number changed.
- **17 Nov, a data-engineering slide** (the researcher: "ok"): slide 4, "How the data stays
  right", after slide 3 (deck version 23; 10 slides; the notes' times: slides 1-9 take 8:30, with
  the demo and the close 13:40 of 15 minutes). Its numbers and their sources: 10:00 every weekday
  (the schedule, `sentinel schedule show`; 001 T059); "usually in under an hour" (notes: the
  update logs, 8 of the 9 scheduled runs since 5 Nov took 43-51 minutes, 16 Nov 191 minutes with
  the SEC slow); "run again with nothing new, it changes nothing" (the reruns of 5 and 13 Nov:
  `nothing_new`); 0 tables differ (`sentinel verify` identical on 13 Nov, 009 T013); 231 checks of
  21 companies, none failed (`docs/report/app_named_cases.md`: 21 named cases, 11 sections each,
  0 failed); 1,000 times too small (V2-75: Tempus AI's 181,311 for about 181 million shares; the
  rule withholds a forecast when the value traded per day is more than 10 times the market value,
  so the slide says the rule checks every company, not that it catches every such count).
- **Times in the notes:** slides 1-9 take 8:30 (0:15, 1:00, 1:00, 1:15, 0:45, 1:30, 0:45, 0:45,
  1:15), the demo 5:00 and the close 0:10. That makes **13:40 of the 15 minutes**.
- **18 Nov, after V2-80:** the talk tells the whole product (deck version 26; section 4). The
  sheet was regenerated on 17 Nov's data with a new data section (`data.*`); the deck's numbers
  were checked against it again: section 4.

## 1. Numbers from the sheet

| slide | id | shown | sheet (as shown) | where |
|---|---|---|---|---|
| 2 The problem | `dil.rate` | 12% | 12% | slide, footer, notes; "about one in eight" in the notes (1 / 0.120 = 8.4) |
| 2 The problem | `dil.rows` | 148,067 | 148,067 | footer |
| 2 The problem | `dil.first` | 2023 | 31 Jan 2023 | slide ("from 2023 on"), notes |
| 2 The problem | `dil.last` | 2026 | 30 Apr 2026 | notes ("2023 to 2026") |
| 3 What we built | `app.companies` | 6,915 | 6,915 | slide, notes |
| 3 What we built | `app.forecasts` | 3,669 | 3,669 | slide, notes |
| 3 What we built | `app.date` | 16 Nov 2026 | 16 Nov 2026 | footer |
| 4 Keeping it honest | `dil.first` | 2023 | 31 Jan 2023 | slide, notes ("from 2023 on") |
| 5 Choosing the model | `dil.test_ll.base_rate` | 0.343 | 0.343 | table |
| 5 Choosing the model | `dil.test_ll.rule` | 0.301 | 0.301 | table |
| 5 Choosing the model | `dil.test_ll.logistic` | 0.249 | 0.249 | table |
| 5 Choosing the model | `dil.test_ll.lightgbm` | 0.226 | 0.226 | table |
| 6 The one-time test | `dil.rows` | 148,067 | 148,067 | slide, notes |
| 6 The one-time test | `dil.first` | 31 Jan 2023 | 31 Jan 2023 | slide; notes "January 2023" |
| 6 The one-time test | `dil.last` | 30 Apr 2026 | 30 Apr 2026 | slide; notes "April 2026" |
| 6 The one-time test | `dil.ll.base_rate` | 0.369 | 0.369 | bar, notes |
| 6 The one-time test | `dil.ll.rule` | 0.311 | 0.311 | bar, notes |
| 6 The one-time test | `dil.ll.logistic` | 0.256 | 0.256 | bar, notes |
| 6 The one-time test | `dil.ll.lightgbm` | 0.229 | 0.229 | bar, sentence, notes (twice) |
| 6 The one-time test | `dil.test_ll.lightgbm` | 0.226 | 0.226 | sentence, notes |
| 6 The one-time test | `dil.best_years` | 4 of 4; 2023, 2024, 2025, 2026 | 4 of 4 (2023, 2024, 2025, 2026) | stat, notes ("each of the four years") |
| 6 The one-time test | `dil.auc.lightgbm` | 0.91; 91% | 0.91 | stat, notes; 91% is 0.9075 as a share |
| 6 The one-time test | `dil.lift10.lightgbm` | 5.1× | 5.1× | stat ("5.1×", "5.1 times"), notes |
| 7 The five bands | `dil.band1.forecast` | 0.4% | 0.4% | chart |
| 7 The five bands | `dil.band1.real` | 0.3% | 0.3% | chart, notes |
| 7 The five bands | `dil.band2.forecast` | 1% | 1% | chart |
| 7 The five bands | `dil.band2.real` | 0.9% | 0.9% | chart |
| 7 The five bands | `dil.band3.forecast` | 3% | 3% | chart |
| 7 The five bands | `dil.band3.real` | 3% | 3% | chart |
| 7 The five bands | `dil.band4.forecast` | 7% | 7% | chart, notes |
| 7 The five bands | `dil.band4.real` | 11% | 11% | chart, notes |
| 7 The five bands | `dil.band5.forecast` | 37% | 37% | chart, text, notes |
| 7 The five bands | `dil.band5.real` | 42% | 42% | chart, text, notes (twice) |
| 8 The other two (removed 17 Nov, V2-78) | `vol.mae.lightgbm` | 0.252 | 0.252 | card, notes |
| 8 The other two (removed 17 Nov, V2-78) | `vol.mae.ridge` | 0.253 | 0.253 | card, notes |
| 8 The other two (removed 17 Nov, V2-78) | `vol.cov80.lightgbm` | 81% | 81% | card, notes |
| 8 The other two (removed 17 Nov, V2-78) | `mov.ll.lightgbm` | 0.467 | 0.467 | card |
| 8 The other two (removed 17 Nov, V2-78) | `mov.ll.ridge` | 0.452 | 0.452 | card |
| 8 The other two (removed 17 Nov, V2-78) | `mov.ridge_better_years` | 4 of 4 | 4 of 4 (2023, 2024, 2025, 2026) | card; notes "every one of the four years" |
| 9 Limits and lessons | `cu.announced` | 41% | 41% | slide, notes |
| 9 Limits and lessons | `cu.auc_none` | 0.87 | 0.87 | slide, notes |
| 9 Limits and lessons | `cu.auc_all` | 0.89 | 0.89 | slide, notes |
| 9 Limits and lessons | `audit.months_before` | 51,441 | 51,441 | slide, notes |
| 9 Limits and lessons | `audit.months_after` | 11,973 | 11,973 | slide, notes |

Sheet ids not on the slides, kept for questions: `mov.rows`, `mov.ll.base_rate`, `mov.ll.baseline`,
`mov.ll.rule`, `vol.rows`, `vol.mae.baseline`, `vol.mae.rule`, `dil.auc.base_rate`, `dil.auc.rule`,
`dil.auc.logistic`, `cu.band5_all`, `cu.band5_none`, `audit.cut_before`, `audit.cut_after`,
`audit.twice_before`, `audit.twice_after`, `audit.named`.

## 2. Other numbers and claims, with their source

| slide | shown | source and check |
|---|---|---|
| 1 | Dry run, 18 November 2026 | the researcher, 16 Nov (`spec.md`) |
| 1, 2, 3, 4 | a 10%+ rise in shares within six months | the question, fixed in `config/risk_params.yaml` (tag `prereg-risk-v5`); the sheet's Terms |
| 1 | "in the next eight minutes … then a live demo" | the notes' times: 8:15 after the cover |
| 2 | 100 M, 25 M new, 125 M, "a fifth less" | a worked example, not data: 100 / 125 = 0.8 |
| 3 | six layers, in order | `docs/architecture.md`: raw; staging (files read into tables); reference and core (clean facts with the day each became public); features; labels, models, scores (answers and forecasts); serving (the app's copy) |
| 3 | the dilution question (until 17 Nov: four questions, volatility over three months; V2-78) | the question in `config/risk_params.yaml` (tag `prereg-risk-v5`); `docs/spec.md` |
| 3 | one paid month of Tiingo | 26 Oct - 26 Nov 2026; prices of stocks that have disappeared and a second source for listed stocks (`docs/spec.md`) |
| 3 | every weekday at 10:00 | the schedule (`sentinel schedule show`; 001 T059) |
| 4 | "tagged before any model was built" | tag `prereg-risk-v5`: 29 Oct 2026, 18:20; the first model notebook: 30 Oct 2026, 11:59 (commit 35d1c8d) |
| 4 | 12 Nov 2026 | `docs/report/model_card.json` → `holdout.date` of each model: 2026-11-12 |
| 4 | the look-ahead test | `tests/unit/test_truncation.py`: deleting every record after a day leaves every feature up to that day unchanged |
| 5 | 2019-2022; an offering filed in the last 12 months; five bands | the sheet's Terms |
| 5 | "best in every test year, well beyond one standard error" | `model_card.json` → `dilution.test_years`: LightGBM's log loss the lowest in 2019 (0.208), 2020 (0.246), 2021 (0.246) and 2022 (0.203); its lead over the logistic regression 0.024 a year on average, one standard error of the four yearly differences 0.0025 (V2-50) |
| 6 | "0.5 would be a coin toss" | the sheet's Terms (AUC) |
| 6 | bar lengths | 1,400 px per unit of log loss: 517, 435, 358, 321 px (the rule's 435.6 drawn as 435) |
| 7 | bar lengths | 1,080 px per unit, at least 4 px (band 1's 0.31% drawn at 4 px, not 3) |
| 7 | blue the forecast, orange what happened | `deck.css`: `.fc` blue, `.real` orange, as the notes say |
| 7 | "each band diluted more often than the one below" | `dil.band1.real` … `dil.band5.real`: 0.31%, 0.89%, 2.96%, 10.5%, 42.3% |
| 8 (removed 17 Nov, V2-78) | volatility over the next 3 months; the 80% range | `docs/spec.md`; the sheet's Terms |
| 8 (removed 17 Nov, V2-78) | "the app serves the dilution forecast only" | decisions V2-61 (10 Nov, before the test) and V2-72 |
| 9 | the AUCs on 2019-2022 | `docs/report/dilution_catching_up.md`, section 2: the test years 2019-2022 (the 0.91 of slide 6 is the one-time test, 2023-2026) |
| 9 | "many of them … a SPAC, left out on purpose" (notes) | decision V2-67: of the 11,973 company-months, "about half now SPAC months cut on purpose" (11 Nov) |
| 9 (8 since 17 Nov) | "a daily update it reported as fixed and verified had stopped on three mornings in a row" (since 17 Nov, V2-78; until then "an audit found one model scored with information from the future": 006, evaluated with `cum_split_after`, rebuilt and approved 9 Nov, V2-55) | `AGENTS.md`, the audit of 4 Nov: the 10:00 runs of 2, 3 and 4 Nov stopped at the 5 GB memory cap while the note said "fixed & verified" (measured without the download); fixed and checked on 4-5 Nov (001 T046) |
| 10 | 5 minutes, the app's sections, port 8100 | the company page's tabs (026 User Story 8; slide changed 16 Nov from a fixed path, version 14; its first step opens by search since 17 Nov, V2-77, version 18); the app on this computer only (V2-71); it asks for the password (HTTP 401 without it) |

## 3. Wording corrected by this check

1. **Cover**: "for any US stock, built from free public data" became "for US stocks, built mostly from
   free public data". Only 3,682 of the 6,917 companies get a forecast (slide 3), and one source,
   Tiingo, is paid. The notes now give eight minutes, then the demo, instead of "ten minutes".
2. **Slide 3**: the six layers are now named as in `docs/architecture.md`; before, the staging layer
   was missing and answers and forecasts, one layer, were counted as two. Tiingo is described as in
   `docs/spec.md`, which adds a check on the listed stocks' prices.
3. **Slide 4, notes**: the look-ahead test keeps every *input* up to the day unchanged, not "that
   day's forecasts" (the test checks features).
4. **Slide 5**: "clearly best" was replaced by what the model card shows: best in every test year,
   well beyond one standard error.
5. **Slide 8, notes**: the app shows only the dilution forecast by decision V2-61 (10 Nov), made
   before the test. It is not a consequence of the test's results, as the notes had said.
6. **Slide 9**:
   - "announced *by* the forecast date": the report's definition is a filing known by that day.
   - The AUCs 0.87 and 0.89 are now labelled as the test years 2019-2022, so they are not confused
     with slide 6's 0.91 on 2023-2026.
   - "on forecasts with nothing announced" replaces "without them": the report leaves out every
     forecast with an announced sale, answers of 0 included.
   - "some prices, delisted companies' above all": Tiingo also fills gaps for listed stocks.
   - The notes add that many of the 11,973 company-months still cut are SPAC months left out on
     purpose.

Left for the researcher's review (T008): who presents which slide; the lessons slide; any text too
long for its box (sizes were checked by font and width only, not on screen).

## 4. Version 26 (18 Nov, V2-80): the product-first deck

Every number on version 26 compared with the sheet of 18 Nov (data to 17 Nov 2026, `app.date`
17 Nov 2026). Slides 5 and 8 are unchanged in their numbers; section 2 holds the sources of the
numbers that are not on the sheet (10:00, 0, 231, 21, 1,000×, the worked example).

| Slide | ids | sheet (as shown) | on the slide |
|---|---|---|---|
| 2 The problem | `data.filings`, `data.forms`, `app.date` | 13.5 million, 602, 17 Nov 2026 | 13.5 million, 602, "counts of 17 Nov 2026" |
| 3 The product | `app.companies`, `app.forecasts`, `app.date` | 6,915, 3,663, 17 Nov 2026 | 6,915, 3,663 (slide and notes), "counts of 17 Nov 2026" |
| 4 The data it gathers | `data.companies`, `data.filings`, `data.financials`, `data.financials_from`, `data.insider`, `data.insider_from`, `data.prices`, `data.priced`, `data.prices_from` | 26,706; 13.5 million; 8.2 million; 2009; 1.2 million; 2006; 26.0 million; 11,416; 2010 | 26,706; 13.5 M; 8.2 M; since 2009; 1.2 M; since 2006; 26.0 M (notes: "26 million"); 11,416; since 2010 ("M: million" in the footer) |
| 6 Part of the data predicts dilution | `dil.rate`, `dil.rows` | 12%, 148,067 | 12%, 148,067 (footer) |
| 7 The result | `dil.rows`, `dil.first`, `dil.last`, `dil.ll.*`, `dil.test_ll.lightgbm`, `dil.best_years`, `dil.auc.lightgbm`, `dil.lift10.lightgbm` | 148,067; 31 Jan 2023; 30 Apr 2026; 0.369, 0.311, 0.256, 0.229; 0.226; 4 of 4; 0.91; 5.1× | the same; 0.226 moved here from the merged slide "choosing the model" |
| 8 The bands | `dil.band1`–`dil.band5` | unchanged | unchanged |
| 9 Limits and lessons | `cu.announced`, `cu.auc_none`, `cu.auc_all`, `audit.months_before`, `audit.months_after` | 41%, 0.87, 0.89, 51,441, 11,973 | the same; the first limit reworded ("part of a yes had already happened") |

Version 28 (18 Nov, the researcher): slide 3 without the "About & data" card; no number
changed. **Version 30 (18 Nov, the researcher), 11 slides:** "Limits and lessons" taken off
(its ids `cu.announced`, `cu.auc_none`, `cu.auc_all`, `audit.months_before`,
`audit.months_after` are no longer on the deck; its content is in `docs/plan.md`, "To improve
the product"); "Keeping it honest" (slide 7, no number from the sheet) and "Choosing the
model" (slide 8: `dil.test_ll.base_rate` 0.343, `dil.test_ll.rule` 0.301,
`dil.test_ll.logistic` 0.249, `dil.test_ll.lightgbm` 0.226) back as in version 23; the result
(slide 9) and the bands (slide 10) as in version 23; slide 6 without its note on the rules.
0 differences.

**Version 31 (18 Nov, the researcher: "remove the footer notes from the presentation"):** the
source line at the foot of slides 2-10 removed; each slide keeps its page number. No number
changed. No longer on the slides: `app.date` ("counts of 17 Nov 2026", slides 2 and 3),
`dil.rows` on slide 6 (still on slide 9 and in its notes) and the key "M: million" (slide 4; its
notes say "million"). The sources of every number stay in this file (FR-003, amended). 0
differences.

## How this was checked

The table in section 1 was compared with the sheet and the slides by a short script, run on
16 Nov:
- the "sheet (as shown)" column equals the sheet's value for each id;
- every number in the "shown" column (split at ";") is found in that slide's text or notes;
- every other number found in the slides' text and notes is either a label or in section 2. The
  labels are card, band and step numbers, decision and feature numbers (V2-70, 010, 027, 019),
  number-sheet ids (`dil.lift10`, `vol.cov80`) and the times in the notes.

That is 44 rows, 39 ids, 0 differences.
