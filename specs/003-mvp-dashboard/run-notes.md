# Run Notes: Feature 003 (MVP prototype)

Built autonomously on 2026-10-22 while the researcher was away, as they asked. Every number below comes from the pilot sample (2006–2011) and covers survivors only. These are prototype numbers, not research results.

## Where it runs

| What | Where |
|---|---|
| Local dashboard | `uv run python -m mvp serve` → **http://127.0.0.1:8765**. Port 8000 was already taken by another app on this machine (an "EDGAR-SENTINEL … Intelligence Terminal"), which was left untouched |
| Shareable page | **https://claude.ai/artifact/EGrR4kQJK5Tuqbo8Lj5fwv**, private until shared from its Share menu |
| Rebuild | `uv run python -m mvp build --skip-prices` (about 30 s with cached prices); `uv run python -m mvp build` also refreshes prices |
| Guards | `uv run python -m mvp check`: no outcome after 2011, no MVP import in `src/sentinel`, pilot label on every return/model/score tab |

## Timings

| Step | Time |
|---|---|
| Yahoo download, 1,183 tickers (1,182 ok; `CMLS` failed) | 2 min 47 s (214 MB cached in `data/mvp/raw/yahoo/`) |
| Purchase/sale extract, 83 archives → 3,435,243 lines | 52 s (one time, cached) |
| SEC submissions for 231 recent-event companies (gate G7) | about 50 s (one time, cached) |
| Full rebuild with caches | about 25–30 s (SC-008 ✅) |

## Results shown on the dashboard

**Coverage (SC-005):**

| Group | Pilot events | Still listed | Priced | Tradable | Kept |
|---|---|---|---|---|---|
| Clusters | 5,399 | 1,959 | 1,864 | 1,582 | 29% |
| Solo CEO/CFO | 1,538 | 596 | 562 | 501 | 33% |
| Total | 6,937 | 2,555 | 2,426 | **2,083** | **30.0%** |

Coverage sits right at the 30% warning line; the dashboard states it on the Findings tab.

**Event study, 63-day abnormal return vs IWM, net of the estimated spread:**
- Clusters: **+3.5%** (95% month-block band +0.5% to +8.2%), median +0.55%, 52% positive.
- Solo CEO/CFO: **+4.1%** (band +0.1% to +9.0%), median +1.1%, 53% positive.
- 2009 (the post-crisis rebound) carries much of the average. The median cost is a 0.60% round trip.

**Model, trained on 1,621 events (2006–2010), tested on 421 events (2011):**

| Model | AUC | Log loss | Brier | Top-fifth net |
|---|---|---|---|---|
| Logistic (selected) | 0.544 | 0.698 | 0.249 | +3.3% |
| LightGBM | 0.496 | 0.794 | 0.290 | +1.8% |
| Market-only baseline | 0.560 | 0.697 | 0.248 | +5.3% |
| Base rate (no skill) | 0.500 | 0.693 | 0.250 | – |

The verdict on the page: "Not yet". In the pilot, insider details add little beyond market data. The model was not tuned against the test year.

**Screener:** 244 events from July–September 2026.
- 27 are at funds, BDCs or blank-check companies and are excluded (gate G7).
- That leaves 217 shown; 195 are scored.
- 19 fail the price check, and the rest are at companies no longer listed.

## Decisions made while the researcher was away

| # | Decision | Why |
|---|---|---|
| M1 | One static page with six tabs, pre-rendered with Jinja2, served locally by FastAPI and published unchanged as an Artifact | Gives an "active URL" that keeps working even when this machine is off |
| M2 | Company lookup covers the 6,659 companies with at least one event | "Any ticker" across about 12,000 issuers would not fit an Artifact |
| M3 | TradingView price chart in the local build only; the shared page links out | The Artifact sandbox only loads approved CDNs |
| M4 | Price check G8 added: the reported purchase price must lie within the day's as-traded range ±10% | The first build showed a "$24B" CEO purchase at Reborn Coffee: 131,387 shares filed at **$180,000** each. 163 events fail (about 6%) |
| M5 | Gate G7 added for recent events, using the current SIC from the SEC submissions API; companies with **no SIC code** are also excluded | Funds and BDCs (e.g. "AGL Private Credit Income Fund") topped the screener. EDGAR leaves almost all of them uncoded, so codes 6722/6726 alone caught only 1 of 28 |
| M6 | The company tab opens on a recent scored event at a company with a long insider history | The first default was a 2025 listing with almost no history |
| M7 | Each screener score shows a pilot percentile next to it | A 55% probability means little on its own |
| M8 | Disclaimers ("course prototype · not investment advice · independent of the SEC") on every page | Real company names and model scores on a page that may be shared |

**For the design (constitution: log what the pilot teaches before `prereg-v1`).** M4 confirms that G8 matters. M5 suggests the production G7 should also exclude issuers with no SIC code at the signal filing. This is proposed as decision **D45** in the plan; the researcher should confirm it.

## Checks

- `uv run pytest`: 98 passed (85 earlier + 13 MVP tests: return arithmetic, entry timing, split unadjusting, the $2 floor on as-traded prices, guards, ticker choice, bootstrap determinism).
- `uv run ruff check .`: clean.
- `uv run python -m mvp check`: all guards pass.
- Visual review in headless Chrome at 1440px (dark and light) and at 400px phone width (inside an iframe, because Chrome enforces a minimum window width). Fixed after review: invalid `NaN` in the page data, the hash deep links, overlapping confidence bands, legend colours, the benchmark toggle layout, score-bar fills, company-chart stacking, and the cut-off table column.
