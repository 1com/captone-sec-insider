# Feature Specification: The hand-in (presentation, live demo, repository)

**Feature Branch**: `019-hand-in`

**Created**: 2026-11-16

**Status**: Draft

**Input**: User description: "There will only be a presentation, and a demo and a github repo
required" and "15 minutes for presentation and demo together. Dry run presentation is on 18th"
(the researcher, 16 Nov 2026). This replaces the plan's "product v1 on 17 Nov, report on 18 Nov":
there is no written report. The repository is public
(https://github.com/1com/captone-sec-insider); the stock research app (026) runs on this computer
only (V2-71); the one-time test of the three models on the answers from 2023 on ran on 12 Nov
(V2-69) and its results are in the generated model report.

## Clarifications

### Session 2026-11-16

- Q: What does the course require for the hand-in (report, product, presentation, demo app)? →
  A: A presentation, a demo and the GitHub repository; no written report.
- Q: When is the presentation and how long is it? → A: 15 minutes for the presentation and the
  demo together; the dry run is on Wednesday 18 November 2026 (the final presentation's date is
  not yet known).

### Session 2026-11-17

- Q: Do the volatility and results-day models belong in the presentation? → A (the researcher,
  17 Nov): "thats not part of the project. that was for myself to enhance the project later on.
  The whole focus should be the data engineering and the dilution data science part." The slides
  present the data platform and the dilution model only (FR-002, V2-78).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Follow the talk and judge the work (Priority: P1)

A tutor or classmate, with no background in markets, listens to a 10-minute talk and comes away
knowing what question the project answers for any US stock (will the company issue many new shares
within six months?), why that matters to an investor, how the data was gathered and kept honest,
and how well the forecasts did on data they were never built on. *Dilution* means a company issues
new shares, so each existing share owns a smaller part of the company: if a company with 100
million shares sells 25 million new ones, each old share's part falls by a fifth.

**Why this priority**: the presentation is how the work is judged, and the dry run is in two days.

**Independent Test**: one timed run-through of the slides alone, read by someone who has not seen
the project, who can then state the question, the main result of the one-time test and one limit.

**Acceptance Scenarios**:

1. **Given** the slides, **When** they are presented at an even pace, **Then** they take about
   10 minutes, leaving about 5 for the demo within the 15.
2. **Given** a number on a slide, **When** it is looked up in the repository, **Then** the same
   number is found in a generated report (the model report, the catching-up report, the data
   audit) and it is an aggregate over many companies.
3. **Given** the one-time test's results, **When** the slides show them, **Then** the dilution
   model's results are shown as they came out, beside every simpler level (amended 17 Nov, V2-78:
   the volatility and results-day models are the researcher's later extensions, not presented).
4. **Given** a market or statistics term (dilution, log loss, AUC, band, look-ahead, the sealed
   test), **When** it first appears, **Then** it is explained in plain words on the slide or in
   the speaker notes.

---

### User Story 2 - See the app answer for real companies (Priority: P1)

In about 5 minutes, the audience watches the presenter use the stock research app live: the
companies with the highest dilution chance today, one of them opened to show its chance, band,
the band's track record and the reasons; a large company's insider sales and its filings in plain
English; a company the forecast leaves out, told which rule; a price history kept whole across a
ticker change.

**Why this priority**: the demo is a required part and shows that the forecasts are a working
product, not only numbers in a report.

**Independent Test**: one timed run of the written demo path on the live app, each step showing
the feature it names.

**Acceptance Scenarios**:

1. **Given** the written demo path, **When** it is followed on the live app, **Then** it takes
   about 5 minutes and each step shows the feature it names.
2. **Given** the app's model section, **When** it is opened in the demo, **Then** it shows the
   one-time test's results (2023 on) beside the test years' (2019-2022), as the generated model
   card gives them.
3. **Given** a demo company whose situation changed since the rehearsal (it left the question,
   stopped trading), **When** the path is checked the day before and the morning of the
   presentation, **Then** the spare company for that step is used instead.
4. **Given** the app or the computer fails during the presentation, **When** the presenter
   switches to the backup, **Then** each step can still be shown from screenshots kept on this
   computer.

---

### User Story 3 - Open the repository as a grader (Priority: P2)

A grader opens the public repository, reads its front page and within a few minutes knows what the
project answers, how well it did on the one-time test, what the app shows and how to install and
run it; they can find the rules, the decisions and the generated reports, and a fresh copy installs
and passes its tests.

**Why this priority**: required for the hand-in, but needed by the final presentation rather than
by the dry run; the repository already holds all the work, so this story is about making it
readable.

**Independent Test**: a fresh copy of the repository, installed by the front page's instructions
alone, passes its tests and checks; a newcomer reading only the first screen of the front page
can name the question and the dilution model's one-time test result.

**Acceptance Scenarios**:

1. **Given** the front page, **When** a newcomer reads its first screen, **Then** it states what
   the project answers, that the app serves the dilution forecast only, and the dilution model's
   one-time test result with its comparison levels.
2. **Given** a fresh copy, **When** it is installed by the front page's instructions, **Then** the
   tests and checks pass without the private data.
3. **Given** the whole repository, **When** it is scanned, **Then** it holds no Tiingo-derived
   value, no secret, no database file and no notebook output.

---

### Edge Cases

- The daily update runs on weekdays from 10:00 for about 50 minutes; a presentation at that time
  still finds the app serving (the serving copy is replaced only once complete), but the
  rehearsal notes the time and the presenter checks the app is up before starting.
- The data change every day, so the numbers seen in rehearsal differ from those on the day: the
  demo path says what to point at, never an exact chance.
- A demo company leaves the question or stops trading before the presentation: each step has a
  spare company, and the path is checked the day before and the morning of the presentation.
- No internet in the room: the app runs on this computer with its chart library stored locally;
  the slides can be shown from a file.
- A question about a number not on the slides: a one-page sheet of the key numbers and terms, each
  with its source, is at hand.
- The researcher has not yet approved the new app (026): the old app (011-017) stays, and the
  front page says it is replaced and not maintained.

## Requirements *(mandatory)*

### Functional Requirements

**Slides (User Story 1)**

- **FR-001**: The slides MUST be 8-10 for about 10 minutes, so that slides and demo fit in 15
  minutes with a minute spare.
- **FR-002**: The slides MUST cover, in this order: the problem with an example; what was built
  (the data platform from free public data plus one paid month of prices, updated every weekday;
  the dilution question; the app); how the data stays right (the daily update, identical
  rebuilds, the named cases, problems searched for); the rules that keep the forecasts honest
  (no look-ahead; definitions fixed and tagged before any model; the test on 2023 on sealed and
  run once); how the dilution model was chosen (levels from base rates up, test years 2019-2022,
  the simplest level within one standard error); its one-time test results; the limits; the
  lessons; the demo. The focus is the data engineering and the dilution model: the volatility and
  results-day models are not presented (amended 17 Nov, V2-78; was "the four questions" and "the
  three questions"; the slide on how the data stays right added the same day).
- **FR-003**: Every number on the slides MUST come from a generated report in the repository or a
  count the platform computes, be an aggregate over many companies, and have its source named in
  the speaker notes; no price or other value derived from the private price source may appear.
- **FR-004**: Each slide MUST have speaker notes in plain words with its time; every market or
  statistics term MUST be explained the first time it appears.
- **FR-005**: A one-page sheet of the key numbers and terms, each with its source, MUST be prepared
  for questions.
- **FR-006**: The slides MUST be showable without internet and exportable to a common file format
  for handing in.

**Demo (User Story 2)**

- **FR-007**: A written demo path MUST list 5-6 steps, each with the company, what to open, what to
  point at and what to say, a spare company and the step's time, about 5 minutes in all.
- **FR-008**: Each demo company MUST be checked on the live app the day before and the morning of
  the presentation.
- **FR-009**: The app's model section MUST show the one-time test's results (2023 on) for the
  dilution model beside the test years' results, read from the generated model card, never typed
  in.
- **FR-010**: A backup of each demo step (screenshots) MUST be kept on this computer only, never in
  the repository or the slides, since the app's price charts use the private price source.
- **FR-011**: The demo MUST need nothing beyond this computer (the app stays local, V2-71).

**Repository (User Story 3)**

- **FR-012**: The front page MUST open, for a newcomer, with what the project answers, the one-time
  test's results as the model report gives them, the app and how to run it, installation and the
  main commands, a map of the folders, the rules and the limits; the notes for coding agents and
  the working history MUST come after these or live in AGENTS.md.
- **FR-013**: The front page MUST say that the app serves the dilution forecast only (V2-61,
  V2-72) and that the volatility and results-day models are evaluated in the model report but not
  served.
- **FR-014**: A fresh copy MUST install with the locked dependencies and pass the unit tests and
  the lint and format checks without the private data.
- **FR-015**: The old app (011-017) MUST be removed once the researcher approves the new one
  (026 T021); until then the front page MUST say it is replaced.
- **FR-016**: The repository MUST hold no Tiingo-derived value, secret, database file or notebook
  output, checked before the merge.
- **FR-017**: `docs/plan.md`, AGENTS.md and the README MUST describe the hand-in as it now is
  (presentation, demo, repository; no written report).

**Limits**

- **FR-018**: No model may change (none after the one-time test), no model notebook may be re-run,
  no new data feature may be built, and the app may not be published or shared (V2-71).

### Key Entities

- **Slides**: 8-10 slides with speaker notes and times; each number tied to its source.
- **Number sheet**: the key numbers and terms on one page, each with its source.
- **Demo path**: the steps, companies, spares, times and what to say.
- **Demo backup**: screenshots of each step, kept on this computer only.
- **Front page**: the README's first part, written for a newcomer.
- **Sources**: the generated model report and model card, the catching-up report, the data audit,
  the decision log.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A timed rehearsal of slides and demo together takes 14 minutes or less.
- **SC-002**: Every number on the slides and the number sheet matches its source exactly (a list of
  slide, number and source, checked one by one).
- **SC-003**: On the morning of the dry run every demo step succeeds on the live app and shows the
  feature it names.
- **SC-004**: A fresh copy installs by the front page's instructions and passes all unit tests and
  checks.
- **SC-005**: The front page's first screen (about 40 lines) names the question, says the app
  serves the dilution forecast only and gives the dilution model's one-time test result against
  its simpler levels.
- **SC-006**: A scan finds no Tiingo-derived value, secret, database file or notebook output in the
  repository or the slides.

## Assumptions

- The audience is tutors and classmates with mixed knowledge of markets; the talk is in English.
- The researcher presents (with the teammate if they choose); the names on the title slide are
  theirs to give.
- The presentation is given from this computer, in the room or by screen sharing, so the app can
  be shown live without being published (V2-71).
- The dry run's feedback may change the slides before the final presentation, whose date is not
  yet known.
- The generated model report stays in the repository as the evidence behind the slides; it is not
  a hand-in document.
- The slides are made in a form that can be shown in a browser and exported to PDF or PowerPoint.
