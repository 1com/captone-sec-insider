# Decision log

Every significant choice, what else was considered, and why. v2 decisions are numbered V2-n. The
v1 log (D1–D64) is in `docs/initialplan.md` §12 at tag `v1-final`; the v1 decisions that still
apply are summarised at the end.

## v2 decisions

| # | Decision | Alternatives | Reasoning |
|---|---|---|---|
| V2-1 | **Rebuild the project from scratch as a market research platform** for any US-traded stock (researcher's decision, 29 Oct 2026): fundamentals, dilution risk, the expected results-day move, expected volatility and an insider tracker, updated daily | Keep extending v1 | v1's universe, tables and staging were shaped by the insider study, the root of most of its problems ([lessons-from-v1.md](lessons-from-v1.md)); the four questions are independent (D63) |
| V2-2 | **Fresh `main`** from one new commit; v1's history kept only behind the tags `v1-final`, `prereg-v1`, `prereg-risk-v1`–`v5` and the `prereg-v1` GitHub Release | Wipe all history; build v2 on a branch | A clean start without destroying the timestamped proof that the registrations came before any result |
| V2-3 | **Keep `data/raw/`** and its manifest as the source layer; delete every derived database and export and rebuild them from raw | Re-download everything | Raw files are unchanged downloads; Tiingo cannot be downloaded after 26 November |
| V2-4 | **The insider study's hypothesis tests are dropped**: insider data is a tracker only; no return claims; the insider holdout is not run | Re-implement the study with its registration unchanged | The researcher's choice. v1 found no signal on development data (H1–H3 null, no model above the base rate); the platform's value is in risk and facts |
| V2-5 | **Deadlines kept**: product v1 on 17 November, report on 18 November; work in priority order, cut in a stated order ([plan.md](plan.md)) | Move the deadline | The capstone dates are fixed |
| V2-6 | **Six-layer design** ([architecture.md](architecture.md)): raw, complete per-source staging, reference and core with `known_at`, daily features, labels, models and scores, a read-only serving snapshot; one build database | v1's warehouse and panel databases | Each v1 problem traced to a missing layer: no security master, staging by project, batch-only, no serving copy |
| V2-7 | **Tiingo prices for every listed company**, fetched on 29 October while the plan is active, as a complete second source (cross-check, gap-fill) | Fetch only the ~200 gaps | A complete second source is only obtainable before 26 November; about one hour of downloads |
| V2-8 | **`config/risk_params.yaml` v5 is carried over unchanged**, so the risk registration (`prereg-risk-v5`) and its sealed holdout still hold | Rewrite the risk definitions | The definitions were checked on real data in v1; changing them now would be after seeing development results |
| V2-9 | **The 50% fall forecast is dropped** (researcher, 29 Oct); its label definition stays in `risk_params.yaml` v5, unused | Keep it as a rank against other stocks | Its ranking worked but its level could not be forecast (it follows whether a crash comes); v2 keeps three forecasts |
| V2-10 | **The volatility range's multiplier is set on all earlier years' calibration data**, not the last six months (researcher, 29 Oct; decided before the risk holdout test, which tests it) | v1's six-month scaling | v1's 80% range covered 74–76% of moves after 2019 because six months is one market mood; the exploratory pooled check gave 78–84% |
| V2-11 | **A price-only coverage level** (researcher, 29 Oct): stocks traded in the US that file nothing periodic with the SEC (about 960, e.g. Hitachi, Deutsche Telekom) get prices and the volatility forecast | Cover SEC filers only | Volatility needs only prices; a tool for any stock should not drop large foreign companies |
| V2-12 | **v1's GitHub issues are closed** with a pointer to `v1-final`; one issue per v2 plan step is opened (researcher, 29 Oct) | Keep tracking v1's issues | The board should show v2's work |

## v1 decisions that still apply

| v1 | In short | Where in v2 |
|---|---|---|
| D5–D7 (adapted) | tradability floors | eligibility for training: close ≥ $1, $10,000 a day, 63 days of prices (risk_params v5) |
| D8, D9 | Form 4 cleaning gates; clusters of 2+ insiders within 14 days with an officer or director | insider tracker (`core.insider_trade`, `core.insider_cluster`) |
| D39 | one paid month of Tiingo Power (26 Oct – 26 Nov 2026); Tiingo data private | price sources, spec §5–6 |
| D42 | labelled window starts on 1 January 2012 | development data 2012–2022 |
| D59 | four risk targets on a company-month panel, definitions in `risk_params.yaml` | three kept (volatility, results-day move, dilution); the 50% fall dropped (V2-9) |
| D60 | evaluation fixed before building: three levels, one-standard-error rule, calibration, bands, family checks, one holdout test | layer 5 |
| D61 | results-day window from the release (report date) to the close after filing | `core.results_release`, labels |
| D62 | dilution first with its own probability; the move as chances, never one number; volatility as band, level, 80% range | the product |
| D63 | four independent questions; universe not limited by Form 4; the five data fixes | the security master, coverage levels |
| D64 | daily update; refit quarterly with a comparison; live hit rates | `sentinel update`, `score.outcome` |
