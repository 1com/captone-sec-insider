# EDGAR-SENTINEL: capstone plan (course format)

Status: Friday 23 October 2026, day 2 of 28. Hand-in: Wednesday 18 November 2026.

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
| 6 | Symbol map (98.1% of event companies mapped) and filing headers (download waits for EDGAR maintenance) | In progress |
| 7–21 | Prices to report | Not started |

## Decisions taken on 23 October

| Decision | Detail |
|---|---|
| **D45 adopted** | G7 also excludes issuers whose signal-filing header has no SIC code, subject to a 30-event check by the researcher (tasks 1.7 and 1.13). Logged in plan §12 |
| **D47 adopted** | Product v1 shows score bands with their holdout hit rate and a caveat, and "no proven skill" if H4 fails ([06](06-user-research-response.md#decision-d47)). Logged in plan §12; §8.6 updated |
| **Weekends** | Used as working days when the schedule needs them; otherwise buffer |
| **No testing with real people** | No interviews or user tests in the capstone. The product presentation rules are checked by automated tests instead |
| **MVP prototype stays as it is** | Product v1 replaces it in week 4 |

Every task is owned by the researcher (R) or the coding agent (C).

The course repository's own draft (`plan/` in `aipm-product-discovery-planning`) is not adopted. Its draft decisions D46–D48 differ from this project's decision log, where D46 is the $25k G6 minimum.
