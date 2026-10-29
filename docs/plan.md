# Plan: v2 to 17 November

Owners: R = the researcher, C = the coding agent (Claude Code). Working days Monday to Friday; the
weekends of 31 Oct – 1 Nov, 7–8 Nov and 14–15 Nov are buffer. Each step is done when its tests pass,
its named real-data checks pass and the researcher has seen its summary.

## Schedule

| # | Step | Content | Done when | Who | Dates |
|---|---|---|---|---|---|
| 0 | Fresh start | archive v1 (`v1-final`); fresh `main`; spec, architecture, lessons, decisions, plan; Tiingo for every listed company | the repository holds only v2; Tiingo downloads complete | C | Thu 29 Oct |
| 1 | Raw and staging | fetchers for every source (SEC, Yahoo, Tiingo, FRED, Cboe, FINRA, French) on the v1 behaviour; daily SEC ticker snapshots; complete staging per source, as views over raw where possible | each staging table holds every downloaded file; row counts match the manifest | C | Fri 30 Oct – Mon 2 Nov |
| 2 | Reference | `ref.company`, `ref.security` (classes, ADRs and ratios), `ref.ticker_history`, calendar, industry, `ref.coverage` | Apple, ASML, Meta, Hitachi, Ares Capital, a closed-end fund and a disappeared company each land in the right level with the right tickers | C | Tue 3 Nov |
| 3 | Core | prices (source choice, fallbacks, Yahoo–Tiingo check, glitches), corporate actions, filings, financial facts with `known_at`, shares per class, results releases, insider trades and clusters, macro, short volume | named checks: Jamie Dimon's 2016 JPM purchase, Tesla's 2022 releases, Meta's market value, TSMC's market value | C | Wed 4 – Thu 5 Nov |
| 4 | Features | features as of month-ends, release eves and each company's latest day (V2-13); month-end training panel | features for a fixture day equal those of a full rebuild | C | Fri 6 – Mon 9 Nov |
| 5 | Labels and models | development answers (windows to 2022); the three risk models under D60; report; MLflow | two runs give identical predictions; report generated | C | Mon 9 – Tue 10 Nov |
| 6 | Daily update and serving | `sentinel update`, `score.daily`, `score.outcome`, `sentinel publish` | a rerun on the same day changes nothing; the serving copy opens read-only | C | Wed 11 Nov |
| 7 | Risk holdout | the one test of the chosen models on windows from 2023 | guard log shows a single run | R triggers, C builds | Thu 12 Nov |
| 8 | Product | stock page, dilution check, risk card, insider tracker, screeners, model card, over `serving.duckdb` | endpoint tests; pages match the report | C | Thu 12 – Mon 16 Nov |
| 9 | Hand-in | product v1 (17 Nov), report (18 Nov) | | R, C | Tue 17 – Wed 18 Nov |
| 10 | Before Tiingo ends | offline rebuild check from raw | a fresh clone plus raw rebuilds the serving copy | C | by 25 Nov |

## Status on 29 October

The data layers are built ahead of schedule; work stopped there at the researcher's request, before
the models and the product.

| # | Status |
|---|---|
| 0 | done |
| 1 | staging done for every source (Form 4 row counts match the files); left: porting v1's fetch commands, and Yahoo prices for the 373 listed companies neither source has (mostly thin OTC ADRs) |
| 2 | done: Apple, Meta, Hitachi (price-only), a BDC, a closed-end fund (not covered) and Bed Bath & Beyond (Tiingo) land right; one price series per company, so share classes and ADR ratios are not modelled and a foreign filer's market value is missing |
| 3 | done; named checks pass (Jamie Dimon's purchase, Tesla's 2022 releases, Meta's and Apple's market value, TSMC); no corporate-actions table (splits and dividends are in `core.price_daily`; delisting reasons served the dropped 50% fall label) |
| 4 | done |
| 5 | development labels done (windows to 2022); the models are next |
| 6 | `sentinel publish` and `sentinel export` done; `sentinel update` and the score tables are next |

## Cut order (if a step slips)

1. Filing-triggered updates during the day (8.12 in v1's numbering).
2. Volatility at 1 and 6 months.
3. The price-only coverage level's pages (prices still kept).
4. Mapping foreign filers' IFRS financials.
5. Screener extras beyond risk band, sector, size and insider activity.

## Questions settled on 29 October

The 50% fall forecast is dropped (V2-9); the volatility range is scaled on all earlier years
(V2-10); the price-only level is in (V2-11); v1's issues are closed and v2's opened (V2-12).
