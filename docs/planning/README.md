# EDGAR-SENTINEL: capstone plan (course format)

Status: Saturday 24 October 2026, day 3 of 28. Hand-in: Wednesday 18 November 2026.

This folder applies the course's six planning steps (neue fische / SPICED AI PM bootcamp, repository `1com/aipm-product-discovery-planning`, used only as a template) to this project. It adds a seventh file that responds to the synthetic user research of 23 October. **It does not change the project's scope.** Everything here is drawn from the specification, and where the user research justifies a change, the change is listed separately and marked for approval.

| File | Course step | Content |
|---|---|---|
| [00-mvp-scoping.md](00-mvp-scoping.md) | MVP scoping | What the 4-week deliverable is, the hypotheses it tests, must-haves and later items |
| [01-outcome-goals.md](01-outcome-goals.md) | Outcome goals | Research, product and learning goals, with the measures that define "done" |
| [02-roadmap.md](02-roadmap.md) | Now–Next–Future | The four weeks by milestone, then what comes after the capstone |
| [03-technical-breakdown.md](03-technical-breakdown.md) | Technical breakdown | Components, effort and risks per epic |
| [04-effort-prioritization.md](04-effort-prioritization.md) | Prioritisation | MoSCoW with effort, capacity check, cut order |
| [05-user-stories-and-tasks.md](05-user-stories-and-tasks.md) | Stories and tasks | User stories, deliverables and dated tasks of a day or less, per epic |
| [06-user-research-response.md](06-user-research-response.md) | (added) | Each concern from the synthetic research: valid or not, in scope or not, and what the plan does about it |

## How this relates to the other project documents

- **Precedence.** `.specify/memory/constitution.md` wins over [docs/initialplan.md](../initialplan.md) (the specification, v2.2), which wins over this folder. This folder schedules and explains; it never overrides.
- **"MVP".** In the course's sense, the MVP is everything due on 18 November: the research result, the pipeline and product v1. This folder calls that **the capstone deliverable**. "The MVP prototype" means feature 003, the demo dashboard built on 22 October.
- **Building.** Each epic is built as a spec-kit feature (specify → plan → tasks → implement), with run notes under `specs/<feature>/`.
- **Hypothesis names.** H1–H5 always means the study's pre-registered hypotheses, never the user research's own H1–H7.

## Where things stand

| Plan steps | What | Status |
|---|---|---|
| 0–1 | Set-up; all 83 quarterly SEC data sets downloaded (feature 001) | ✅ 22 Oct |
| — | MVP prototype (feature 003): pilot 2006–2011, survivors only, public demo | ✅ 22 Oct |
| 2–5 | Staging (37.9 M rows), entities, gates (161,059 clean purchases at the $25k minimum, D46), preliminary events (39,498) and the comparison with feature 001 (feature 002) | ✅ 23 Oct, pushed |
| 3–4 audits | Three 50-row audit sheets | Waiting for the researcher |
| 6 | Symbol map (98.1% of event companies mapped); filing headers for 27,288 of 27,290 signal filings (SGML fallback for 2012–2014) | ✅ 24 Oct |
| D45 | 30-company no-SIC sheet (`specs/002-insider-warehouse/audits/d45_no_sic.csv`) | Waiting for the researcher (due 29 Oct) |
| 7 | Yahoo prices (11.3 M rows, 3,649 companies), reference data, final events (A 4,926 · B1 2,542 · B2 7,171; 9,088 unpriced), G8 93.8%, coverage 97.5% of listed / 61.1% of all (feature 004) | ✅ 24 Oct for listed companies, merged; Tiingo prices from 29 Oct |
| 8 | Delisting classes and returns | After Tiingo (29–30 Oct) |
| 9–10 | XBRL facts (market cap for 92% of priced events; 8 of 10 within 5% of Yahoo, both misses explained) and costs (median round trip 0.73%) | ✅ 24 Oct for listed companies |
| 19 (task 8.1) | Product v1 stock lookup: search, every insider transaction with plain-English codes, holdings, events, glossary, JSON API; SEC data only (feature 005) | ✅ 24 Oct |
| 11–21 | Labels, features, models, the rest of the product, report | Not started (after `prereg-v1`) |

## Decisions taken on 24 October

| Decision | Detail |
|---|---|
| **G8 scope** | G8 checks only purchases traded from 1 January 2010, when prices start. Share-class and ADR mismatches are accepted and documented (mapping share classes would add at most 0.3 points); SC-002 is re-measured after Tiingo. Logged as D52 in plan §12, for approval with the other entries (L.2) |
| **Feature 004 merged early** | Merged into `main` before the Tiingo month; the Tiingo-month tasks continue on `main` |

## Decisions taken on 23 October

| Decision | Detail |
|---|---|
| **D45 adopted** | G7 also excludes issuers whose signal-filing header has no SIC code, subject to a 30-event check by the researcher (tasks 1.7 and 1.13). Logged in plan §12 |
| **D47 adopted** | Product v1 shows score bands with their holdout hit rate and a caveat, and "no proven skill" if H4 fails ([06](06-user-research-response.md#decision-d47)). Logged in plan §12; §8.6 updated |
| **D48: no external review** | `prereg-v1` is recorded by a GitHub Release of the tag instead of an email (constitution v3.1.0). Logged in plan §12 |
| **Weekends** | Used as working days when the schedule needs them; otherwise buffer |
| **No testing with real people** | No interviews or user tests in the capstone. The product presentation rules are checked by automated tests instead |
| **MVP prototype stays as it is** | Product v1 replaces it in week 4 |

Every task is owned by the researcher (R) or the coding agent (C).

The course repository's own draft (`plan/` in `aipm-product-discovery-planning`) is not adopted. Its draft decisions D46–D48 differ from this project's decision log, where D46 is the $25k G6 minimum.
