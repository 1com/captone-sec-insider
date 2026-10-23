# 06 – Response to the synthetic user research

**Source:** *EDGAR-SENTINEL — Synthetic User Research*, 23 October 2026 (PDF in `C:\Users\Administrator\Downloads\`). Five AI personas answered three interview blocks each while looking at the MVP prototype's build of 22 October: P1 swing trader, P2 retired value investor, P3 small-fund analyst, P4 quant student and P5 European part-time investor.

**How much weight it carries.** The answers are AI-generated guesses, and the document flags its own biases: personas read every banner, recall exact numbers, echo the site's own method page and give tidy answers about payment. The plan therefore adopts only changes that are **cheap, in scope, and harmless even if a finding is wrong**. Anything that would need real users, live data or new infrastructure is moved to NEXT.

## Verdict on each concern

✅ adopted · ☑️ already in the plan · ⏭️ later (NEXT/FUTURE) · ✗ not adopted

| # | Concern (raised by) | Valid? | Response | Where |
|---|---|---|---|---|
| 1 | A precise "97%" from a near-chance model (AUC 0.54) is misread as a win chance, or destroys trust (P1, P2, P3, P5) | Yes, the top risk | ✅ Show a **band** (top fifth / middle / bottom fifth) with its holdout hit rate, and a caveat beside it; no raw probability in lists (D47) | E8 |
| 2 | Score confused with the percentile printed next to it (P4) | Yes | ✅ One number per event, the band, under one plain name | E8 |
| 3 | Caveats reassure experts but scare beginners (all 5) | Yes | ✅ Layer them: one plain line beside each score, details on the model card | E8 |
| 4 | "Why this score?": users want reasons in words, not AUC (P2, P5) | Yes | ✅ A fact line on every event (who bought, how much, stake increase, distance from the 52-week high), plus the top three drivers in words on the event page | E8 |
| 5 | Unknown, tiny, illiquid companies feel risky (P1, P2, P3, P5) | Yes | ✅ Show market-cap band, daily dollar volume and industry on every event; liquidity filter presets. These come from features F16, F17 and F24 at no extra data cost | E8 |
| 6 | Jargon: Form 4, IWM, log loss, "after costs", G8 (P2, P4, P5) | Yes | ✅ Plain labels and a glossary: what a Form 4 is, why insider buying is legal, which costs are deducted (spread and price impact on a $10,000 position; not broker fees, taxes or exchange rates), why 14 days, what the gates do | E8 |
| 7 | Events are weeks old because the SEC data sets are quarterly (P1; severe for traders) | Yes | ✅ Show the data-as-of date, days since filing and sessions left in the 63-day window. ☑️ Daily EDGAR ingestion is already a *Should* (first in the cut order) | E8; Should |
| 8 | Proof beyond a survivors-only 2006–2011 pilot (P1, P3) | Yes | ☑️ This is the core study: delisted prices (Tiingo), the 2012–2022 development period and the sealed 2023–2026 holdout | E2, E7 |
| 9 | Insider inputs added nothing over the market-only model in the pilot (P3) | Yes | ☑️ Tested directly: the market-only baseline and H4 | E6, E7 |
| 10 | A +3.5% mean against a +0.6% median: a few winners do the work, mostly in 2009 (P3) | Yes | ✅ The event study also reports the median and the share of events with a positive net return beside every mean, and results by year. This is descriptive and changes no hypothesis | E5 |
| 11 | Long-term investors value the company lookup most (P2) | Yes | ☑️ The lookup is a *Must*. It is built early (task 8.1), because it needs only the insider tables | E8 |
| 12 | Want code and an event file to replicate (P3, P4) | Yes | ☑️ Code is public on GitHub since 23 October. ⏭️ A CSV of SEC-derived event fields, with no prices or scores (licences, plan §8.6), is a *Could* | E8 (Could) |
| 13 | Forward-track the live 2026 scores (P1, P3) | Yes, but slow | ⏭️ Windows take 63 sessions, longer than the capstone. Saving the scored list with its date is a *Could*; evaluating it comes after 18 November | NEXT |
| 14 | Alerts within the hour, or a monthly digest (P1, P2, P5) | Plausible | ⏭️ Needs live filings and email infrastructure | NEXT |
| 15 | Tickers unavailable at EU brokers (P5) | Unknown | ⏭️ Show the exchange, with an OTC flag and a "hide OTC" filter (*Could*; the symbol map has the flag). Broker coverage is out of scope | E8 (Could) |
| 16 | Simple English, ideally German (P5) | Partly | ✅ Plain English (row 6). ✗ No translation | — |
| 17 | The $100k daily-volume floor is far too small for a fund (P3) | Not for this audience | ✗ The research floor is pre-registered and sized for a $10,000 retail position (D7). The product's liquidity filter and the $25k/$50k sensitivity variants cover larger positions | — |
| 18 | Low willingness to pay (P2, P3, P4) | Suspect (bias flag 4) | ✗ No monetisation in scope | — |
| 19 | Validate with 8 paid interviews (research plan) | Sensible for a launch | ✗ No testing with real people in the capstone (researcher's decision, 23 Oct). The presentation rules P1–P8 are checked by automated tests | — |

## What product v1 adopts

These refine plan §8.6 without changing the research. Effort is on top of building product v1 itself.

| ID | Requirement | Priority | Effort |
|---|---|---|---|
| P1 | Score shown as a band (top fifth / middle / bottom fifth of the model's calibration-slice predictions) with the band's holdout hit rate and count. The calibrated probability appears only on the event page and the model card | Must | S, 0.5 d |
| P2 | A one-line caveat beside every score, visible without scrolling or hovering; full detail on the model card | Must | with P1 |
| P3 | A fact line on every event, e.g. "3 insiders incl. the CEO · $1.2M · stake +18% · 28% below 52-week high" | Must | S, 0.25 d |
| P4 | The top three drivers in words on the event page, from SHAP | Should (cut item 3) | S, 0.5 d |
| P5 | Market-cap band, daily dollar volume and industry on every row; liquidity filter presets | Must | S, 0.25 d |
| P6 | Freshness: data-as-of date, filing date, days since filing, sessions left in the window; open windows shown by default | Must | S, 0.25 d |
| P7 | Plain-English glossary and labels (row 6) | Must | S, 0.5 d |
| P8 | If H4 is not confirmed, every score is labelled "no proven skill" and the screener sorts by filing date by default (fixed in advance by D47) | Must | with P1 |
| P9 | CSV download of SEC-derived event fields (no prices, no scores) | Could | S, 0.25 d |
| P10 | Exchange with an OTC flag, and a "hide OTC" filter | Could | S, 0.25 d |

**MVP prototype.** It keeps its current display (researcher's decision, 23 Oct). Product v1 replaces it in week 4.

## Decision D47

Adopted on 23 October and logged in plan §12, with §8.6 updated to match:

| # | Decision | Alternatives considered | Reasoning |
|---|---|---|---|
| D47 | Product v1 shows each cluster's score as a band (top fifth, middle three fifths, bottom fifth of the model's calibration-slice predictions; the top fifth is H5's model portfolio), with the band's holdout hit rate and count and a one-line caveat beside it. The calibrated probability appears only on the event page and the model card. If H4 is not confirmed, every score is labelled "no proven skill" and the screener sorts by filing date by default | Show the calibrated probability in lists (v2.2 §8.6) | Synthetic user research on the MVP (23 Oct 2026): a precise "97%" from a near-chance model was misread as a chance of profit, or undermined trust, in 4 of 5 personas. Bands carry what the evidence supports, and the rule is fixed before the holdout so the display cannot be chosen after seeing the result. The research design is unchanged |

## Measures taken from the research

| Measure | Target | Used where |
|---|---|---|
| Presentation rules P1–P3, P5–P8 | Each covered by an automated test: no raw probability in list views, a caveat on every scored row, a fact line on every event, the H4 rule | Product outcome goal ([01](01-outcome-goals.md)) |
| Calibration: gap between predicted and observed hit rate per band, on the holdout | Reported (target ≤ 3 points) | Model card |

The research's user measures (score comprehension, 7-day return rate, retention, alert sign-ups) need real users, which the capstone does not include.
