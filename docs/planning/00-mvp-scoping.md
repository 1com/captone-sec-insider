# 00 – MVP scoping

## Team context

| Item | Detail |
|---|---|
| Team | The researcher (owner: decisions, audits, emails, approvals, report) and Claude Code as coding agent (builds each feature through spec-kit) |
| Time | 4 weeks, 22 October – 18 November 2026. 18 weekdays remain from 26 October; weekend days are used when the schedule needs them |
| Core skills | Data engineering (DuckDB, point-in-time pipelines), ML (scikit-learn, LightGBM, SHAP), empirical finance (event studies, factor models), a small web product (FastAPI) |
| Budget | Free data, plus one month of Tiingo Power ($30) for delisted-stock prices (D39) |

## 1. MVP goal (the capstone deliverable)

By 18 November, deliver a **pre-registered, cost-adjusted test** of whether clusters of insider purchases predict stock returns, using every SEC insider filing from 2006 to 2026 and keeping delisted stocks. Also test whether an ML model, using only information available on the day, ranks those clusters better than simple rules. Wrap the result in **product v1**: an insider lookup for any stock, and a screener of the latest clusters whose scores a retail investor reads correctly.

## 2. Core hypotheses

- **Research (pre-registered, plan §3.3).** H1: clusters beat their industry peers over 63 trading days after costs. H4: out of sample, the selected ML model beats a three-feature logistic regression. H2a, H3 and H5 complete the five confirmatory tests.
- **Product (from the user research).** A model score is safe to show a retail investor only as a band with its track record, a caveat and a plain reason, never as a precise probability (D47; [06](06-user-research-response.md)). The capstone does not test this with users. It enforces the rule with automated tests.

Null results are results: the pipeline, the methods and the product are the deliverable either way.

## 3. Core components (Must)

From plan §4. ML is a Must and is never cut.

| # | Component | Plan steps |
|---|---|---|
| E1 | **Insider warehouse**: all 83 quarters typed, point-in-time entities and roles, clean-purchase gates with an audited funnel, preliminary events, symbol map, filing headers | 1–6 |
| E2 | **Prices, final events, delistings**: Yahoo for listed stocks, Tiingo for delisted ones, the French data library; price check G8, issuer types G7, tradability floors, cooldown; delisting returns | 7–8 |
| E3 | **Company financials and costs**: XBRL shares and five balance-sheet items; spread and trading-cost estimates | 9–10 |
| — | **Pre-registration lock**: parameters and spec tagged `prereg-v1` before any return is computed | 10a |
| E4 | **Labels and features**: 5 horizons × 4 benchmarks, gross and net; F1–F29 as of T | 11–12 |
| E5 | **Event study** on 2012–2022: H1–H3, written up before any ML result exists | 13 |
| E6 | **ML tournament**: purged walk-forward validation, six baselines, three model families, calibration, SHAP | 14–17 |
| E7 | **Sealed holdout** (2023–2026), evaluated once; production refit and latest scores | 18–19 |
| E8 | **Product v1**: stock lookup, screener and model card, with the research-driven presentation P1–P3 and P5–P8 ([06](06-user-research-response.md)) | P, 19 |
| E9 | **Robustness and delivery**: sensitivity variants, offline rebuild check, report, Tiingo deletion | 20–21 |

## 4. Later features

| Priority | Items |
|---|---|
| **Should** (plan §4; cut in this order if needed) | Daily ingestion of new Form 4 filings from EDGAR, so the screener stays current · B2, solo purchases by other insiders, for the exploratory H2b · SHAP drivers in words on the product (P4) · non-primary horizons (126 and 252 days) · sensitivity variants (Appendix E) |
| **Could** | Dimson-adjusted betas · exploratory regression on net returns · public deployment · CSV of SEC-derived event fields (P9) · OTC flag and filter (P10) · saving dated live scores for a later forward test |
| **Won't (this version)** | Macro features · fundamentals beyond F26–F29 · a matched no-buying control group · insider-selling signals · intraday data · paid data beyond the Tiingo month · alerts and digests · translations · monetisation · interviews or tests with real users · changes to the MVP prototype |

## 5. Learning goals

A proposal; edit to taste.

- **Researcher:** design and defend a pre-registered empirical study, and supervise a coding agent through specification-driven development.
- **Data engineering:** a point-in-time warehouse in which every fact carries the date it became public, proven by truncation tests.
- **ML:** leakage-free evaluation for overlapping financial events (purging, walk-forward folds, calibration, a sealed holdout), and honest communication of a weak or null result.
- **Product:** presenting a probabilistic model to non-experts without overselling it.

## Summary

The capstone deliverable is a pre-registered, cost-adjusted, survivorship-free test of insider purchase clusters on 2012–2026 data, with an ML ranking tested once on a sealed holdout. It is wrapped in a product that lets a retail investor look up any stock's insider activity and read the latest clusters' scores correctly. It answers whether the signal exists after costs and whether ML adds to it (H1–H5), and it presents the model's scores no more precisely than the evidence allows (D47). Everything else is a Should or later, cut in the pre-registered order.
