# 01 – Outcome goals

## Outcome goals

> **Research.** By 18 November 2026, the course reviewers will receive a pre-registered answer to H1–H5. Delisted stocks are included (price coverage of at least 90%), every headline number is net of trading costs, and the holdout is evaluated exactly once. The result is a report in which every number traces to a tested, rebuildable pipeline.

> **Product.** By 18 November 2026, a retail investor using product v1 will be able to see every insider trade for any stock, and to see the latest clusters' scores as bands with their holdout hit rate, a caveat and a plain reason, never as a precise probability. Every presentation rule (P1–P3, P5–P8) is covered by an automated test.

> **Learning.** In the same time, the team will learn to build a point-in-time data pipeline and a leakage-free ML evaluation end to end, and to report a weak or null result as carefully as a strong one.

## Definition of done

| Area | Measure | Target | Source | By |
|---|---|---|---|---|
| Data | Staged rows equal the SEC files | 0 mismatches | Run notes | ✅ 23 Oct |
| Data | Point-in-time: rebuilding up to T changes nothing dated ≤ T | Truncation tests pass, synthetic and on 20 real (issuer, T) pairs | Tests | 27 Oct |
| Data | Hand audits of entities, excluded and kept purchases | At least 90% agreement per sheet | `sentinel audit summary` | 27 Oct |
| Data | Events mapped to a price symbol | At least 95% (SC-006) | Run notes | 27 Oct |
| Data | Signal filings with a parsed header | At least 99% (SC-007) | Run notes | 27 Oct |
| Prices | A and B1 events with prices, by year and delisting status | At least 90% | Coverage report | 30 Oct |
| Prices | Clean purchases whose price lies inside the day's range (G8) | At least 95% | Run notes | 30 Oct |
| Prices | Hand-checked golden set of events against EDGAR | 30 of 30, or every difference explained | Audit | 2 Nov |
| Rigour | `prereg-v1` tagged and pushed before any return is computed | Tag date < first label | Git | 4 Nov |
| Rigour | Event-study results written before any ML result exists | Commit order | Git | 9 Nov |
| Rigour | Holdout evaluated once | Guard log shows a single run | Guard log | 12 Nov |
| Research | H1–H5 answered with their pre-registered statistics; medians and hit rates beside the means | All five reported, nulls included | Report | 18 Nov |
| Product | Lookup, screener and model card working | Endpoint tests pass | Tests, demo | 16 Nov |
| Product | Presentation rules P1–P3, P5–P8 (D47) | One passing test per rule: no raw probability in list views, a caveat on every scored row, a fact line on every event, the H4 rule | Tests | 16 Nov |
| Delivery | Clean clone plus raw snapshot rebuilds the key tables offline | Pass | Step 21 check | 17 Nov |
| Delivery | Tiingo data deleted when the paid month ends | Deletion logged in §12 | Decision log | about 28 Nov |

## Checklist

- **Time-bound:** every goal is due 18 November, with the dated milestones above.
- **User-focused:** the reviewers get a trustworthy answer; the retail investor gets a lookup and a score shown no more precisely than the evidence allows.
- **Measurable:** every row has a numeric or pass/fail target.
- **Teachable:** the learning goal covers point-in-time data, leakage-free ML and honest reporting.
