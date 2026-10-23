# 04 – Effort-informed prioritisation

## Features by value and effort

Effort is in the coding agent's days ([03](03-technical-breakdown.md)). Priorities come from plan §4, plus the user-research items from [06](06-user-research-response.md).

| Feature | Effort | Priority | Reason |
|---|---|---|---|
| E1 Insider warehouse (Steps 1–6) | 2 d left (Steps 1–5 done) | ✅ **MUST** | Everything downstream reads it; the symbol map gates the Tiingo month |
| E2 Prices, final events, delistings (7–8) | 4.5 d | ✅ **MUST** | Delisted prices are what makes the study survivorship-free; the critical path |
| E3 Company financials and costs (9–10) | 1.5 d | ✅ **MUST** | Market cap (F16, F25–F29) and costs are in every headline number |
| Pre-registration lock (10a) | 0.5 d | ✅ **MUST** | Without it, no confirmatory claim is credible |
| E4 Labels and features (11–12) | 2.5 d | ✅ **MUST** | The ML target and inputs |
| E5 Event study (13), with medians and hit rates | 1 d | ✅ **MUST** | Answers H1–H3, the research question itself |
| E6 ML tournament (14–17) | 3 d | ✅ **MUST** | ML is the capstone's required core and is never cut |
| E7 Holdout and production model (18–19) | 1 d | ✅ **MUST** | H4 and H5; the only out-of-sample evidence |
| E8 Product v1 with P1–P3 and P5–P8 | 4 d | ✅ **MUST** | Lookup and screener are deliverables; the research-driven presentation keeps the product honest |
| E9 Robustness and delivery (20–21) | 2 d | ✅ **MUST** | The offline rebuild must pass before the Tiingo data is deleted |
| Daily EDGAR ingestion | 2 d | ⚙️ **SHOULD**, cut first | Freshness for the screener (research row 7). Not needed for the research |
| B2 group and exploratory H2b | 0.5 d | ⚙️ **SHOULD**, cut second | Prices for B2 come with the same pull, so the extra cost is small |
| SHAP drivers in words (P4) | 0.5 d | ⚙️ **SHOULD**, cut third | The fact line (P3) already gives a reason; drivers add the model's view |
| Horizons of 126 and 252 days | in E4–E5 | ⚙️ **SHOULD**, cut fourth | The 63-day label is primary |
| Sensitivity variants (Appendix E) | in E9, unattended | ⚙️ **SHOULD** | Shows how fragile the results are |
| CSV of SEC-derived events (P9) | 0.25 d | 💡 **COULD** | Replication for students and analysts |
| OTC flag and filter (P10) | 0.25 d | 💡 **COULD** | Helps non-US investors; the flag already exists |
| Dimson betas, regression model, public deployment | 1–2 d | 💡 **COULD** | Plan §4 |
| Saving dated live scores for a forward test | 0.25 d | 💡 **COULD** | Evaluated only after the capstone |
| Alerts, digests, translations, monetisation, insider-selling signals | — | 🚫 **WON'T** | Out of scope for 4 weeks (plan §4; research rows 14, 16, 18) |
| Interviews or tests with real users; changes to the MVP prototype | — | 🚫 **WON'T** | Researcher's decision, 23 Oct (research row 19) |

## Capacity check

| | Agent-days |
|---|---|
| Musts | about 22 |
| + 20% buffer (course rule) | about 26 |
| Weekdays left, 26 Oct – 18 Nov | 18 |
| Plus the four buffer weekends | up to 26 |

**The Musts do not fit in weekdays alone.** Three things close the gap:
1. **The estimates are conservative.** Steps 2–5, estimated at about 5 days, were built and run in one. Code-heavy steps (E4–E6, E8) are likely to go faster. Waiting on data sources (E2) and on the researcher's checkpoints will not.
2. **Weekend days.** Using about four of the eight covers the gap. Decided on 23 October: weekends are worked when the schedule needs them.
3. **The pre-registered cut order** (plan §9.3) applies if week 2 slips by more than two days.

Should items fit only if the estimates prove conservative. Daily EDGAR ingestion is unlikely before 18 November.

## Cut order and triggers

The cut order is pre-registered (plan §9.3) and is not changed here.

| Order | Cut | Trigger |
|---|---|---|
| 1 | Daily EDGAR ingestion | Week 2 slips by more than two days |
| 2 | Comparison group B2 | Week 2 still slipping |
| 3 | The SHAP panel in the product (P4). The SHAP analysis itself stays | Week 3 slips |
| 4 | Horizons of 126 and 252 days | Week 3 still slipping |

The ML core (E6, E7) and the research-driven presentation (P1–P3, P5–P8, about 1.75 days) are never cut. The presentation is what stops the product from overstating a weak model.

## From priorities to tasks

**Outcome goal → epic → deliverables → tasks**, in [05](05-user-stories-and-tasks.md).

| Outcome goal | Epics |
|---|---|
| Research: a pre-registered, cost-adjusted answer to H1–H5 | E1–E7, E9, the lock |
| Product: lookup plus a correctly read score | E8 (needs E1 for the lookup, E7 for the scores) |
| Learning: point-in-time data and leakage-free ML | E1, E4, E6, E7 |
