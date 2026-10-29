# Lessons from v1

v1 (21–29 October 2026, tag `v1-final`) built a pre-registered study of insider purchase clusters,
then grew a risk panel and a product around it. This page lists what went wrong, what it cost, and
the rule v2 follows so it does not happen again. Section numbers in v1 documents refer to
`docs/initialplan.md` at tag `v1-final`.

## Universe and companies

| What happened in v1 | Effect | v2 rule |
|---|---|---|
| The risk panel's companies were every Form 4 issuer (D59), inherited from the insider study | 450 of 6,065 listed companies missing (ASML, Shell, Novo Nordisk, SAP, TSMC, Shopify), mostly foreign filers exempt from Form 4 | The universe is the security master, built from what trades (spec §4, architecture layer 3) |
| Tiingo's name search covered only SEC entity type "operating" | 732 disappeared foreign filers (typed "other": 58.com, Pengrowth, Secoo) never searched | Search every registrant that may have traded; check entity types on real examples first |
| Only periodic filers were candidates | 964 companies in today's SEC list not covered: foreign stocks traded OTC that file nothing periodic (Hitachi, Deutsche Telekom, Infineon) | A price-only coverage level |
| Companies and securities were one thing | TSMC worth $10.8 trillion (ordinary shares × ADR price); Meta, Palantir, Coinbase with no market value (share counts per class); 23% of stocks without a market value | `ref.security` with share class and ADR ratio; shares per class; market value per security |
| Funds were found by SIC code only | closed-end funds with no SIC (a BlackRock fund topped the dilution list); then N-2 counted as a fund report excluded 69 business development companies | A fund files N-CSR, NPORT or N-CEN; BDCs file 10-Ks and are companies |
| The Form 4 universe was carried into unrelated steps | short-sale volume reached companies only through Form 4 tickers, so added companies had none | No step may assume a company has insider filings |

## Prices

| What happened in v1 | Effect | v2 rule |
|---|---|---|
| Staging was organised by project (study vs panel) and the panel's staging was dropped after use | no table held "everything from Yahoo" or "everything from Tiingo" | One complete staging schema per source, kept |
| The panel lacked the study's fallbacks | 79 listed companies with no price (Yahoo had none); late-starting histories not filled | `core.price_choice`: Yahoo first, Tiingo where Yahoo is missing or starts late |
| Tiingo was fetched only for gaps | no second source to check Yahoo against | Tiingo fetched for every listed company before the plan ended (29 Oct) |
| One snapshot of the SEC ticker list | no history of which company used which ticker when, beyond Form 4 symbols | Save the list every day |

## Filings and financials

| What happened in v1 | Effect | v2 rule |
|---|---|---|
| The results-day window started at the 8-K's filing date | 7.1% of results 8-Ks are filed 2+ days after the release, so their moves were missed (D61) | Window from the release (report date) to the close after filing |
| Every item 2.02 8-K counted as a results release; then "the last single 8-K before the report" | delivery figures and preliminary results counted as releases; releases dated by a later supplement; 4,446 releases filed just after the 10-Q dropped | The announcement rule of risk_params v5 (`core.results_release`) |
| Every 424B prospectus counted as a share offering | Nvidia's and Amazon's bond sales showed as offerings | A 424B5 with a pricing term sheet (FWP) in the five days before it is a bond sale; Canadian banks' note prospectuses remain a known gap |
| Missing filings were counted as zero | a foreign filer read as "no insider activity" | Missing, not zero, where a filing does not apply |
| Foreign filers' financials (IFRS) were never mapped | no fundamentals for foreign filers | Map the main IFRS items (Could) |

## Models

| What happened in v1 | Effect | v2 rule |
|---|---|---|
| Rows were read without an order | LightGBM's sampling saw a different row order each run (338 vs 610 trees for the same fold) | Sort before modelling; reproducibility test: two runs, identical predictions |
| Feature-family checks used one fit | opposite verdicts between two runs (z +3.7 and −6.1) | Average five seeds; a verdict needs every seed to agree |
| The volatility range was scaled on the last six months | 74–76% of moves inside an "80%" range after 2019 | Scale on all earlier years (V2-10; exploratory check: 78–84%) |
| The 50% fall forecast was shown as a probability | its level follows whether a crash comes (11% predicted vs 35% actual in 2019) | Dropped (V2-9) |
| The results-day move was shown as one number | Meta's 27.5% move looked like a miss of an 8% forecast | Show chances of 10%+ and 20%+ moves and the typical range (D62) |

## The insider study

v1 tested whether clusters of insider purchases predict returns, pre-registered (`prereg-v1`). On
2012–2022, cluster stocks did worse than their industries (mean 63-day net return −1.6%, t −2.9);
clusters did no better than solo CEO or CFO purchases; no model beat the base rate (the selected
elastic net used no features in two of four years; development preview of H4 p = 0.22). The same
held in calm, normal and stressed markets. v2 keeps insider data as a tracker and makes no return
claims (V2-4).

## Process

| What happened in v1 | Effect | v2 rule |
|---|---|---|
| The spec stayed insider-first while the product grew | the universe and tables kept the study's shape (the root of most problems above) | v2's spec starts from the platform |
| Tests used synthetic data only | the ADR, share-class, fund and release problems passed every test | Each layer has named real-data checks |
| Data rules were registered before being checked on real data | four amendments (v2–v5) to the risk registration | Check every rule on real cases before registering |
| Everything was a one-off batch | no daily updates; a browsing session locked the database the build needed | `sentinel update` and a read-only serving copy |
| Two databases (warehouse and panel) | confusion about where data lives | One build database plus the serving copy |

## What worked and is kept

- Raw files kept unchanged, with a manifest line each.
- Financial values as first filed; macro values from their release day.
- The Form 4 cleaning gates and the merging of insider identities.
- Ticker matching by dates and Tiingo's name check.
- One-day price glitch detection.
- The D60 evaluation: three levels, the one-standard-error rule, calibration, bands, purged
  walk-forward folds.
- Reports generated by commands, never edited by hand; the decision log.
