# EDGAR-SENTINEL

**Do clusters of insider purchases predict stock returns — and can machine learning tell the good ones from the bad?**

Research and engineering specification · Version 2.2 · 22 October 2026
v2.2: one month of Tiingo Power replaces the free-tier price budget, the labelled window now starts on 1 January 2012, and five simple company-financial features are added (decisions D39–D43)
Status: draft. The pre-registration is locked before any return is computed (§3.3)
Capstone duration: 4 weeks (22 October – 18 November 2026)

---

## How to read this document

This document is written to be read without its author in the room. It moves from **theory** (why the idea might work, §2) to the **concept** (exactly what is tested, §3), then to the **project** (scope, data, definitions and methods, §4–§7), and finally to **how it is built and in what order** (§8–§9). Risks, limitations and a log of every design decision with its reasoning follow (§10–§12).

The appendices:
- **Appendix A** holds evidence from a pilot run on real SEC data.
- **Appendix B** is a glossary.
- **Appendix C** lists the references.
- **Appendix D** summarises what changed from the first draft.
- **Appendix E** is the parameter register: every number used in the design, with its basis, and either a sensitivity check or the label "convention".

## Contents

1. Summary
2. Theory and evidence
3. The concept: research questions and hypotheses
4. Scope
5. Data sources
6. From filings to events: definitions
7. Methods
8. System architecture and tech stack
9. Step-by-step plan
10. Risks and mitigations
11. Known limitations
12. Decision log
- Appendix A — Pilot evidence from real SEC data
- Appendix B — Glossary
- Appendix C — References
- Appendix D — Changes from the first draft
- Appendix E — Parameter register

---

## 1. Summary

**The question.** Company insiders — officers, directors and large shareholders — must publicly report trades in their own company's stock within two business days. When two or more insiders buy on the open market within a short window (an **insider purchase cluster**), does the stock go on to beat comparable stocks *after realistic trading costs*? And can a machine-learning (ML) model, using only information available on the day, rank clusters by how likely they are to work?

**Why it is worth asking.** Five decades of research find that insider purchases carry information about future returns (Jaffe, 1974; Seyhun, 1986; Lakonishok & Lee, 2001; Cohen, Malloy & Pomorski, 2012). The same literature warns that much of the apparent profit disappears once company size, value effects and trading costs are accounted for (Rozeff & Zaman, 1988), and that published return patterns weaken after publication (McLean & Pontiff, 2016). This project re-tests the idea with the controls those critiques demand, then asks whether ML adds anything on top.

**Data (all free).**
- Every Form 4 insider filing from 2006 Q1 to 2026 Q3: 83 quarterly SEC data sets.
- SEC company data and filing headers.
- Daily prices: Yahoo Finance for listed stocks, Tiingo for delisted stocks.
- Factor and industry returns from the Kenneth French Data Library.

Returns are studied for events from **2012 onward**: the earliest year in which every data source is complete without workarounds. XBRL share counts, needed for market capitalisation, cover all companies only from mid-2011 (§5.2, D42). Insider filings from 2006 onward are still used to build each insider's trading history.

**Method, in two stages.**

1. **Event study.** Measure what happened after each cluster. The comparison groups are a CEO or CFO buying alone and — time permitting — another insider buying alone. Returns are measured over horizons from one week to one year and against several benchmarks, net of estimated trading costs.
2. **Machine learning.** Three classifiers (elastic-net logistic regression, random forest, LightGBM) are trained with purged walk-forward validation. Each predicts whether a cluster will beat its industry peers over the next 63 trading days by more than its own trading cost. They are compared with simple baselines, including a model that sees only market data, and the chosen model is evaluated exactly once on a locked holdout (2023 onward).

**Deliverables.**
1. A research report answering five pre-registered hypotheses.
2. A reproducible data and ML pipeline.
3. Product v1: a web screener of the latest clusters with calibrated scores and explanations, and a lookup of all insider activity for any stock.

**What makes the results credible.**
- **Point-in-time data throughout.** Nothing is used before the market could have known it, including who counted as an insider entity and which industry a company was in at the time.
- **Entry at the next day's open** after the filing.
- **Delisted stocks are kept**, with explicit worst- and best-case bounds.
- **Trading costs** are included in every headline number.
- **Time-robust statistics** allow for events that overlap in time.
- **Pre-registration.** The parameters are locked and publicly time-stamped before any post-event return is computed.
- **A sealed holdout**, evaluated exactly once.

---

## 2. Theory and evidence

### 2.1 Who counts as an insider, and what they must report

- **Section 16 insiders.** Under Section 16 of the Securities Exchange Act of 1934, a company's officers, directors and owners of more than 10% of a class of its registered equity must publicly report their holdings and their trades in the company's stock.
- **Form 4.** A trade is reported on Form 4.
  - Since the Sarbanes–Oxley Act of 2002 (§403, effective 29 August 2002), Form 4 must be filed within **two business days** of the trade. Before that, the deadline was the 10th day of the following month.
  - Faster reporting made the filings themselves more informative to the market (Brochet, 2010).
  - Electronic filing on the SEC's EDGAR system has been mandatory since 30 June 2003, which is why machine-readable Form 4 data exists.
- **Legal versus illegal insider trading.** Trading on the basis of material non-public information, in breach of a duty of trust or confidence, is illegal (SEC Rule 10b-5). Rule 10b5-1 defines "on the basis of" as trading while aware of the information. Insiders may legally trade on their general understanding of the business. Most companies only let insiders trade in "windows" shortly after earnings announcements (Bettis, Coles & Lemmon, 2000).
- **Pre-planned trades (Rule 10b5-1).** Insiders can set up a trading plan in advance. Trades under a plan execute automatically, so they are less likely to reflect the insider's current view — although plans can be used strategically (Jagolinzer, 2009). Since 1 April 2023, Form 4 carries a checkbox for plan trades (SEC Release No. 33-11138).
- **Transaction code P.** Form 4 codes an "open market or private purchase" as **P**. These purchases are this project's raw material.

### 2.2 Why insider purchases might predict returns

1. **Information asymmetry.** Managers know more about their firm than outside investors (Myers & Majluf, 1984). A manager putting personal wealth into the firm sends a costly, and therefore credible, signal of that knowledge (Leland & Pyle, 1977).
2. **Markets cannot be perfectly efficient.** Fama (1970) defines an efficient market as one in which prices fully reflect available information. Grossman & Stiglitz (1980) show that markets cannot be perfectly efficient in this sense: if prices already reflected all information, no one would be rewarded for acquiring it. Some return to private information must therefore persist.
3. **Purchases, not sales.** Insiders sell for many reasons unrelated to their outlook: diversification, liquidity, taxes, option exercises. They buy for essentially one. As Lynch & Rothchild (1989) put it, there are many reasons insiders might sell, but only one reason they buy: they think the stock is undervalued and will go up. Empirically, purchases predict returns and sales do so much less (Lakonishok & Lee, 2001; Jeng, Metrick & Zeckhauser, 2003).
4. **Who buys matters.** Officers and directors, who know the firm best, trade more profitably than large outside shareholders — Seyhun's (1986) "information hierarchy".
5. **Insiders are contrarians who know the fundamentals.** They tend to buy after prices fall (Rozeff & Zaman, 1998; Lakonishok & Lee, 2001), and their trades anticipate future earnings and cash flows (Piotroski & Roulstone, 2005).
6. **Routine versus opportunistic trades.** Cohen, Malloy & Pomorski (2012) show that trades by insiders who trade on a fixed calendar ("routine" traders) carry no information, while the remaining "opportunistic" trades predict returns. This project turns that finding into a model feature (§7.2).
7. **Why the market may be slow.** Limited investor attention (Hirshleifer, Lim & Teoh, 2009) and the cost and risk of arbitrage in small, illiquid stocks (Shleifer & Vishny, 1997) let information be priced in gradually. This also means the effect should be strongest exactly where trading is most expensive — a tension the project measures directly.

### 2.3 Why the evidence might not hold, and how the design responds

| Threat | Evidence | Design response |
|---|---|---|
| Returns are really size, value, momentum or price-reversal effects | Rozeff & Zaman (1988): outsiders' profits from imitating insiders disappear after controlling for size, earnings/price and costs. See also Fama & French (1993, 2015); Jegadeesh (1990) | Industry-adjusted labels remove *industry* effects only. Size, value, momentum and reversal are handled by calendar-time factor regressions that include short-term reversal (§7.1), by size-group breakdowns, and by an ML baseline that sees only market data (§7.2) |
| Trading costs eat the profit | Seyhun (1986); Novy-Marx & Velikov (2016) | Per-trade cost model; every headline number net of cost; price and liquidity floors (§6.5, §6.8) |
| Results driven by tiny stocks | Fama & French (2008); Hou, Xue & Zhang (2020) | Floors; results by size group (NYSE breakpoints); value-weighted as well as equal-weighted portfolios |
| Failed companies silently drop out (survivorship) | Brown et al. (1992); Shumway (1997); Shumway & Warther (1999) | Prices for delisted stocks; delisting returns; best- and worst-case bounds, including for events that cannot be priced (§5.1, §6.7) |
| Using information before it was public (look-ahead) | Banz & Breen (1986) | Point-in-time data, entity definitions and industry codes; entry in the session after the filing; unadjusted prices for price-level rules; automated tests (§6, §8.5) |
| Data mining and repeated backtesting | Harvey, Liu & Zhu (2016); Bailey & López de Prado (2014) | Pre-registration locked and time-stamped; sealed holdout; small, fixed grids; logged trial count; deflated Sharpe ratio; Holm–Bonferroni correction (§3.3, §7.2) |
| Effects fade after publication | McLean & Pontiff (2016) | The labelled sample (2012–2026) postdates most of the literature; results by sub-period |
| Events bunch in time (e.g., crashes), overstating precision | Mitchell & Stafford (2000); Kolari & Pynnönen (2010) | Time-robust standard errors on monthly series; calendar-time portfolios; concurrency sample weights (§7.1, §7.2) |

### 2.4 Why machine learning, and how it usually goes wrong in finance

Gu, Kelly & Xiu (2020) show that tree-based models and neural networks predict stock returns better than linear models, largely because they capture non-linear interactions between predictors. Insider signals are naturally interactive: a CEO purchase probably means more in a stock that has just fallen 40% than in one at its 52-week high.

Financial ML also fails in well-documented ways (López de Prado, 2018):
- labels that overlap in time leak information between training and test sets;
- crowded periods dominate training;
- repeated backtesting finds patterns that are not there.

The validation design in §7.2 addresses each of these. The ML is judged only by whether it beats simple baselines out of sample — including a baseline that has no insider information at all.

---

## 3. The concept: research questions and hypotheses

### 3.1 From theory to a testable idea

Theory says a single insider purchase is informative but noisy: one person's purchase may reflect personal circumstances. When **several insiders independently buy within a couple of weeks**, personal motives are a less likely explanation, and agreement among the best-informed people becomes the signal. Early studies already focused on periods of heavy, one-directional insider trading (Jaffe, 1974).

A competing explanation must also be tested: a cluster may be a *coordinated show of confidence* after bad news — a public signal rather than private information. That would predict a short-lived bounce, not sustained outperformance. Measuring returns from 5 to 252 trading days separates the two.

Clusters are also practical. In the full 2006–2026 pilot scan they occur about 140–330 times a quarter, roughly 200 on average (Appendix A). That is frequent enough to study statistically, rare enough to act on, and easy to explain to a user.

### 3.2 Research questions

- **RQ1.** Do insider purchase clusters predict positive abnormal returns after trading costs?
- **RQ2.** Is a cluster more informative than a single insider's purchase?
- **RQ3.** Can ML, using only point-in-time information, rank clusters better than simple rules and better than market data alone?

### 3.3 Pre-registered hypotheses

Only these five tests are confirmatory. Each has one primary statistic and a one-sided test at the 5% level. A Holm–Bonferroni correction across the five (Holm, 1979) keeps the chance of any false positive at 5%. Every other analysis is labelled exploratory.

| # | Hypothesis | Primary statistic and decision rule | Decided on |
|---|---|---|---|
| H1 | Clusters earn a positive mean 63-day industry-adjusted abnormal return, net of estimated trading costs | Mean of the monthly series of average net BHARs (by signal month); Newey–West standard errors with 3 lags; one-sided | Development period |
| H2a | Clusters outperform solo CEO/CFO purchases | Mean of the monthly series of differences (average A net BHAR − average B1 net BHAR); same errors; one-sided | Development period |
| H3 | The cluster effect survives standard risk factors | Intercept (alpha) of the equal-dollar, net-of-cost calendar-time cluster portfolio, regressed on the Fama–French five factors + momentum + short-term reversal with Dimson lags; Newey–West (10 lags); one-sided | Development period |
| H4 | Out of sample, the selected ML model beats a three-feature logistic regression | Mean per-event weighted log-loss difference < 0 (a Diebold–Mariano-type test with errors clustered by signal month; one-sided). Beating the base rate, rank IC > 0 and beating the market-only model are supporting evidence | Holdout |
| H5 | The model's top-quintile clusters earn positive net-of-cost alpha | Alpha as in H3 for the model portfolio; one-sided. The Sharpe ratio and the return difference against "all clusters" are supporting evidence | Holdout |

**Exploratory and replication tests.**
- **H2b** (clusters versus solo purchases by other insiders, A − B2) is exploratory, unless at least 90% of B2's delisted companies can be priced.
- The holdout re-runs of H1–H3 are reported as **replications**, not as new tests.

**Null results are results.** If a hypothesis fails, it is reported with the same detail as a success. The pipeline, methods and product remain the deliverable either way.

**Pre-registration.** Before any post-event return is computed (Step 11), this document and the parameter file (`config/params.yaml`) are tagged `prereg-v1` in git. The tag is pushed to the remote repository and published as a GitHub Release, whose creation time GitHub records on its own servers (D48). Any later change is logged in §12 with its reason.

**What the author has already seen.** The pilot (Appendix A) examined counts and purchase-size distributions for all years, including the holdout years, but never any returns. The author's general knowledge of 2023–26 market events (for example, the March 2023 regional-bank stress) is an unavoidable limitation.

**Statistical power (rough).** The pilot finds about 8,600 development clusters (2012–2022) and 2,300 labelled holdout clusters before the production rules and floors; an unknown fraction (to be measured) will remain. Events bunch in time, which shrinks the *effective* sample. Assume:
- an effective development sample of about 800 (500 was assumed for the shorter 2016–2022 period; the 2012 start adds about 1.6 times as many months);
- a 63-day abnormal-return standard deviation of about 30% (consistent with 4% daily volatility: 4% × √63 ≈ 32%).

The standard error of the mean is then about 1.1 percentage points.
- At the 5% one-sided level, an effect must exceed about 1.7 points to be significant.
- The smallest effect detectable with 80% power is about 2.6 points (about 3.4 points at the strictest Holm step, 1% one-sided).
- H5 uses only the top fifth of the holdout, so its minimum detectable 63-day effect is roughly 7–8 points. A null H5 will therefore be reported as *inconclusive*, not as evidence of no effect.

The effective sample is measured, not assumed: n × (independent-sample variance ÷ time-robust variance).

---

## 4. Scope

Scope is prioritised with MoSCoW (Must / Should / Could / Won't). ML is a **Must**. If time runs short, items are cut in the pre-registered order in §9.3, starting with product polish — never the ML core.

| Priority | In scope |
|---|---|
| **Must** | Insider data pipeline for all 83 quarters, with point-in-time entities and roles. Clean-purchase gates with a funnel audit. Point-in-time industry codes from filing headers. Event detection: clusters (A) and solo CEO/CFO buys (B1). Prices with delisted-stock coverage, delisting returns, and best/worst-case bounds (including for unpriced events). Label grid: 5 horizons × 4 abnormal-return measures, gross and net of cost. Point-in-time features. Event study on the development period. ML tournament with baselines (including a market-only model), calibration, SHAP explanations and experiment tracking. One-time holdout evaluation. Product v1: insider lookup for any stock, and a screener of the latest clusters from the newest quarterly data set. Written report |
| **Should** | Comparison group B2 (solo other insiders), time permitting (cut order, §9.3). Daily ingestion of new Form 4 filings from EDGAR, so the screener stays current. Pre-listed sensitivity variants on the development period (Appendix E) |
| **Could** | Dimson-adjusted betas for the per-event factor measure. An exploratory regression model on net returns. Public deployment |
| **Won't (this version)** | Macroeconomic features. XBRL fundamentals beyond the five items behind F26–F29 (e.g. revenue, quarterly earnings sums). A matched "no insider buying" control group. Signals from insider *selling*. Intraday data. Paid data beyond the one-month Tiingo Power plan (D39) |

---

## 5. Data sources

| Source | What we use | Coverage | Access and limits | Terms |
|---|---|---|---|---|
| SEC Insider Transactions Data Sets | All Forms 3/4/5 as tables: `SUBMISSION`, `REPORTINGOWNER`, `NONDERIV_TRANS`, `NONDERIV_HOLDING`, `DERIV_TRANS`, `DERIV_HOLDING`, `FOOTNOTES` | 2006 Q1 – 2026 Q3 (83 quarterly zip files), updated quarterly. The two newest files sit in a different SEC folder from the rest | Free bulk download. SEC fair-access policy: at most 10 requests per second, with a declared `User-Agent` that includes a contact | Public US-government data |
| SEC filing index headers (`…-index-headers.html`) | For each event's signal filing: the issuer's SIC code *as of that filing*, and the EDGAR acceptance time | Every EDGAR filing | One request per event (roughly 11,000–16,000); a background job | Public |
| SEC submissions API (`data.sec.gov/submissions`) | Filing history: 10-Q and 10-K dates, delisting and deregistration forms (25, 15), merger filings | All EDGAR filers | Same policy | Public |
| SEC company facts API (XBRL) | Shares outstanding (`dei:EntityCommonStockSharesOutstanding`), plus shareholders' equity, total assets, total liabilities, cash and net income (F26–F29), each with its filing date. One file per company holds all of them | From each company's XBRL start: large companies 2009–2010, smaller companies from mid-2011 (SEC Release No. 33-9002) | Same policy | Public |
| SEC `company_tickers.json` | Current CIK ↔ ticker map for active companies | Current only | Same policy | Public |
| Yahoo Finance via `yfinance` | Daily prices and volume for listed stocks, SPY and IWM. Yahoo's open, high, low and close are already **split-adjusted**; "Adj Close" also removes dividends; the split history is available | Listed stocks only — **no history for delisted stocks** | Unofficial API; rate-limited; every response cached | Personal use; no redistribution |
| Tiingo end-of-day API (Power plan, one month; D39) | Daily raw and adjusted prices for **delisted** stocks | Tiingo's public ticker list includes about 8,100 delisted NYSE, Nasdaq and NYSE American stocks. A delisted company's history is filed under its final ticker, often a bankruptcy `Q` ticker on an OTC venue | 110,346 unique symbols per month, 10,000 requests per hour, 100,000 per day | "Internal use only". Data may be stored only while the paid plan is active, and is deleted when it ends (ToS §1.6(b)) |
| FINRA Tick Size Pilot lists | Which small-cap stocks were quoted in $0.05 increments, October 2016 – September 2018 | The pilot period only | Free download | Public |
| Kenneth French Data Library | Daily Fama–French five factors, momentum and short-term reversal; daily equal- and value-weighted returns for 49 and 12 industry portfolios; SIC-to-industry definitions; NYSE market-cap breakpoints | Decades of history, through 31 August 2026 at the time of writing (updated with a lag of a few months) | Free download | Free for research use |

**Considered and not used:**
- **FRED** macroeconomic series — macro features were dropped (§12, D24).
- **Stooq** — blocks scripted downloads with a browser check.
- **CRSP and Compustat** — not available.
- **Tiingo's free Starter plan** — its terms forbid storing Tiingo data (ToS §1.6(a), updated 6 October 2026), so it cannot feed a stored raw snapshot. Outside the paid month, only Tiingo's public ticker list is used, in memory.

### 5.1 Why two price sources: survivorship bias

Yahoo keeps price history only for stocks that still trade. When a company is acquired or goes bankrupt, its history disappears.

In the pilot, Yahoo returned no prices at all for Silicon Valley Bank (SIVB), First Republic (FRC) or Bed Bath & Beyond (BBBY) for January 2022 — a month in which all three traded normally. It returned Apple's prices for the same month.

If only Yahoo were used, every event at a company that later disappeared would drop out of the data, and the results would describe survivors only (Brown, Goetzmann, Ibbotson & Ross, 1992; Shumway, 1997). The direction of that bias is not obvious. Failures would be lost, which flatters insider buying, but so would takeovers, which often end with a premium. Neither can be dropped. Tiingo keeps delisted histories, so its limited free allowance is spent **only** on stocks Yahoo cannot supply.

### 5.2 Delisted-stock prices and the start of the labelled window

**Why a paid month.** Tiingo's free Starter plan forbids writing Tiingo data to any persistent storage (ToS §1.6(a), updated 6 October 2026). This design needs stored prices: a raw snapshot and a warehouse (§8). One month of Tiingo Power is therefore used for delisted stocks (D39).
- Power allows 110,346 unique symbols a month and 10,000 requests an hour, so the 500-symbol budget of the free plan, and the budget rule of v2.1, no longer apply (D40).
- Storage is allowed only while the paid plan is active (§1.6(b)). When it ends, all Tiingo data is deleted, including per-stock tables derived from it, and the deletion is logged (constitution Principle VI).
- The month starts on the day of the delisted-price pull (Step 7), so it covers the hand-in on 18 November. The offline-rebuild check (Step 21) runs before the plan expires (constitution Principle V).

**Pilot result.** The full 2006–2026 scan (Appendix A.3) counted, for each possible start year, the distinct companies with A or B1 events:

| Labelled window starts | Events (A + B1) | Companies | Delisted, in Tiingo's list | Not matched to Tiingo's list |
|---|---|---|---|---|
| 2006 | 21,904 | 6,682 | 1,982 | 1,233 (18%) |
| 2009 | 17,636 | 5,560 | 1,657 | 708 (13%) |
| 2011 | 16,085 | 5,179 | 1,515 | 572 (11%) |
| 2014 | 13,404 | 4,545 | 1,234 | 413 (9%) |
| 2016 | 11,162 | 4,039 | 955 | 340 (8%) |

Feature 001 rebuilt this scan from the SEC data (`sentinel candidates-provisional`, `specs/001-skeleton-sec-ingest/run-notes.md`). Events and companies agree with the pilot to within 0.7%. With matching widened to OTC venues and bankruptcy `Q` tickers, about 2,235 delisted companies across 2006–2026 are found in Tiingo's list, 1,152 of them with events from 2016.

**What this shows.**
1. Every start year fits comfortably within the paid allowance.
2. Coverage is weaker for older periods. In the pilot, the share of companies not matched to Tiingo's ticker list falls from 18% for a 2006 start to 8% for a 2016 start. Some of these will be recovered by the production symbol map (Step 6), which must look up a company's final, often `Q`-suffixed, ticker. The rest are excluded and covered by the bounds in §6.7.

**Start of the labelled window: 1 January 2012 (D42).** The rule is to start where every data source is complete without workarounds; this is a course project, not an institutional tool.
- **Binding source: XBRL share counts.** Needed for market capitalisation (D23), they cover large companies from 2009–2010 and all filers only from mid-2011 (SEC Release No. 33-9002), so by 1 January 2012 every company has filed one. SEC insider data, filing headers, Yahoo and the French library cover the whole period.
- **Development period 2012–2022.** Provisional counts from feature 001: 11,470 development events against 7,675 for a 2016 start (+49%), which strengthens the ML stage. Delisted companies found in Tiingo's list: 79%, against 83% for a 2016 start.
- **Insider history.** Every labelled event has at least six years of insider filings behind it (from 2006).
- **Not included:** the 2008–09 crisis. An earlier start would need a substitute for the missing share counts.
- **Holdout unchanged:** signal dates from 1 January 2023 to 1 June 2026. 1 June 2026 is the last signal date whose 63-session window ends by 31 August 2026, the last date of the factor data. Insider filings from 2006 onward feed the history-based features.

---

## 6. From filings to events: definitions

### 6.1 Point in time, signal date and entry

**Point-in-time (PIT) principle.** Every input used for an event must have been public before the moment a trade is assumed. Every table records when each fact became public (a filing date or a market date). Automated tests check this, including a "truncation test": deleting all data after T must leave every event, entity, role, feature and floor decision at T unchanged (§8.5).

**Signal date T** is the SEC filing date of the Form 4 that completes an event's conditions. SEC business days can differ from market days (the SEC is open on Good Friday; the stock market is not). Any rule "at T" therefore uses **the last trading session on or before T**.

**Entry** is at the **open of the first trading session after T** (session T+1).
- Under Regulation S-T Rule 13(a)(4), Forms 3, 4 and 5 submitted up to 10 p.m. Eastern time receive that day's filing date. A Form 4 dated T can therefore become public after the market has closed on T.
- The pilot found a real example: a Form 4 for Prothena dated 31 March 2023 was accepted at 21:31 ET.
- The open of T+1 is the first price at which any investor could have acted on every filing dated T.

### 6.2 Clean purchases: the gates

A raw Form 4 purchase becomes a **clean purchase** only if it passes the gates below. The funnel (rows in and out of each gate, per quarter) is stored and shown in the product.

| Gate | Rule | Why |
|---|---|---|
| G1 Form | Original Form 4 only (no 4/A amendments, no Forms 3 or 5) | Amendments re-report earlier filings and would double-count. Form 3 reports initial holdings. Open-market purchases must be reported on Form 4 |
| G2 Transaction | Non-derivative table; code **P**; shares acquired (A) | The insider bought shares — not an award, option exercise or gift |
| G3 Security | Common stock: the title contains *common*, *ordinary* or a share class; preferred stock, warrants, units, notes, options and rights are excluded | Prices and returns refer to the common stock |
| G4 Not pre-planned | The 10b5-1 checkbox is not ticked. The field appears in the 2023-onward data sets and is recorded **per filing**, so a ticked box excludes every purchase in that filing. In addition, no footnote referenced by the transaction mentions a 10b5-1 plan, dividend reinvestment, an employee stock purchase plan or automatic purchases | Isolates *discretionary* purchases. Before 2023, only footnotes can reveal plan trades. Even after 2023, trades under plans adopted before 27 February 2023 need not be flagged, so footnote screening continues throughout |
| G5 Not an offering | No referenced footnote mentions a public or underwritten offering, private placement, registered direct offering, subscription or securities purchase agreement, PIPE, rights offering, or buying directly from the company | Code P includes *private* purchases. An insider joining a company share sale is supporting a financing, not making an open-market bet |
| G6 Size and timeliness | Total value per entity per filing ≥ $25,000, filed within 30 days of the trade | In the pilot, a $10k rule removes 25–39% of the filings that pass G1–G5 but less than 0.1% of their dollar value: it removes token purchases, not money. $25k (D46) also stops a token purchase from counting as a cluster's second buyer. Filings made long after the trade describe old decisions and could create spurious clusters |
| G7 Issuer type *(applied to events)* | Exclude blank-check companies (SIC 6770, e.g., SPACs) and registered funds (SIC 6722, 6726), using the issuer's SIC **recorded in the signal filing's header**, and issuers whose header carries no SIC code (D45) | Their prices are anchored to trust value or net asset value. Using the SIC at the time — not today's — avoids dropping companies that only later became shells, and avoids keeping SPACs that later merged |
| G8 Price check *(after prices load)* | The reported price must lie within the day's unadjusted traded range, ±10% | Catches data-entry errors and wrong ticker matches |

Footnote filters scan only the footnotes *referenced by that transaction*, so a clean purchase is not excluded because a different line in the filing mentions a plan. Their precision is checked by hand on 50 excluded and 50 kept transactions (Step 4).

### 6.3 Insiders as economic entities (point-in-time)

A single economic decision is often reported by several "reporting owners" on one filing — for example an investment fund, its general partner and its manager. Counted naively, that looks like three insiders. In the pilot, 14–16% of clean purchase filings listed more than one owner.

**Rule.**
- Reporting owners who have appeared together on a filing for the same issuer, **dated on or before T**, are merged into one **entity**. Formally, the entities are the connected components of the co-filing graph built from that issuer's filings dated on or before T.
- Each member's role is taken from the relationship flags (director, officer, 10% owner, other) and the officer title on **its filings dated on or before T**. Regular expressions catch the variants of chief executive and chief financial officer.
- An entity takes its most senior member's role, ranked CEO/CFO > other officer > director > 10% owner > other. This follows Seyhun's (1986) information hierarchy.
- Membership is stored with a valid-from date, so a director who later becomes CEO counts as a director in earlier events.

### 6.4 Events

| Group | Definition (all point-in-time, on signal date T) |
|---|---|
| **A — Cluster** | The issuer's clean purchases filed in the 14 calendar days ending on T come from **≥ 2 entities**, at least one of them an officer or director, and total **≥ $100,000** |
| **B1 — Solo CEO/CFO** | A CEO or CFO entity's clean purchases filed in the 14 days ending on T total ≥ $100,000, and **no other entity filed a clean purchase** in that window |
| **B2 — Solo other** | As B1, but the buyer is another officer or a director (owners holding only a 10% stake are excluded) |

**Order of operations.**
1. Gates G1–G6 on the Form 4 data.
2. Preliminary event detection — used only to choose which symbols to price.
3. Prices.
4. Price check G8.
5. Final event detection, on the purchases that pass.
6. At each candidate T: the issuer-type rule G7 and the tradability floors (§6.5).
7. Cooldown, triggered only by events that pass step 6.

Purchases at issuers that cannot be priced skip G8, and their events are counted as unpriced.

**Cooldown.** After an event, the same issuer cannot produce another event *in the same group* for 63 trading sessions — one primary label window. A stock therefore never has two overlapping labels within a group at horizons up to 63 sessions. Across the full 2006–2026 pilot, this costs about 13% of clusters compared with a 21-calendar-day cooldown.

**Groups are analysed separately.** A B1 purchase can be joined by other insiders after T and become part of a later A event. B1 therefore includes some purchases that turn into clusters, which biases A − B1 toward zero (a conservative bias for H2a). The share of such B1 events is reported, and H2a is re-run without them as a robustness check. That check uses later information, so it is not a trading rule.

**Parameter justifications.**
- **Two or more entities, including an officer or director.** Two is the smallest number that represents independent agreement. Requiring an officer or director keeps clusters made up only of related outside funds from qualifying.
- **14 days.** Form 4 is due within two business days of the trade, so filing dates track trade dates closely. In Bettis et al.'s (2000) survey, the most common company policy was a trading window of about ten trading days after an earnings announcement — roughly two calendar weeks — so coordinated buying in one window shows up within that span. Practice may have changed since that 1996 survey, which makes the 30-day variant an important check.
- **$100,000.** About 1.3 times the median clean purchase in the pilot (about $75–80k, measured after the $10k gate), so a cluster requires a real joint financial commitment.
- **Sensitivity.** Appendix E lists the variants.

### 6.5 Tradability floors

Applied to every event at the close of the last session on or before T, using prices up to that session only.

| Floor | Value | Justification |
|---|---|---|
| Price | Unadjusted close ≥ **$2.00** | See the three reasons below the table |
| Liquidity | 20-day average daily dollar volume (ADDV20) ≥ **$100,000** | Your own buying moves the price, so the floor is set as position size ÷ the maximum share of daily volume. A **$10,000** position (a small retail position, matching the product's audience; §12 D7) at no more than **10%** of a day's volume gives $100,000. The cost model (§6.8) still charges every trade for its own share of volume, so the floor removes only stocks where a $10k order would be an outsized share of trading |
| Activity | Volume > 0 on ≥ 18 of the last 20 sessions | Stale prices make returns, volatility and spread estimates unreliable |

**Why a $2 price floor.**
1. **Tick size.** US stocks priced at $1 or more are quoted in $0.01 increments (Regulation NMS Rule 612), so the narrowest possible quoted spread is 1% of the price at $1 but 0.5% at $2. Real micro-cap spreads are several ticks wider. Two exceptions:
   - During the SEC's Tick Size Pilot (October 2016 – September 2018), about 1,200 small-cap stocks were quoted in $0.05 increments. For those stock-days, the one-tick spread floor uses $0.05, taken from FINRA's published pilot lists.
   - Amendments adopted in 2024 add a $0.005 increment only for the most tightly quoted stocks, which does not affect illiquid micro-caps.
2. **Listing compliance.** Nasdaq sends a deficiency notice when a stock's bid price stays below $1 for 30 consecutive business days (Nasdaq Rules 5450(a)(1), 5550(a)(2) and 5810(c)(3)(A)). NYSE does so when the average closing price over 30 trading days is below $1 (NYSE Listed Company Manual 802.01C). Stocks between $1 and $2 are prone to reverse splits and delisting, which distort returns.
3. **The alternative is too strict.** The common academic $5 filter (e.g., Jegadeesh & Titman, 2001) — which mirrors the $5 price test in the SEC's penny-stock definition (Rule 3a51-1), although that definition largely excludes exchange-listed stocks — would remove most micro-caps, which this project deliberately studies.

**Prices on the day, not adjusted prices.** Yahoo's prices are already adjusted for *later* splits. A stock trading at $0.40 that later does a 1-for-10 reverse split would show $4.00 and wrongly pass the floor — and reverse splits cluster in distressed micro-caps.
- Every price-level rule therefore uses the **unadjusted price on the day**: the $2 floor, the one-tick spread floor, G8 and market capitalisation.
- For Yahoo, unadjusted prices are rebuilt by undoing later splits from its split history. Tiingo supplies raw prices directly.
- Returns use split- and dividend-adjusted prices.
- Dollar volume is unaffected, because a split scales price and volume in opposite directions.

**Validation.** On the development period, estimated spreads are plotted against price; if costs jump at a level other than $2, that is reported. These floors define the *research* universe only — the product's insider lookup covers every stock.

### 6.6 Returns, benchmarks and labels

**Holding window.** Enter at the adjusted open of session T+1; exit at the adjusted close of session T+H. The horizons are H ∈ {5, 21, 63, 126, 252} trading days, from one week to one year.

**Buy-and-hold abnormal return (BHAR)** = the stock's buy-and-hold return − the benchmark's buy-and-hold return over the same window (Barber & Lyon, 1997).

**Four abnormal-return measures** (three BHARs and one factor-model measure, all computed for every event):

| Measure | Why it is included |
|---|---|
| BHAR against SPY (S&P 500 ETF) | Investable and intuitive; used in the product. Biased against small stocks |
| BHAR against IWM (Russell 2000 ETF) | Investable small-cap comparison |
| **BHAR against the equal-weighted Fama–French 49-industry portfolio** of the issuer's industry — **primary** | Compares the stock with peers in its own industry, using the SIC code at T. Equal weighting lets the typical (small) firm count, as in this sample. Uses the data library's 49-industry revision of the SIC-based Fama & French (1997) classification, with consistent daily history. The value-weighted version is reported as a check |
| Cumulative abnormal return from FF5 + UMD | Removes exposure to market, size, value, profitability, investment and momentum. Betas are estimated on sessions T−252 to T−21 (at least 120 observations) and the abnormal return is cumulated over the window |

**Why not cap-weighted sector or style ETFs.** QQQ, SOXX and IBB were rejected as primary benchmarks because they are dominated by the largest companies — a poor peer for a $300 million firm.

**Two known biases in the industry benchmark.** Both are documented rather than corrected:
- The industry portfolios run close-to-close, so their window includes one extra overnight move compared with the stock's open-to-close window. This is negligible.
- Compounding daily-rebalanced equal-weighted returns slightly overstates the benchmark (Blume & Stambaugh, 1983; Barber & Lyon, 1997). That biases abnormal returns *downward*, which makes the label conservative.

**Primary label (pre-registered).** The **63-day BHAR against the equal-weighted industry portfolio, net of the event's estimated round-trip trading cost**. For the classifier, the target is **y = 1 if this net BHAR > 0** — the trade would have beaten its industry peers after paying for itself. The continuous net and gross BHARs are kept for ranking metrics.

**Why 63 days.**
- It usually spans the next quarterly earnings announcement, a major information event, and insider trades anticipate future earnings (Piotroski & Roulstone, 2005). The share of windows that contain the next 10-Q or 10-K filing date is reported.
- It sits between the one-month holding period tested by Cohen et al. (2012), whose event-time returns keep rising for about six months, and the twelve-month horizon of Lakonishok & Lee (2001).
- Shorter windows give more independent observations, fewer mid-window delistings and more labelled events near the end of the sample.
- It was fixed before any results were seen; all other horizons are reported alongside.

**Why "net of own cost > 0" instead of a fixed threshold.** The first draft used "beat IWM by 5 percentage points". A fixed threshold is arbitrary and means different things at different horizons and liquidity levels. Using each trade's own cost asks the economically meaningful question.

**Why a classifier.** Returns are heavy-tailed. A classifier is robust to a few extreme outcomes and produces calibrated probabilities, which the product displays. Two caveats are handled explicitly:
- **Cost is part of the label.** The cost is a fixed formula of features F17, F22 and F23, so part of any measured skill could be "predicting its own cost". Ranking metrics are therefore reported against gross as well as net returns, alongside a cost-only ranking (§7.2).
- **Probability and expected return can rank events differently.** An exploratory regression model on net returns is listed under *Could*.

### 6.7 Stocks that delist during the window, and events that cannot be priced

If a stock's prices end before T+H:
1. The return runs to the last available close.
2. A **delisting return** is applied, according to why the stock left (classified from SEC filings):

| Class | Evidence | Delisting return |
|---|---|---|
| Acquired | A merger proxy, tender offer or merger registration filing in the 12 months before the last trade | 0% (the last price approximates the deal value) |
| Performance-related | An exchange delisting notice (Form 25) or deregistration (Form 15), with no merger evidence | −30% for NYSE and NYSE American stocks; −55% for Nasdaq stocks (Shumway, 1997; Shumway & Warther, 1999) |
| Unknown | Prices end with no delisting, deregistration or merger filing | Main run: the performance-related return. Bounds: 0% and −100%. Reported separately |

3. After delisting, the position is assumed to earn the benchmark for the rest of the window, so the abnormal return is zero from then on.

**Re-mapping, not delisting.** An issuer that is still filing 10-Qs after its last price is treated as a ticker change and re-mapped.

**Bounds.**
- All results are re-run with every delisting return set to 0% and to −100%.
- **Unpriced events:** H1 is recomputed with every unpriced event set to −100% (worst case) and to zero net BHAR (best case).

**Coverage criterion.** Price coverage is the share of detected A and B1 events, before floors, that have prices on sessions T−19 to T+1.
- The target is ≥ 90%, reported by year and by delisting status.
- If the target is missed, the unpriced-event bounds become a headline result. The window does not change after the fact.
- Separately, G8's pass rate (the share of mapped clean purchases inside the day's range) should be ≥ 95%.

### 6.8 Trading-cost model

The round-trip cost for event *i* is

> **cᵢ = Sᵢ + 2 · σᵢ · √(Q / ADDVᵢ)**

where:
- **Sᵢ** is the estimated proportional bid–ask spread from daily high, low and close prices (Abdi & Ranaldo, 2017), averaged over the 20 sessions to T and floored at one tick relative to the unadjusted price. The Corwin & Schultz (2012) estimator is used as a cross-check. The full spread is paid once per round trip: half on entry, half on exit.
- **σᵢ · √(Q / ADDVᵢ)** is the price impact of an order of size Q, paid on entry and on exit.
  - The square-root form with a coefficient of order one is the "square-root law" documented by Tóth et al. (2011), on futures data.
  - Almgren, Thum, Hauptmann & Li (2005), using large-cap US stocks, find a similar concave shape but estimate an exponent of about 0.6, and reject exactly 0.5.
  - Neither was estimated on micro-caps, so the coefficient (set to 1) is varied in the sensitivity runs (Appendix E).
- **σᵢ** is the daily return volatility over 63 sessions.
- **Q** is $10,000 (§6.5).

*Illustration.* A $2 stock with a two-tick spread (1%) and 4% daily volatility:
- If it trades $100,000 a day (exactly the floor), a $10,000 order is 10% of daily volume and costs about 1% + 2 × 4% × 0.32 ≈ **3.5%** round trip.
- If it trades $1 million a day, the same order is 1% of daily volume and costs about **1.8%**.

These are model estimates, which is why results are also shown gross of cost.

---

## 7. Methods

### 7.1 Stage 1 — Event study (development period, 2012–2022)

Standard event-study methods are used (Brown & Warner, 1985; MacKinlay, 1997). **Development analyses use only label windows that end by 31 December 2022, at every horizon**, so no development result contains a holdout-period return.

- **Average abnormal-return paths** run from 20 sessions before entry to 252 after, for groups A, B1 and B2. The pre-entry segment shows the price decline that typically precedes insider buying.
- **BHAR tables** report the mean, median and share positive, for every horizon × measure, gross and net of cost.
- **Inference that allows for overlap.** A 63-session window spans about three calendar months, so events in neighbouring months share return days.
  - For each horizon H, net BHARs are averaged by signal month. The mean of that monthly series is tested with Newey–West standard errors (Newey & West, 1987) using ⌈H/21⌉ lags — 3 at 63 days.
  - Group comparisons (H2) use the monthly series of differences between group averages, tested the same way.
  - A moving-block bootstrap over months (block length ≥ H/21; Künsch, 1989) checks for skewness (Lyon, Barber & Tsai, 1999).
  - Confidence bands on the paths use the same method.
- **Breakdowns** are reported by:
  - size group — micro, small and big, using NYSE market-cap breakpoints at the 20th and 50th percentiles (Fama & French, 2008);
  - sector (the 12 Fama–French sectors);
  - sub-period (2012–2019 and 2020–2022);
  - cluster size (2, 3, ≥ 4 entities);
  - CEO/CFO participation.
- **Calendar-time portfolios** (Fama, 1998; Mitchell & Stafford, 2000).
  - **Construction.** Each event is bought with equal dollars at the T+1 open and held without rebalancing to its exit. The portfolio's daily return is the value-weighted return of its open positions. Entry cost (half the spread plus one impact term) is charged on the entry day, and exit cost on the exit day.
  - **Weighting.** Equal-dollar weighting is primary. A value-weighted version uses market capitalisation at T, or ADDV20 where that is missing.
  - **Thin days.** Days with fewer than 10 open positions are excluded; a sensitivity check keeps them.
  - **Regression.** Daily excess returns are regressed on FF5 + UMD + short-term reversal, with one- and two-day lags of the factors to allow for thin trading (Dimson, 1979). Alpha uses Newey–West standard errors with 10 lags. The regression is repeated on monthly returns, and FF5 + UMD alone is reported as a check.

The holdout is not examined until Step 18.

### 7.2 Stage 2 — Machine learning

**Unit of analysis.** One cluster event (group A) that passes the floors.

**Target.** The primary label (§6.6).

**Why clusters only.** The research question concerns clusters; the solo groups exist for the H2 comparison. Pooling would also put overlapping windows from the same issuer into one training set.

**Features.** All computed from information available at the close of the last session on or before T. All Form 4 look-backs select filings by filing date ≤ T.

| # | Feature | Source | Rationale |
|---|---|---|---|
| F1 | Number of distinct entities buying in the window | Form 4 | Breadth of agreement (§3.1) |
| F2 | Total purchase value | Form 4 | Size of the financial commitment |
| F3 | Largest buyer's share of the total | Form 4 | Broad buying versus one dominant buyer |
| F4 | Number of CEO/CFO entities buying | Form 4 | Information hierarchy (Seyhun, 1986) |
| F5 | Number of director entities | Form 4 | Same |
| F6 | Number of 10% owners | Form 4 | The least-informed group (Seyhun, 1986) |
| F7 | Mean log increase in buyers' holdings: log(shares held after ÷ shares held before), each buyer's direct and indirect holdings in the filing summed | Form 4 | Conviction relative to the existing stake. Summing matters: insiders often hold through trusts or funds on separate lines |
| F8 | Buyers opening a new position | Form 4 | A first commitment |
| F9 | Share of buyers classified *opportunistic* | Form 4 history | Following Cohen et al. (2012), classification happens at the start of each calendar year, using all open-market purchases and sales (codes P and S) in the previous three years. A *routine* insider traded in the same calendar month in each of those years; everyone else with three years of history is *opportunistic*. Missing for insiders with less than three years of history |
| F10 | Buyers' past hit rate at this issuer | Form 4 history + prices | Mean over buyers of (h + k·p̄) ÷ (n + k), with k = 5. Here n counts the buyer's earlier clean purchases at this issuer whose 63-session windows (from each filing date) ended before T; h counts those with net industry-adjusted BHAR > 0; p̄ is the base rate of the primary label over the 36 months before T |
| F11 | Mean filing lag (filing date − trade date) | Form 4 | Slow reporting |
| F12 | Value of insider open-market sales at the issuer in the prior 90 days | Form 4 (code S) | Conflicting insider views |
| F13 | Any CEO/CFO open-market sale in the prior 90 days | Form 4 | Replaces the first draft's hard "sell veto" with a learnable feature |
| F14 | Clean purchase filings at the issuer in the prior 365 days, excluding the window | Form 4 | Repeated buying |
| F15 | Days since the last 10-Q or 10-K | SEC submissions | Trading-window timing (Bettis et al., 2000) |
| F16 | Market capitalisation | Unadjusted price × the latest shares outstanding filed on or before T | Size (Banz, 1981). Missing where the cover-page shares tag is absent |
| F17 | ADDV20 | Prices | Liquidity; also stands in for size where F16 is missing |
| F18 | Cluster value ÷ ADDV20 | Form 4 + prices | Purchase size relative to normal trading |
| F19 | Return over the prior 21 sessions | Prices | Short-term reversal (Jegadeesh, 1990) |
| F20 | Return from session T−252 to T−21 | Prices | Momentum (Jegadeesh & Titman, 1993) |
| F21 | Distance from the 52-week high | Prices | George & Hwang (2004) |
| F22 | Daily volatility over 63 sessions | Prices | Risk |
| F23 | Estimated bid–ask spread | Prices | Trading cost (Abdi & Ranaldo, 2017) |
| F24 | Sector (12 Fama–French sectors), from the SIC code at T | Filing header | Industry differences |
| F25 | Cluster value ÷ market capitalisation (F2 ÷ F16) | Form 4 + XBRL + prices | A $1M purchase means far more at a $50M company than at a $5B one. Missing where F16 is missing |
| F26 | Book-to-market: latest shareholders' equity ÷ F16 | XBRL | Insider purchases are reported to predict best in small value stocks (Lakonishok & Lee, 2001). Negative equity is kept, then winsorised |
| F27 | Loss-making: latest reported net income (quarter or year) < 0 | XBRL | Distressed companies behave differently |
| F28 | Leverage: total liabilities ÷ total assets | XBRL | Financial risk |
| F29 | Cash ÷ total assets | XBRL | Ability to survive a downturn |

**Company financials (F16, F26–F29) — kept simple.** Each value is taken from the SEC company facts file for the latest period whose *first* filing date is on or before T, and only the value as first filed is used: later restatements are ignored, so nothing the market did not know is used (D23, D43). Tags, with one fallback each: shareholders' equity `StockholdersEquity` (else including non-controlling interests); total assets `Assets`; total liabilities `Liabilities` (else assets − equity); cash `CashAndCashEquivalentsAtCarryingValue` (else including restricted cash); net income `NetIncomeLoss` (else `ProfitLoss`). Missing values get missing-value indicators like any other feature.

**No time or macro features.** Calendar variables (year, date) and macroeconomic variables are not used. The 2012–2022 training data contain only a few crises, so a model could memorise *when* rather than learn *what* (§12, D24). Market conditions are examined in the error analysis instead.

**The tournament.**

| Model | Why it is included | Tuning grid (small, pre-registered) |
|---|---|---|
| M1 Elastic-net logistic regression (Zou & Hastie, 2005) | Interpretable linear benchmark with built-in feature selection | C ∈ {0.01, 0.1, 1}; l1_ratio ∈ {0.2, 0.5, 0.8}; `solver="saga"`* |
| M2 Random forest (Breiman, 2001) | Robust non-linear model needing little tuning | max_depth ∈ {4, 6, 8}; min_samples_leaf ∈ {25, 50, 100}; 500 trees |
| M3 LightGBM (Ke et al., 2017) | Strong gradient-boosted trees for tabular data; handles missing values natively | num_leaves ∈ {7, 15}; min_child_samples ∈ {25, 50, 100}; learning rate 0.03; number of trees chosen on the tuning slice |
| Ensemble | Average of the M1–M3 calibrated probabilities | — |

\* In current scikit-learn (1.9), elastic net is set with `l1_ratio` and `solver="saga"`. The older `penalty="elasticnet"` argument is deprecated.

That is 25 configurations in total (9 + 9 + 6 + 1).

**Preprocessing.**
- **Fixed in advance (no fitting).** Dollar-denominated features (F2, F12, F16, F17) are divided by the S&P 500 level (SPY close) on the last session on or before T, then logged. A decade of market growth therefore does not make early and late events incomparable.
- **Fitted on each fold's fitting data only:**
  - winsorising continuous features at the 1st and 99th percentiles;
  - median imputation plus missing-value indicators (M1, M2);
  - standardisation (M1);
  - one-hot sector.
- **No resampling of classes**, which would distort the probabilities.

**Validation: purged, expanding walk-forward.**

```
signal year →  2012 … 2018 │ 2019 │ 2020 │ 2021 │ 2022 ║ 2023 … 1 Jun 2026
fold 1         [──── train ────]  test
fold 2         [─────── train ───────]  test
fold 3         [────────── train ──────────]  test
fold 4         [───────────── train ─────────────]  test
holdout model  [──────────── all development data ────────────] ║ HOLDOUT (evaluated once)

inside every training window:  [ fit set ……… ][ tuning: months −12…−7 ][ calibration: months −6…−1 ]
```

- **Folds.** Four yearly test folds, 2019–2022. Each training window holds all events whose label windows end before its test year begins. With the 2012 start (D42), fold 1 trains on 2012–2018.
- **Three-way split inside each training window:**
  1. The **fit set** is everything before the last 12 months.
  2. The **tuning slice** (months −12 to −7) chooses hyperparameters and the number of boosting rounds.
  3. The model is then **refitted** on the fit set plus the tuning slice, with the chosen settings.
  4. The **calibration slice** (months −6 to −1) fits the Platt map (Platt, 2000) and the portfolio cut-off. The refitted model has never seen it.
- **Purging.** Every boundary is purged: an event is used on one side only if its label window ends before the next part begins (López de Prado, 2018, ch. 7). Because training always precedes testing, no extra "embargo" is needed.
- **Why calibrate at all.** Boosted trees' raw scores are often poorly calibrated, while bagged trees' are better (Niculescu-Mizil & Caruana, 2005). The product shows probabilities, so every model is calibrated the same way for comparability. Calibration is never fitted on randomly shuffled data — that was a leak in the first draft.
- **Holdout model.** The same recipe on the whole development period, using only events whose windows end by 31 December 2022.
- **Minimum size.** Post-floor event counts for each fold are reported before any model is fitted. If fold 1's fit set has fewer than 500 events, fold 1 is dropped (pre-registered).
- **Sample weights: calendar concurrency.** This is adapted from López de Prado's (2018, ch. 4) "average uniqueness".
  - Each event is weighted by the average, over the days of its label window, of 1 ÷ (number of floor-passing cluster events whose windows include that day). Weights are normalised to a mean of 1.
  - Crowded periods such as March 2020 then cannot dominate training.
  - The effective sample size implied by the weights is reported per fold, and an unweighted fit is reported as a sensitivity — not as a selection candidate.

**Model selection (pre-registered).**
- Candidates are ordered from simplest to most complex: M1, M2, M3, ensemble.
- The simplest candidate whose mean weighted out-of-fold **log loss** is within one standard error of the best is chosen — the "one-standard-error rule" (Hastie, Tibshirani & Friedman, 2009). The standard error is paired across candidates and clustered by month.
- Log loss is a proper scoring rule: it rewards honest probabilities.
- Per-fold log losses are reported.

**Baselines the models must beat.**
1. **Base rate** — always predict the training share of positive labels.
2. **Three-feature logistic regression** — number of entities, any CEO/CFO buyer, log total value.
3. **Rule** — select clusters with ≥ 3 entities or a CEO/CFO buyer.
4. **All clusters** — buy every cluster (portfolio comparison only).
5. **Market-only model** — the selected model family trained only on market and company data (F16, F17, F19–F24, F26–F29), with no insider information. The gap between it and the full model measures the value of the insider information itself.
6. **Cost-only ranking** — rank events by −cᵢ (ranking metrics only).

All baselines use the same folds, weights and purging.

**Evaluation metrics.**
- **Probabilistic.** Log loss; Brier score (Brier, 1950) and Brier skill score against the base rate; ROC-AUC; reliability (calibration) curve.
- **Ranking.** The Spearman rank correlation (rank IC) between predicted probability and realised net *and* gross BHAR, computed per calendar quarter and averaged, with a t-statistic across quarters.
- **Economic.**
  - An event enters the model portfolio if its predicted probability is at or above the 80th percentile of the model's predictions on its calibration slice. That threshold is known at the time; ranking within a quarter would use events that had not happened yet.
  - The portfolio is built and tested like the calendar-time portfolios in §7.1.
  - The **deflated Sharpe ratio** (Bailey & López de Prado, 2014) is computed for the selected model's *development* out-of-fold portfolio, with N = 25 configurations and the variance of their Sharpe ratios.
  - The holdout Sharpe ratio is reported with its standard error (Lo, 2002).

**Holdout (sealed).**
- Signal dates run from 1 January 2023 to 1 June 2026.
- Labels for windows ending after 31 December 2022 — and the past-purchase outcomes that F10 needs for holdout events — are computed **only inside the guarded Step 18 job** and stored in a separate schema. The code refuses holdout access without an explicit flag and logs the single run.
- Because the 10b5-1 checkbox exists only from April 2023, the holdout is also evaluated with the checkbox gate switched off, so its definition of a clean purchase matches the development period's.
- After the holdout evaluation, the production model is refitted on all labelled data with the same recipe; the reported holdout numbers belong to the pre-refit model.

**Explainability.** SHAP values (Lundberg & Lee, 2017; TreeSHAP for the tree models, Lundberg et al., 2020) give global importance, dependence plots, and each event's top three drivers, which the product displays. SHAP explains *the model*, not causes in the market.

**Error analysis.** Performance by year, sector, size group, cluster size and market-volatility regime (terciles of SPY's 63-day realised volatility).

**Experiment tracking.** MLflow (local) records, for every run, the git commit, the parameter-file hash, the data snapshot, the hyperparameters, the metrics and the artefacts.

---

## 8. System architecture and tech stack

### 8.1 Architecture

```
SOURCES     SEC bulk data sets · SEC headers, submissions & company facts
            Yahoo (listed) · Tiingo (delisted) · Kenneth French library
                 │  fetchers: rate-limited, retried, cached
                 ▼
RAW         data/raw/   immutable files + manifest (URL, fetch time, SHA-256)
                 │
                 ▼
WAREHOUSE   one DuckDB file, rebuilt layer by layer
  stg       typed copies of raw tables (schema changes handled here)
  core      issuers · point-in-time entities · all transactions · clean purchases
            prices (unadjusted + adjusted + split factors) · symbol map
            SIC at filing · delistings · XBRL facts (shares, 5 items) · factor tables
  evt       events (A, B1, B2) + member filings
  feat      one feature row per event, as of T
  lab       development labels (windows ending by 31 Dec 2022)
  hold      holdout labels and outcomes — written only by the guarded Step 18 job
  ml        datasets · predictions (out-of-fold, holdout, live) · run index
  audit     funnel counts per gate per quarter · data-quality results
                 │                                 │
                 ▼                                 ▼
RESEARCH    event study, ML tournament,       PRODUCT   FastAPI (read-only)
            reports and figures (MLflow)                screener · lookup · model card
```

Each layer is rebuilt deterministically from the one above by an idempotent command. The whole warehouse can be deleted and regenerated from `data/raw/`.

### 8.2 Core data model

| Table | One row per | Key columns |
|---|---|---|
| `core.issuer` | Company (CIK) | Name, current SIC, exchanges and tickers (today's values: reporting and the D45 fallback only) |
| `core.filing` | Filing (accession), first quarter that lists it | Issuer, filing date, form type, reported ticker |
| `core.filing_header` | Event signal filing | Accession, SIC at filing and its label, acceptance time (ET) |
| `core.entity_member` | Issuer × reporting owner × valid-from date | Entity id |
| `core.owner_role` | Issuer × reporting owner × valid-from date | Role, seniority, relationship flags, title |
| `core.transaction` | Form 4 transaction line (all codes) | Accession, issuer, entity, trade date, filing date, code, shares, price, holdings after, gate flags |
| `core.clean_purchase` | Entity × filing | Value, shares, holdings change, role |
| `core.price_series` | Issuer × price source × ticker | Role, first and last session, identity check, chosen, reason |
| `core.price_daily` | Issuer × session (the chosen series) | As-traded OHLC and volume, adjusted close, split factor after the session, source, ticker |
| `core.session` | Trading session (SPY's calendar from 2010) | Session number |
| `core.symbol_map` | Issuer × symbol × date range | Price source, match quality |
| `core.symbol_unmatched` | Issuer without a usable ticker | Reason (`no_ticker`, `fund_like`) |
| `core.company_filing` | Issuer × non-insider filing | Form, filing date, report date, 8-K items (delisting evidence, F15) |
| `core.delisting` | Delisted issuer | Last session, class, venue, delisting return |
| `core.xbrl_fact` | Issuer × concept × period end (first-filed value only) | Concept (shares outstanding, equity, assets, liabilities, cash, net income), value, period end, filed date |
| `core.ff_factor_daily`, `core.ff_industry_daily`, `core.sic_industry`, `core.me_breakpoint`, `core.tick_pilot` | Date × factor; date × industry × weighting; SIC range; month × percentile; ticker × pilot interval | French library and FINRA reference data |
| `core.price_check` / `core.priced_purchase` | Purchase line checked by G8 / entity × filing after G8 | Reference session, range, pass and reason / as `core.clean_purchase`, plus G8 status |
| `evt.prelim_event` / `evt.prelim_event_member` | Preliminary event (Step 5) / its purchases | Group, issuer, T, signal filing, entities, value; entity and role as of T |
| `evt.event_candidate` | Candidate (issuer, group, T) | Outcome (event, unpriced, cooldown, G7, floors), floor inputs |
| `evt.event` / `evt.event_member` | Kept event (priced or unpriced) / its purchases | Group, issuer, T, acceptance time, entry session, G7 SIC and source, floor values, market cap at T |
| `evt.event_cost` | Priced event | Spreads (Abdi–Ranaldo, Corwin–Schultz), tick floor, volatility, ADDV20, impact, round-trip cost |
| `feat.event_features` | Event | F1–F29, feature version |
| `lab.event_label` / `hold.event_label` | Event × horizon × measure | Gross abnormal return, cost, net abnormal return, delisting class |
| `ml.prediction` | Event × run | Split (out-of-fold / holdout / live), probability |
| `audit.funnel` | Quarter × gate | Rows in, rows out |
| `audit.event_funnel`, `audit.price_coverage`, `audit.g8_rate`, `audit.price_issue` | Year × group × outcome; year × group × delisting status; year; provider row | Final-event outcomes, price coverage (SC-001), G8 pass rate (SC-002), price problems |

The product reads a separate file, `data/lookup.duckdb`, built by `sentinel lookup` from an allow-list of SEC-derived tables (`core.filing`, `core.issuer`, `core.transaction`, `core.owner_role`, `core.build_log`, `stg.reportingowner`, `stg.nonderiv_holding`, `stg.footnotes`, `evt.prelim_event`, `evt.prelim_event_member`). Its `lookup.*` tables (`meta`, `issuer_search`, `filing_owner`, `transaction`, `footnote`, `holding`, `event`, `event_member`) hold no market price, so no Yahoo or Tiingo value can reach a page, and the running app never locks the warehouse (feature 005).

### 8.3 Tech stack

Every Python package below was verified to install and import on Python 3.14.4 on 21 October 2026. Exact versions are pinned in `uv.lock`.

| Layer | Choice | Why |
|---|---|---|
| Language and packaging | Python 3.14, **uv** | Fast, reproducible environments with a lockfile |
| Storage and compute | **DuckDB 1.5** + Parquet (pyarrow 25) | A columnar SQL engine in a single file: fast analytical queries over tens of millions of rows, no server, easy to share. Postgres would add operational work with no research benefit |
| Data frames | pandas 3.0 | Interoperates with scikit-learn and statsmodels |
| HTTP | httpx 0.28 | Timeouts and retries; a shared rate limiter enforces the SEC and Tiingo limits |
| Prices | yfinance 1.7 (listed), Tiingo REST API (delisted) | Free for listed stocks; one paid month of Tiingo for delisted ones (§5.2, D39) |
| ML | scikit-learn 1.9, LightGBM 4.7, SHAP 0.54 | Standard, well-documented libraries for the three models, calibration and explanations |
| Statistics | statsmodels 0.15 | Factor regressions, Newey–West standard errors |
| Experiment tracking | MLflow 3.17 (local file store) | Records every run without a server |
| API and UI | FastAPI 0.156 + Jinja2 3.1 templates + HTMX (a small JavaScript file served with the pages) | One small server process; typed, testable endpoints; server-rendered pages with no JavaScript build chain |
| Quality | pytest 9.1, ruff 0.17 | Tests and linting |

### 8.4 Repository layout

```
capstone/
├── config/params.yaml        # every number in Appendix E (pre-registered)
├── docs/initialplan.md       # this specification
├── src/sentinel/
│   ├── ingest/               # SEC bulk, headers + APIs, Yahoo, Tiingo, French library, manifest
│   ├── core/                 # staging, entities, gates, symbols, prices, delisting, shares
│   ├── events/               # event detection (A, B1, B2), floors, cooldown
│   ├── labels/               # returns, benchmarks, costs (dev and guarded holdout)
│   ├── features/             # F1–F29
│   ├── study/                # event study, calendar-time portfolios
│   ├── ml/                   # datasets, CV, models, tournament, evaluation, SHAP
│   ├── api/                  # FastAPI app, templates, static files
│   └── cli.py                # `uv run sentinel <step>`
├── tests/                    # unit, point-in-time, data-quality, golden set
├── reports/                  # generated figures and tables
└── data/                     # git-ignored: raw files, warehouse.duckdb
```

### 8.5 Testing and reproducibility

- **Point-in-time tests:**
  - *Truncation test:* deleting every record after T leaves the events, entities, roles, SIC codes, floor decisions and features at T unchanged.
  - The entry session is after T.
  - Every XBRL value used at T (shares outstanding, equity, assets, liabilities, cash, net income) was first filed on or before T, and no restated value is used.
  - F10 uses only windows that ended before T.
  - No training label window crosses its fold boundary or 31 December 2022.
- **Price tests:**
  - On known reverse-split stocks, price-level rules use unadjusted prices.
  - Every open used as an entry price is positive and lies between the day's low and high.
- **Data-quality tests:**
  - Keys are unique.
  - The funnel reconciles: rows in = rows out + rows removed, per gate.
  - G8 passes for ≥ 95% of mapped clean purchases.
  - Price coverage of A and B1 events is ≥ 90% (§6.7), reported by year and delisting status.
- **Holdout guard tests.** Development code paths cannot read the `hold` schema.
- **Golden set.** 30 events are checked by hand against the original filings on EDGAR (insiders, dates, amounts).
- **Unit tests.** Gates, entity merging and event detection are tested on synthetic fixtures covering edge cases: several filings on one day, cooldown boundaries, joint filers, owners whose roles change.
- **Reproducibility.**
  - Locked dependencies and a single parameter file.
  - A raw-data manifest with hashes, and fixed random seeds.
  - Every model run is linked to a git commit and a data snapshot.
  - **Offline rebuild:** because Tiingo, Yahoo and the French library cannot be re-downloaded identically, reproducibility is defined as follows. A clean clone, plus the archived `data/raw` snapshot (checked against the manifest hashes), regenerates the key tables with no network access. The snapshot is kept private for licensing reasons. Tiingo files are in it only while the paid plan is active, so this check runs before the plan expires; later rebuilds exclude delisted-stock prices and say so (constitution Principle V).

### 8.6 Product v1

**Pages.**
1. **Screener — latest clusters.** For each cluster:
   - signal date, ticker, company, sector;
   - the number of insiders and their roles, total value and holdings increase;
   - the score band (top, middle or bottom fifth; D47), with the hit rate observed for that band in the holdout and a one-line caveat beside it. The calibrated probability appears only on the event page and the model card. If H4 is not confirmed, every score is labelled "no proven skill";
   - a fact line: who bought, how much, the increase in holdings and the distance from the 52-week high;
   - market-cap band, daily dollar volume, filing date, days since filing and sessions left in the 63-day window;
   - the estimated round-trip cost, explained in plain words, and the top three SHAP drivers, in words;
   - links to the filings on EDGAR.

   Filters: date, sector, minimum band, liquidity. A plain-English glossary explains every term (D47).
2. **Stock lookup.** Search by ticker or company to see:
   - every insider transaction — buys, sales, awards, exercises — with transaction codes explained in plain English;
   - holdings over time for each insider;
   - past clusters and their realised outcomes;
   - links to the filings.
3. **Methodology and model card.** The funnel audit, holdout performance, calibration plot, limitations, and a "research, not investment advice" notice.

**API.**
- `GET /api/clusters` (filters: dates, sector, minimum band, liquidity)
- `GET /api/clusters/{event_id}`
- `GET /api/issuers/search?q=`
- `GET /api/issuers/{cik}/transactions`
- `GET /api/funnel`
- `GET /api/model-card`

**Data freshness.** v1 is built from the newest quarterly data set (currently through 30 September 2026). The *Should* item adds daily ingestion of new Form 4 filings from EDGAR, producing the same tables as the bulk data, so the screener stays current.

**Licensing.**
- SEC data is public and can be displayed.
- Tiingo's licence (free and paid plans alike) is for internal use only, and Yahoo's terms restrict redistribution. The product therefore does **not** display raw prices from either; charts come from an embeddable third-party widget licensed for public display.
- Whether model scores derived from these prices may be shown publicly must be checked against the providers' terms before any public launch. The capstone demonstration is private.

---

## 9. Step-by-step plan

### 9.1 The big picture: ten milestones

Each milestone answers one question and feeds the next:

```
 1 COLLECT ───► 2 CLEAN ───► 3 DETECT ───► 4 PRICE ───► 5 LABEL
 What did       Which buys    When did      Could it     What happened
 insiders       are genuine   several       be traded,   next?
 file?          choices?      insiders      and at what
                              buy at once?  cost?
                                                             │
                                                             ▼
 10 SHIP ◄─── 9 FINAL EXAM ◄─── 8 LEARN ◄─── 7 TEST ◄─── 6 DESCRIBE
 Can anyone    Does it hold on    Can ML rank    Does the     What was
 use it?       data it has        clusters?      signal       known at
               never seen?                       exist?       the time?
```

### 9.2 The steps

Each step lists what is done, what it produces, and how we know it is finished.
- **Phase 0** (Step 0) is set-up.
- **Phase 1** (Steps 1–6) builds the data foundation.
- **Phase 2** (Steps 7–12) adds prices, labels and features.
- **Phase 3** (Steps 13–17) is the analysis.
- **Phase 4** (Steps 18–21) evaluates the holdout and ships.

The product's lookup page runs as a parallel track from Week 2, because it needs only the core tables.

**Phase 0 — Set-up (Days 1–2)**

| Step | What we do | Output | Done when |
|---|---|---|---|
| 0 | Create the repository structure, environment and parameter file. Set the SEC `User-Agent` with a real contact. Obtain a Tiingo key. Rebuild the pilot's list of delisted A and B1 companies from the SEC data (`sentinel candidates-provisional`). Commit this draft | Runnable skeleton; provisional delisted-candidate list | `uv run sentinel --help` works; candidate list ready |

**Phase 1 — Insider data foundation (Week 1)**

| Step | What we do | Output | Done when |
|---|---|---|---|
| 1 | Download all 83 quarterly data sets, from both SEC folder layouts | `data/raw/sec/` + manifest | 83 files with hashes |
| 2 | Load into typed staging tables, handling column changes over the years (e.g., the 10b5-1 checkbox field exists only in the 2023-onward files) | `stg.*` | Row counts match the source files; schema-drift report |
| 3 | Build point-in-time entities and roles (§6.3) | `core.entity_member` | Truncation test passes; hand check of 50 random entities |
| 4 | Apply gates G1–G6. Keep all transaction types, for the product and the features | `core.transaction`, `core.clean_purchase`, `audit.funnel` | Funnel reconciles; hand check of 50 excluded and 50 kept rows |
| 5 | Preliminary event detection (A, B1, B2), used to choose which symbols to price | Candidate events | Unit tests pass |
| 6 | Map issuers to price symbols: SEC's ticker file for active companies, Form 4 symbol history for delisted ones. Start the background fetch of signal-filing headers (SIC at T, acceptance time). Look up delisted companies' final Tiingo tickers (often a bankruptcy `Q` ticker on an OTC venue). **Fix the start of the labelled window (§5.2)** | `core.symbol_map`; labelled-window decision | Window recorded in §12 |

**Phase 2 — Prices, labels, features (Week 2)**

| Step | What we do | Output | Done when |
|---|---|---|---|
| 7 | Fetch prices: Yahoo for listed stocks, SPY and IWM (with unadjusted prices rebuilt from split histories); Tiingo for delisted stocks (the one-month Power plan starts that day, D39). Download the factor, industry and breakpoint files. Run G8; run final event detection with G7, the floors and the cooldown | `core.price_daily`, reference tables, `evt.event` | Price tests pass; coverage report (target ≥ 90%); 30-event golden set matches EDGAR |
| 8 | Classify delistings (acquired / performance-related / unknown) and assign delisting returns | `core.delisting` | Hand check of 30 companies across all three classes |
| 9 | Load shares outstanding and the five F26–F29 items from XBRL company facts (first-filed values only) | `core.xbrl_fact` | Market caps and book values match known examples; coverage report per item |
| 10 | Estimate spreads and costs | Cost estimates | Plot of estimated cost by price bucket |
| 10a | **Lock the pre-registration**: tag `prereg-v1`, push it, and publish it as a GitHub Release (D48) | Locked parameters | Tag and release on GitHub before Step 11 starts |
| 11 | Compute development labels: 5 horizons × 4 measures, gross and net, with delisting handling — windows ending by 31 December 2022 only | `lab.event_label` | Point-in-time tests pass; 10 events recomputed by hand |
| 12 | Compute features F1–F29 as of T (F10 from development windows only) | `feat.event_features` | Point-in-time tests pass; missing-value report |
| P | *Parallel track:* stock lookup page and its API endpoints on the core tables | Working lookup page | Endpoint tests pass |

**Phase 3 — Analysis (Week 3)**

| Step | What we do | Output | Done when |
|---|---|---|---|
| 13 | Event study on the development period (H1–H3) | Return paths, BHAR tables, calendar-time alphas | Results written up *before* any ML result exists |
| 14 | Build the ML dataset: folds, three-way splits, purging, weights | Versioned dataset; post-floor counts per fold | Leakage tests pass; fold-size rule applied |
| 15 | Fit and score the six baselines | Baseline metrics | Logged in MLflow |
| 16 | Run the tournament (25 configurations) with tuning and calibration slices | Out-of-fold metrics; selected model | Selection follows the one-standard-error rule |
| 17 | SHAP explanations and error analysis | Figures; driver tables | Reviewed for implausible drivers (a smell test for leakage) |

**Phase 4 — Final evaluation and delivery (Week 4)**

| Step | What we do | Output | Done when |
|---|---|---|---|
| 18 | **Guarded holdout job:** compute holdout labels and F10 outcomes in the `hold` schema; fit the holdout model by the same recipe; evaluate once (H4, H5; H1–H3 replications; the checkbox-off variant) | Holdout report | Guard log shows a single run |
| 19 | Refit the production model; score the latest clusters; finish the screener and the model card | Running application | All endpoints tested; demo script |
| 20 | Robustness: the pre-listed sensitivity variants (Appendix E), on the development period only | Sensitivity tables | Every listed variant run once; any holdout sensitivity is labelled exploratory |
| 21 | Final report and presentation; offline rebuild check before the Tiingo plan expires; then delete all Tiingo data and log it | Report, slides, tagged release | Clean clone + raw snapshot regenerates the key tables offline; Tiingo deletion logged in §12 |

### 9.3 Calendar, checkpoints and cut order

| Week | Dates (2026) | Steps | Checkpoint at the end of the week |
|---|---|---|---|
| 1 | 22–28 Oct | 0–6 | Event counts known; delisted-candidate list ready; start of the labelled window decided (§5.2) |
| 2 | 29 Oct – 4 Nov | 7–12, P | Tiingo month started with the price pull; price coverage reported (target ≥ 90%); pre-registration locked; development labels and features pass point-in-time tests; lookup page working |
| 3 | 5–11 Nov | 13–17 | Event-study results frozen; model selected |
| 4 | 12–18 Nov | 18–21 | Holdout evaluated; product demo; report submitted |

**Critical path: Step 0 → Step 6 → Step 7.** Delisted-stock prices gate everything downstream, so the delisted-candidate list is built in Week 1 and the Tiingo pull starts at the beginning of Week 2, on the first day of the paid month.

**Pre-registered cut order.** If Week 2 slips by more than two days, the following are dropped in this order:
1. Daily EDGAR ingestion.
2. Comparison group B2.
3. The SHAP panel in the product (the SHAP analysis itself stays).
4. The non-primary horizons (126 and 252 days).

The ML core is never cut.

---

## 10. Risks and mitigations

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | The free Tiingo plan cannot be used: its terms forbid storing data | **Confirmed** (ToS §1.6(a)) | One month of Tiingo Power (D39); bounds for unpriced events (§6.7) |
| R2 | The paid month ends before the work that needs Tiingo data is finished | Low / High | Subscribe on the day of the pull (about 29 Oct, so it runs to about 28 Nov); finish labels and the offline rebuild first; a second month would need a constitution amendment |
| R3 | Wrong ticker matches (ticker changes and reuse) | Medium / High | CIK-based symbol history; date-overlap checks; G8; hand audit |
| R4 | `yfinance` breaks or is rate-limited (unofficial API) | Medium / Medium | Cache every response; retries with back-off. The Tiingo month is reserved for delisted stocks (D39), so a long outage slips the schedule |
| R5 | Footnote filters miss plan or offering trades (mainly before 2023), or over-exclude | Medium / Medium | Hand audit to estimate precision; results re-run with the filters off (on the default event set) |
| R6 | Effective sample is small; results driven by one or two crises | Medium / High | Time-robust inference; concurrency weights; calendar-time portfolios; sub-period results; power stated in advance (§3.3) |
| R7 | Overfitting through repeated experimentation | Medium / High | Locked, time-stamped pre-registration; sealed holdout; small grids; one-standard-error rule; trial count; deflated Sharpe ratio |
| R8 | No signal found | Medium / Low for the capstone | Framed as a valid result; methods, pipeline and product still delivered |
| R9 | Schedule overrun | High / Medium | Pre-registered cut order (§9.3); lookup page built early; ML protected |
| R10 | Data licensing blocks a public launch | High / Low for the capstone | No raw price redistribution; terms reviewed before any launch |
| R11 | Slow SEC responses (about 1–2 requests per second in the pilot) | High / Low | Background jobs, caching, early start |

---

## 11. Known limitations

- **Our data is not CRSP.** Delisting returns are approximations, and some events cannot be priced. Their share is reported and bounded (§6.7).
- **The 2008–09 crisis is outside the labelled window**, which starts in 2012 (§5.2, D42). Including it would need a substitute for XBRL share counts, which are incomplete before mid-2011.
- **Industry fallback.** If a signal filing's header cannot be fetched, the issuer's current SIC code is used and flagged.
- **Companies with several share classes** are mapped to their primary listed class.
- **Plan and offering detection before 2023 depends on voluntary footnotes** and will miss some trades. The holdout is evaluated both with and without the checkbox gate (§7.2).
- **Trading costs are estimated, not observed.** The capacity of any strategy built on micro-caps is small.
- **Company financials can be missing or tagged unusually** where a company's filings lack the cover-page shares tag or the standard balance-sheet tags. Dollar volume stands in for size; the other items get missing-value indicators (F16, F25–F29).
- **Prior knowledge.** The pilot saw holdout-period counts (no returns), and the author knows the broad market history of 2023–26.
- **External validity.** The results cover US stocks from 2012 to 2026, under the two-day reporting rule. They may not carry over to other markets or periods.
- **No causal claims.** SHAP explains the model's behaviour, not why prices move.

---

## 12. Decision log

Every significant choice, what else was considered, and why. "v1" refers to the first draft (Appendix D).

| # | Decision | Alternatives considered | Reasoning |
|---|---|---|---|
| D1 | Research result first, product second | A product-first screener | A screener is only as good as the evidence behind its scores |
| D2 | Ingest insider data for 2006 Q1 – 2026 Q3 (83 quarters); study returns for events from 2016 (changed to 2012 by D42) | v1: insider data and returns from 2011 Q1 (63 quarters). Returns from 2006 (~2,000 delisted symbols) | Insider history from 2006 feeds the features. The return window follows the pre-registered budget rule (§5.2), and free coverage of older delistings is also weaker (18% of companies unmatched for a 2006 start vs 8% for 2016). Cost: the 2008–09 crisis drops out. This is accepted for the course version; a later version with a paid subscription can restore it |
| D3 | All sectors, none treated specially | Biotech only; semiconductors only | Pilot: about 1 semiconductor cluster per quarter (about 80 in 20 years) — too few. Single-sector samples are dominated by single episodes (bank clusters jumped from 17 to 77 in the 2023 banking stress). Sector is a feature and a breakdown |
| D4 | Micro-caps included | Exclude stocks below $5 | Insider signals are strongest in small firms (Lakonishok & Lee, 2001); floors and costs handle tradability |
| D5 | $2 floor on the unadjusted price | $1; $5; adjusted prices | Tick-size cost floor, listing-compliance zone, the cost of a $5 filter (§6.5). Adjusted prices would select on future reverse splits |
| D6 | ADDV20 ≥ $100k; 18/20 active sessions | No floor; other levels | Derived from position size and share of daily volume (§6.5) |
| D7 | $10k standard position (owner's decision) | $25k; $50k | A small retail position, matching the product's audience. The floor and the cost model scale with it: $25k → $250k floor; $50k → $500k floor. The larger sizes are sensitivity checks that show how quickly any edge shrinks as positions grow (Appendix E) |
| D8 | Entry at the T+1 open | Close of T; entry based on acceptance time | Regulation S-T Rule 13(a)(4); the Prothena example (§6.1) |
| D9 | Cluster: ≥ 2 entities, including an officer or director; 14 days; ≥ $100k | v1: 2 owners, 14 days, $100k | Adds entity merging and the officer/director condition (§6.3–§6.4) |
| D10 | Cooldown of 63 sessions per issuer per group | v1: 21 calendar days | Prevents overlapping labels for the same stock; costs about 13% of clusters (full pilot) |
| D11 | Merge joint filers into entities, point-in-time | Count reporting owners; merge using all filings | 14–16% of pilot filings had several owners. Merging with later filings would make an event's existence depend on the future |
| D12 | Original Form 4 only, filed within 30 days of the trade | Include 4/A and Form 5; no timeliness rule | Avoids double counting and stale trades |
| D13 | Exclude plan trades via the checkbox (per filing) and transaction-level footnotes | v1: scan every footnote in the filing | Avoids discarding a clean purchase because another line's footnote mentions a plan |
| D14 | Exclude participation in company offerings | Keep them | Code P includes private purchases from the company (§6.2) |
| D15 | Exclude SPACs and funds, using the SIC at T from filing headers | Today's SIC | Today's codes would drop companies that only later became shells, and keep SPACs that later merged |
| D16 | Keep all transaction types | v1: purchases only | Needed for the product lookup and the selling features |
| D17 | B1 confirmatory, B2 exploratory unless priced; no matched control | A matched "no insider buying" control | A matched control needs prices for every listed stock — impossible on free data in 4 weeks. Industry and factor adjustment, plus the market-only baseline, cover most of its purpose |
| D18 | Horizons 5–252 days; primary 63 | v1: 60 days only | §6.6 |
| D19 | Measures: SPY, IWM, equal-weighted industry (primary), FF5 + UMD | v1: IWM only; sector ETFs; QQQ | §6.6 |
| D20 | Label: industry-adjusted 63-day BHAR net of the trade's own cost > 0 | v1: +5% vs IWM | §6.6 |
| D21 | Three delisting classes, plus bounds for delisting returns and for unpriced events | Drop delisted events; treat every price gap as a failure | §6.7. Data gaps are not failures |
| D22 | Free data: Yahoo for listed stocks, Tiingo for delisted ones (superseded for Tiingo by D39) | Paid data; Yahoo only | Owner preference; survivorship bias (§5.1) |
| D23 | Only shares outstanding from XBRL (extended by D43) | v1: full point-in-time fundamentals | Handling restated values is the biggest engineering risk; market cap is the essential piece |
| D24 | No macroeconomic features | v1: VIX, yield curve, credit spreads, Fed funds rate | One or two crises in the training data, so the model could memorise them; analysed in the error analysis instead |
| D25 | ML trained on clusters only | Pool clusters and solo events | The research question concerns clusters; pooling adds overlapping windows from the same issuer. About 5,800 development clusters before floors (Appendix A.3) |
| D26 | Three models plus an ensemble | One model; deep learning | Covers the linear, bagged and boosted families. Neural networks add little on a few thousand rows of tabular data |
| D27 | Purged expanding walk-forward; holdout fixed at 1 Jan 2023 – 1 Jun 2026 | Random K-fold; a holdout end that moves with data updates | Time order must be respected; the holdout must not move after the fact |
| D28 | Calendar-concurrency weights | Unweighted; 1 ÷ events per month | Smoothly down-weights crowded periods without arbitrary month boundaries. Unweighted results are reported as a sensitivity |
| D29 | Three-way split inside each training window; calibration on a slice the refitted model has never seen | v1: `CalibratedClassifierCV` with random 3-fold splits; one slice for everything | v1 leaked future data into calibration; one slice reused for tuning and calibration is optimistic |
| D30 | Selection by log loss with the one-standard-error rule | Best mean log loss; AUC; Sharpe ratio | A proper scoring rule. With four folds, small differences are noise, so prefer the simpler model |
| D31 | Baselines include a market-only model and a cost-only ranking | Only naive baselines | Isolates the value of the insider information, and the share of "skill" that is really cost prediction |
| D32 | Time-robust inference on monthly series; Holm–Bonferroni over five primary tests | Standard errors clustered by month; no correction | Overlapping windows make neighbouring months dependent; five tests need family-wise control |
| D33 | Buy-and-hold calendar-time portfolios with Dimson lags | Daily-rebalanced equal weights | Daily rebalancing of micro-caps inflates returns through bid–ask bounce; thin trading understates betas |
| D34 | Sealed holdout: labels computed only in a guarded job | Compute all labels up front | Once holdout returns exist in development tables, a guard protects nothing |
| D35 | DuckDB + Parquet | v1: PostgreSQL | §8.3 |
| D36 | FastAPI + server-rendered pages; a third-party chart widget | React front end; Streamlit | The smallest stack that serves both API and pages, and avoids redistributing price data |
| D37 | MLflow tracking | Ad-hoc logs | Every run reproducible; the trial count feeds the deflated Sharpe ratio |
| D38 | Pre-registration locked after review, pushed, and the hash emailed | Tag on Day 1; local tag only | Review changes are not counted as deviations; a pushed tag plus an emailed hash is verifiable |
| D39 | One month of Tiingo Power ($30) for delisted prices (decided 2026-10-22); the project finishes within that month, Tiingo data is deleted when the plan ends, and the Step 21 offline rebuild runs before then | Free Starter plan; free plan with in-memory processing only; drop delisted stocks | Tiingo's Starter terms (ToS §1.6(a), updated 2026-10-06) forbid storing its data, and in-memory processing cannot fit a rebuild into the 500-symbol and 50-request limits. Dropping delisted stocks would bring back survivorship bias (§5.1). A paid plan allows storage while it is active (§1.6(b)). Requires amending constitution Principle VI ("free sources only") |
| D40 | The §5.2 budget rule no longer binds; the provisional candidate list covers 2006 onward; the labelled-window start is revisited on research grounds before `prereg-v1` | Keep 2016 because of the free budget | With Power's 110,346 symbols a month, all ~2,200 matched delisted companies can be priced. A 2016 start was forced only by the free budget |
| D41 | New dependencies typer (CLI), python-dotenv (`.env`) and respx (test-only HTTP mocks); DuckDB pinned below 2 | argparse; a hand-written `.env` parser; live HTTP in tests; DuckDB 2.0 | Help grouped by phase; standard secret loading; offline tests (FR-007). DuckDB 2.0.0 was released on 2026-10-21, too new to adopt mid-project |
| D42 | The labelled window starts on 1 January 2012 (decided 2026-10-22) | 2016 (the free-budget default); 2011; 2009; 2006 | Owner's rule: start where every data source is complete without workarounds — a course project, not an institutional tool. XBRL share counts (D23) cover all filers only from mid-2011 (Release 33-9002); the other sources cover the whole period. Development events 11,470 against 7,675 for 2016 (+49%); delisted match rate 79% against 83% |
| D43 | Add F25–F29: purchase value ÷ market cap, book-to-market, loss flag, leverage, cash ÷ assets (decided 2026-10-22) | Insider and market features only (D23); full XBRL fundamentals | Owner's request to consider company financials and purchase size relative to the company. The items come from the same company facts file already fetched for share counts, with the same first-filed rule, so the look-ahead risk that motivated D23 is contained. Revenue and quarterly earnings sums are left out because their tags vary too much. The market-only baseline gains F26–F29 so it still isolates the insider information |
| D44 | Build an MVP prototype first (feature 003, in `mvp/`), before the insider warehouse: real SEC data, Yahoo prices for listed stocks only, a simple model and a dashboard, with returns computed only for a pre-2012 pilot sample (decided 2026-10-22) | Placeholder findings; lock the pre-registration first; buy Tiingo now | A demo for the teachers early. Pre-2012 events are outside both the development period and the holdout, so the confirmatory tests stay clean; outputs are labelled "survivors only, prototype". Governed by the constitution's Prototype Exception (v3.0.0). Anything the pilot teaches that changes the design is logged here before `prereg-v1` |
| D45 | G7 also excludes issuers whose signal-filing header carries no SIC code (decided 2026-10-23). A 30-event check across 2012–2026 is made before the lock; if 3 or more of the 30 are operating companies, issuers without a header SIC take the current-SIC fallback (§11) instead of being excluded | Exclude only SIC 6770, 6722, 6726 | In the MVP's July–September 2026 events, 27 events were at funds, BDCs or blank-check companies, but only 1 had one of those codes: EDGAR leaves almost all funds and BDCs uncoded (specs/003-mvp-dashboard/run-notes.md, M5). Such issuers also have no industry benchmark for the primary label |
| D46 | Raise the G6 minimum from $10,000 to $25,000 per entity per filing; sensitivities $10k and $50k (decided 2026-10-23) | Keep $10k (sensitivities $5k; $25k); $50k; count only buyers of ≥ $25k toward a cluster's two entities while keeping $10k for G6 | Owner's view: $10k is retail-sized money. The event minimum ($100k) already stops any event resting on a small purchase, but at $10k a token buy could still count as a cluster's second, independent buyer. Measured on purchase sizes only (no returns), in feature 001's provisional events for 2006–2026: 23% of clean filings are $10–25k, and the higher floor removes about 15% of clusters (12% lose their second buyer, 3% fall below $100k). A $50k floor would remove 35%, and a $100k floor 59%. A fixed dollar floor also ignores company size, which features F7, F18 and F25 measure. The provisional outputs of feature 001, built at $10k, are kept as they are: their candidate list is a superset of what $25k needs. `provisional.filing_min_value` keeps the pilot's $10k, so feature 001 still rebuilds them and the comparison (feature 002) can isolate this change |
| D47 | Product v1 shows each cluster's score as a band: top fifth, middle three fifths or bottom fifth of the model's calibration-slice predictions (the top fifth is H5's model portfolio), with the band's holdout hit rate and count and a one-line caveat beside it, plus a plain fact line. The calibrated probability appears only on the event page and the model card. If H4 is not confirmed, every score is labelled "no proven skill" and the screener sorts by filing date by default (decided 2026-10-23) | Show the calibrated probability in lists (§8.6 before this decision) | Synthetic user research on the MVP (23 Oct 2026; docs/planning/06): a precise "97%" from a near-chance model was misread as a chance of profit, or undermined trust, in 4 of 5 personas. Bands carry only what the evidence supports, and the rule is fixed before the holdout so the display cannot be chosen after seeing the result. The research design is unchanged |
| D48 | Record `prereg-v1` with a GitHub Release of the tag instead of emailing the commit hash; there is no external review (decided 2026-10-23; constitution v3.1.0) | Email the hash to a supervisor (D38) | There is no supervisor to email. GitHub records a release's creation time on its own servers, so the lock stays independently time-stamped, and the tag and its commit are public |
| D49 | Feature 002 design choices (decided 2026-10-22): the gate keyword lists and the preliminary cooldown move to a `rules` section of `params.yaml`, locked by `prereg-v1`; preliminary events carry no price filter; filing headers are fetched only for signal filings from 2012 | Keep the lists in `provisional`; apply feature 001's $2 stand-in; fetch headers for every event | Research rules must be locked like the Appendix E numbers. Price floors use market prices (Step 7), so the preliminary set is a superset, which is right for choosing what to price. G7 applies to labelled and holdout events only |
| D50 | Delistings from venues other than NYSE, NYSE American and Nasdaq (for example OTC), or from an unknown venue, take the Nasdaq delisting return, −55% (decided 2026-10-23, feature 004) | −30% (the NYSE value); exclude such events | §6.7 gives returns only for the three exchanges, but many delisted micro-caps end on OTC venues under a bankruptcy `Q` ticker. −55% is the more conservative of the two registered values, and the 0% and −100% bounds still apply. Registered as `delisting_returns.other_venue_treated_as` |
| D51 | Feature 004 design choices (decided 2026-10-23): final detection runs from 1 July 2011, a six-month warm-up before the labelled window whose events are never labelled, with prices from 1 January 2010; events at companies that cannot be priced are kept, counted and start a cooldown; G8 is applied to each purchase line and the G6 minimum is then re-applied; a Tiingo series is accepted only if its dates and company name match the SEC company; a header SIC of "0000" (EDGAR's code for none assigned) counts as no SIC under D45 | Detect from 2006; drop unpriced events; apply G8 per filing; trust Tiingo's ticker | Signal-filing headers (G7's SIC at T) exist only from the labelled window, and no feature uses earlier events. Unpriced events must be counted like priced ones for the bounds (§6.7). G8 checks the reported price, which lives on the line. About 10% of delisted companies resolve to a reused Tiingo ticker (specs/004-market-data-events/research.md R1, R3, R6, R7) |
| D52 | G8 runs only on purchase lines traded on or after `rules.price_history_start` (1 January 2010); earlier lines skip it, as lines at unpriced issuers do. Purchases whose reported price fails G8 because the insiders bought a different share class than the priced one, or reported per ordinary share for an ADR, are accepted as G8 failures and documented. SC-002 (G8 ≥ 95%) is re-measured after the Tiingo pull (agreed 2026-10-24, feature 004) | Count pre-2010 lines as failures; choose the share class from the security title | No prices are fetched before 2010, and those lines cannot reach a final candidate, which are detected from 1 July 2011; counting them put the rate at 73.4% instead of 93.8%. Share-class mapping would recover at most 515 of the 6,687 out-of-range lines since 2012 (+0.3 points), and ADR ratios are not in the free data. Most remaining failures (4,972) are trades before an issuer's Yahoo history starts, which the Tiingo fallback covers (specs/004-market-data-events/run-notes.md, T036) |

---

## Appendix A — Pilot evidence from real SEC data

Before this plan was finalised, simplified versions of the gates were run on two real quarters and on the full 2006–2026 history. These numbers come from a pilot. The production pipeline adds point-in-time entity merging, the officer/director condition, the issuer-type rule, the timeliness rule and the market-price floors. **The pilot looked at counts and purchase sizes only, never at returns.**

### A.1 Two-quarter funnel

| Measure | 2019 Q1 | 2023 Q1 |
|---|---|---|
| Purchase lines (code P, shares acquired) | 12,796 | 6,539 |
| — on an original Form 4 | 11,938 (93%) | 6,015 (92%) |
| — common stock | 12,385 (97%) | 6,240 (95%) |
| — flagged by plan footnotes (10b5-1, dividend reinvestment, employee purchase plans) | 5,009 (39%) | 957 (15%) |
| — flagged by offering footnotes | 107 (0.8%) | 118 (1.8%) |
| — 10b5-1 checkbox ticked | field absent | 8 |
| Insider filings passing G1–G5 | 3,023 | 2,773 |
| — of which below $10k: share of filings / share of dollars | 39% / < 0.1% | 25% / < 0.1% |
| Clean insider filings after all pilot gates | 1,632 | 1,864 |
| — filed jointly by several owners | 228 (14%) | 290 (16%) |
| Clean purchase size: 25th percentile / median / 75th / 90th | $27k / $75k / $281k / $1.9M | $31k / $80k / $282k / $1.4M |
| Clusters (21-day cooldown → 91-calendar-day cooldown, ≈ 63 sessions) | 154 → 150 | 221 → 204 |
| Cluster size: 2 / 3 / ≥ 4 entities | 66% / 17% / 17% | 66% / 19% / 15% |
| Solo CEO/CFO purchases ≥ $100k | 71 | 94 |
| Distinct cluster ticker symbols as reported (blank counted once): active / delisted / not found in Tiingo's list | 78 / 32 / 33 | 151 / 25 / 17 |

**Notes.**
- The pilot used the transaction price (≥ $2) as a stand-in for the market-price floor.
- The 2023 Q1 checkbox count is small because the checkbox became mandatory only for filings from 1 April 2023.
- The single-quarter cooldown comparison understates the cooldown's cost, because no cluster can be blocked by one in the previous quarter. Across the full history the cost is about 13% (A.3).

### A.2 Sector mix of pilot clusters (looser filter, before the footnote gates)

| Sector | 2019 Q1 | 2023 Q1 |
|---|---|---|
| Banks | 17 | 77 |
| Biotech and pharma | 29 | 22 |
| REITs | 9 | 19 |
| Other financials | 16 | 16 |
| Oil and gas | 9 | 10 |
| Software and computers | 5 | 10 |
| Medical devices and labs | 5 | 7 |
| Semiconductors | 1 | 1 |
| Other or unknown | 95 | 102 |
| **Total** | **186** | **264** |

The jump in bank clusters in 2023 Q1 coincides with the regional-bank stress of March 2023 — an example of events bunching in time, and of why a single-sector study would really be a study of one episode.

### A.3 Full-history scan (2006 Q1 – 2026 Q3)

The same simplified gates were run on all 83 quarterly data sets, producing 189,582 clean insider filings at 10,249 companies. Events were detected across quarter boundaries with a 91-calendar-day cooldown (≈ 63 sessions). A 21-day cooldown would have given 19,300 clusters instead of 16,676: about 13% more.

| Year | Clusters (A) | Solo CEO/CFO ≥ $100k (B1) |
|---|---|---|
| 2006 | 853 | 240 |
| 2007 | 1,260 | 279 |
| 2008 | 1,329 | 307 |
| 2009 | 646 | 181 |
| 2010 | 549 | 175 |
| 2011 | 871 | 263 |
| 2012 | 624 | 176 |
| 2013 | 572 | 175 |
| 2014 | 751 | 269 |
| 2015 | 913 | 309 |
| 2016 | 718 | 226 |
| 2017 | 669 | 237 |
| 2018 | 867 | 251 |
| 2019 | 792 | 277 |
| 2020 | 1,080 | 284 |
| 2021 | 825 | 278 |
| 2022 | 834 | 301 |
| 2023 | 739 | 259 |
| 2024 | 562 | 233 |
| 2025 | 698 | 290 |
| 2026 (Q1–Q3) | 524 | 218 |
| **Total** | **16,676** | **5,228** |

**Observations.**
- Clusters peak in the 2007–08 financial crisis and in 2020 (the COVID-19 crash). Insiders buy into sharp declines, and events bunch in time — the reason for time-robust inference and concurrency weights.
- The development period (2012–2022) holds about 8,600 clusters (2016–2022: about 5,800), and the holdout (2023 – 2026 Q3) about 2,500, of which about 2,300 have signal dates by 1 June 2026. These are counts before the production rules and the market-price floors.
- The price-coverage counts by start year are in §5.2.

### A.4 Filing headers

The header of a real Form 4 (Prothena, filed 31 March 2023) shows both facts the design relies on:
- an acceptance time of 21:31 ET, after the market close — the reason for T+1 entry;
- the issuer's SIC code at the time of filing — the basis for point-in-time industry codes.

---

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| Abnormal return | A stock's return minus the return of the benchmark it is compared with |
| ADDV20 | Average daily dollar volume (price × shares traded) over the last 20 sessions; a liquidity measure |
| Alpha | The intercept of a factor regression: the average return not explained by the factors |
| Base rate | The share of positive labels in the training data |
| BHAR | Buy-and-hold abnormal return: the compounded stock return minus the compounded benchmark return over the same window |
| Bid–ask spread | The gap between the price buyers pay and the price sellers receive; a cost of every round trip |
| Bootstrap (moving-block) | Resampling consecutive blocks of time so that dependence between neighbouring periods is preserved |
| Brier score / skill score | Mean squared error of probability forecasts (lower is better) / its improvement over always predicting the base rate |
| Calendar-time portfolio | A daily portfolio holding every event currently in its window; its alpha measures abnormal performance while accounting for overlapping events |
| Calibration | Whether predicted probabilities match observed frequencies (events scored 0.6 should succeed about 60% of the time) |
| CAR / CAAR | Cumulative abnormal return for one event / its average across events |
| CIK | The SEC's permanent identifier for a company or person |
| Cluster | ≥ 2 insider entities, including an officer or director, buying ≥ $100k within 14 days (§6.4) |
| Concurrency weights | Sample weights that lower the influence of events whose label windows overlap with many others |
| Cooldown | The period after an event during which the same issuer cannot produce another event in the same group |
| Deflated Sharpe ratio | A Sharpe ratio adjusted for the number of strategies tried and for non-normal returns (Bailey & López de Prado, 2014) |
| Delisting return | The return assigned to a stock's final move when it leaves the exchange (§6.7) |
| Diebold–Mariano test | A test of whether one forecast's losses are significantly lower than another's on the same events |
| Dimson lags | Adding lagged factor returns to a regression so that betas of thinly traded stocks are not understated |
| Early stopping | Choosing the number of boosting rounds by performance on held-out data |
| EDGAR | The SEC's electronic filing system |
| Effective sample size | The number of independent observations that would give the same precision as the actual, correlated sample |
| Elastic net | A penalised regression combining L1 (lasso) and L2 (ridge) penalties |
| Embargo | An extra gap after a test period, needed when training data may come after test data; unnecessary here |
| Entity | One economic decision-maker, after merging reporting owners who file jointly (§6.3) |
| Equal- vs value-weighted | Each position gets the same weight vs a weight proportional to its market value |
| Event study | Measuring average returns around a type of event, relative to a benchmark |
| Excess return | Return minus the risk-free rate |
| Expanding window | Each training set includes all data up to its fold boundary |
| FF5 + UMD | The Fama–French five factors (market, size, value, profitability, investment) plus momentum |
| Form 4 / Form 25 / Form 15 | Insider trade report / notice of delisting from an exchange / notice ending SEC registration |
| Gradient boosting (LightGBM) | An ensemble of small decision trees, each fitted to the errors of the previous ones |
| Holdout | Data set aside and used exactly once, at the end, to measure true out-of-sample performance |
| Holm–Bonferroni | A step-down correction that controls the chance of any false positive across several tests |
| Information hierarchy | Seyhun's (1986) finding that officers and directors trade on better information than large outside shareholders |
| Log loss | The negative mean log-likelihood of the observed outcomes under the predicted probabilities |
| Look-ahead bias | Using information in a backtest before it was available in reality |
| Market impact | The price move caused by one's own order |
| Maximum drawdown | The largest peak-to-trough fall in a portfolio's value |
| Micro-cap | A very small listed company; here, below the 20th percentile of NYSE market capitalisation (Fama & French, 2008) |
| Momentum / short-term reversal | Stocks that rose over the past year tend to keep rising / stocks that fell over the past month tend to bounce back |
| MoSCoW | Prioritisation into Must, Should, Could and Won't |
| Newey–West | Standard errors robust to autocorrelation and heteroskedasticity |
| Out-of-fold | Predictions made for data that the model was not trained on |
| PIPE | Private investment in public equity: a company selling shares directly to selected investors |
| Platt scaling | Calibrating scores by fitting a logistic curve that maps them to probabilities |
| Point-in-time (PIT) | Using data exactly as it was known on a given date |
| Pre-registration | Fixing hypotheses, tests and parameters publicly before seeing results |
| Proper scoring rule | A score that is optimised by reporting one's true probability (log loss and the Brier score are examples) |
| Purging | Removing training observations whose label windows overlap the test period |
| Random forest | An average of many decision trees, each fitted to a random sample of the rows and the features |
| Rank IC | Information coefficient: the rank correlation between predictions and realised outcomes |
| ROC-AUC | The probability that a randomly chosen positive is scored above a randomly chosen negative |
| Routine / opportunistic trader | An insider who trades in the same calendar month every year / every other insider (Cohen et al., 2012) |
| Section 16 insider | An officer, a director, or an owner of more than 10% of a registered class of equity |
| Session; T+1 | A trading day; the first session after the signal date T |
| Sharpe ratio | Average excess return divided by its standard deviation |
| SHAP / TreeSHAP | Shapley-value explanations of individual predictions (Lundberg & Lee, 2017) / their exact, fast version for tree models |
| Shrinkage | Pulling an estimate from a small sample toward a broader average |
| SIC | Standard Industrial Classification code |
| SPAC | Special purpose acquisition company: a listed shell that raises cash to buy a private company |
| Survivorship bias | Distortion from studying only entities that still exist |
| Tercile | One of three equal-sized groups |
| 10b5-1 plan | A pre-arranged trading plan under SEC Rule 10b5-1 |
| Tick | The minimum quoting increment: $0.01 for US stocks priced at $1 or more, and $0.05 for Tick Size Pilot stocks in 2016–2018 |
| Walk-forward validation | Repeatedly training on the past and testing on the next period |
| Winsorise | Cap extreme values at chosen percentiles |
| XBRL | The machine-readable tagging format of SEC financial statements |

---

## Appendix C — References

### Academic

- Abdi, F., & Ranaldo, A. (2017). A simple estimation of bid-ask spreads from daily close, high, and low prices. *Review of Financial Studies, 30*(12), 4437–4480.
- Almgren, R., Thum, C., Hauptmann, E., & Li, H. (2005). Direct estimation of equity market impact. *Risk, 18*, 57–62.
- Bailey, D. H., & López de Prado, M. (2014). The deflated Sharpe ratio: Correcting for selection bias, backtest overfitting, and non-normality. *Journal of Portfolio Management, 40*(5), 94–107.
- Banz, R. W. (1981). The relationship between return and market value of common stocks. *Journal of Financial Economics, 9*(1), 3–18.
- Banz, R. W., & Breen, W. J. (1986). Sample-dependent results using accounting and market data: Some evidence. *Journal of Finance, 41*(4), 779–793.
- Barber, B. M., & Lyon, J. D. (1997). Detecting long-run abnormal stock returns: The empirical power and specification of test statistics. *Journal of Financial Economics, 43*(3), 341–372.
- Bettis, J. C., Coles, J. L., & Lemmon, M. L. (2000). Corporate policies restricting trading by insiders. *Journal of Financial Economics, 57*(2), 191–220.
- Blume, M. E., & Stambaugh, R. F. (1983). Biases in computed returns: An application to the size effect. *Journal of Financial Economics, 12*(3), 387–404.
- Breiman, L. (2001). Random forests. *Machine Learning, 45*(1), 5–32.
- Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. *Monthly Weather Review, 78*(1), 1–3.
- Brochet, F. (2010). Information content of insider trades before and after the Sarbanes-Oxley Act. *The Accounting Review, 85*(2), 419–446.
- Brown, S. J., Goetzmann, W., Ibbotson, R. G., & Ross, S. A. (1992). Survivorship bias in performance studies. *Review of Financial Studies, 5*(4), 553–580.
- Brown, S. J., & Warner, J. B. (1985). Using daily stock returns: The case of event studies. *Journal of Financial Economics, 14*(1), 3–31.
- Cohen, L., Malloy, C., & Pomorski, L. (2012). Decoding inside information. *Journal of Finance, 67*(3), 1009–1043.
- Corwin, S. A., & Schultz, P. (2012). A simple way to estimate bid-ask spreads from daily high and low prices. *Journal of Finance, 67*(2), 719–760.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics, 13*(3), 253–263.
- Dimson, E. (1979). Risk measurement when shares are subject to infrequent trading. *Journal of Financial Economics, 7*(2), 197–226.
- Fama, E. F. (1970). Efficient capital markets: A review of theory and empirical work. *Journal of Finance, 25*(2), 383–417.
- Fama, E. F. (1998). Market efficiency, long-term returns, and behavioral finance. *Journal of Financial Economics, 49*(3), 283–306.
- Fama, E. F., & French, K. R. (1993). Common risk factors in the returns on stocks and bonds. *Journal of Financial Economics, 33*(1), 3–56.
- Fama, E. F., & French, K. R. (1997). Industry costs of equity. *Journal of Financial Economics, 43*(2), 153–193.
- Fama, E. F., & French, K. R. (2008). Dissecting anomalies. *Journal of Finance, 63*(4), 1653–1678.
- Fama, E. F., & French, K. R. (2015). A five-factor asset pricing model. *Journal of Financial Economics, 116*(1), 1–22.
- George, T. J., & Hwang, C.-Y. (2004). The 52-week high and momentum investing. *Journal of Finance, 59*(5), 2145–2176.
- Grossman, S. J., & Stiglitz, J. E. (1980). On the impossibility of informationally efficient markets. *American Economic Review, 70*(3), 393–408.
- Gu, S., Kelly, B., & Xiu, D. (2020). Empirical asset pricing via machine learning. *Review of Financial Studies, 33*(5), 2223–2273.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies, 29*(1), 5–68.
- Hastie, T., Tibshirani, R., & Friedman, J. (2009). *The elements of statistical learning* (2nd ed.). Springer.
- Hirshleifer, D., Lim, S. S., & Teoh, S. H. (2009). Driven to distraction: Extraneous events and underreaction to earnings news. *Journal of Finance, 64*(5), 2289–2325.
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics, 6*(2), 65–70.
- Hou, K., Xue, C., & Zhang, L. (2020). Replicating anomalies. *Review of Financial Studies, 33*(5), 2019–2133.
- Jaffe, J. F. (1974). Special information and insider trading. *Journal of Business, 47*(3), 410–428.
- Jagolinzer, A. D. (2009). SEC Rule 10b5-1 and insiders' strategic trade. *Management Science, 55*(2), 224–239.
- Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. *Journal of Finance, 45*(3), 881–898.
- Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling losers: Implications for stock market efficiency. *Journal of Finance, 48*(1), 65–91.
- Jegadeesh, N., & Titman, S. (2001). Profitability of momentum strategies: An evaluation of alternative explanations. *Journal of Finance, 56*(2), 699–720.
- Jeng, L. A., Metrick, A., & Zeckhauser, R. (2003). Estimating the returns to insider trading: A performance-evaluation perspective. *Review of Economics and Statistics, 85*(2), 453–471.
- Ke, G., Meng, Q., Finley, T., Wang, T., Chen, W., Ma, W., Ye, Q., & Liu, T.-Y. (2017). LightGBM: A highly efficient gradient boosting decision tree. *Advances in Neural Information Processing Systems, 30*.
- Kolari, J. W., & Pynnönen, S. (2010). Event study testing with cross-sectional correlation of abnormal returns. *Review of Financial Studies, 23*(11), 3996–4025.
- Künsch, H. R. (1989). The jackknife and the bootstrap for general stationary observations. *Annals of Statistics, 17*(3), 1217–1241.
- Lakonishok, J., & Lee, I. (2001). Are insider trades informative? *Review of Financial Studies, 14*(1), 79–111.
- Leland, H. E., & Pyle, D. H. (1977). Informational asymmetries, financial structure, and financial intermediation. *Journal of Finance, 32*(2), 371–387.
- Lo, A. W. (2002). The statistics of Sharpe ratios. *Financial Analysts Journal, 58*(4), 36–52.
- López de Prado, M. (2018). *Advances in financial machine learning*. Wiley.
- Lundberg, S. M., Erion, G., Chen, H., DeGrave, A., Prutkin, J. M., Nair, B., Katz, R., Himmelfarb, J., Bansal, N., & Lee, S.-I. (2020). From local explanations to global understanding with explainable AI for trees. *Nature Machine Intelligence, 2*(1), 56–67.
- Lundberg, S. M., & Lee, S.-I. (2017). A unified approach to interpreting model predictions. *Advances in Neural Information Processing Systems, 30*.
- Lynch, P., & Rothchild, J. (1989). *One up on Wall Street: How to use what you already know to make money in the market*. Simon & Schuster.
- Lyon, J. D., Barber, B. M., & Tsai, C.-L. (1999). Improved methods for tests of long-run abnormal stock returns. *Journal of Finance, 54*(1), 165–201.
- MacKinlay, A. C. (1997). Event studies in economics and finance. *Journal of Economic Literature, 35*(1), 13–39.
- McLean, R. D., & Pontiff, J. (2016). Does academic research destroy stock return predictability? *Journal of Finance, 71*(1), 5–32.
- Mitchell, M. L., & Stafford, E. (2000). Managerial decisions and long-term stock price performance. *Journal of Business, 73*(3), 287–329.
- Myers, S. C., & Majluf, N. S. (1984). Corporate financing and investment decisions when firms have information that investors do not have. *Journal of Financial Economics, 13*(2), 187–221.
- Newey, W. K., & West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. *Econometrica, 55*(3), 703–708.
- Niculescu-Mizil, A., & Caruana, R. (2005). Predicting good probabilities with supervised learning. *Proceedings of the 22nd International Conference on Machine Learning*, 625–632.
- Novy-Marx, R., & Velikov, M. (2016). A taxonomy of anomalies and their trading costs. *Review of Financial Studies, 29*(1), 104–147.
- Piotroski, J. D., & Roulstone, D. T. (2005). Do insider trades reflect both contrarian beliefs and superior knowledge about future cash flow realizations? *Journal of Accounting and Economics, 39*(1), 55–81.
- Platt, J. C. (2000). Probabilities for SV machines. In A. J. Smola, P. L. Bartlett, B. Schölkopf, & D. Schuurmans (Eds.), *Advances in large margin classifiers* (pp. 61–74). MIT Press. (Widely cited from its 1999 preprint, "Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods".)
- Rozeff, M. S., & Zaman, M. A. (1988). Market efficiency and insider trading: New evidence. *Journal of Business, 61*(1), 25–44.
- Rozeff, M. S., & Zaman, M. A. (1998). Overreaction and insider trading: Evidence from growth and value portfolios. *Journal of Finance, 53*(2), 701–716.
- Seyhun, H. N. (1986). Insiders' profits, costs of trading, and market efficiency. *Journal of Financial Economics, 16*(2), 189–212.
- Shleifer, A., & Vishny, R. W. (1997). The limits of arbitrage. *Journal of Finance, 52*(1), 35–55.
- Shumway, T. (1997). The delisting bias in CRSP data. *Journal of Finance, 52*(1), 327–340.
- Shumway, T., & Warther, V. A. (1999). The delisting bias in CRSP's Nasdaq data and its implications for the size effect. *Journal of Finance, 54*(6), 2361–2379.
- Tóth, B., Lempérière, Y., Deremble, C., de Lataillade, J., Kockelkoren, J., & Bouchaud, J.-P. (2011). Anomalous price impact and the critical nature of liquidity in financial markets. *Physical Review X, 1*(2), 021006.
- Zou, H., & Hastie, T. (2005). Regularization and variable selection via the elastic net. *Journal of the Royal Statistical Society: Series B, 67*(2), 301–320.

### Regulation and data

- Sarbanes–Oxley Act of 2002, Pub. L. No. 107-204, §403.
- Securities Exchange Act of 1934, §16(a); SEC Rules 10b-5 and 10b5-1 (17 CFR 240.10b-5, 240.10b5-1); Rule 3a51-1 (17 CFR 240.3a51-1).
- SEC Release No. 33-8230 (2003), *Mandated Electronic Filing and Website Posting for Forms 3, 4 and 5*.
- SEC Release No. 33-9002 (2009), *Interactive Data to Improve Financial Reporting*.
- SEC Release No. 33-11138 (2022), *Insider Trading Arrangements and Related Disclosures*.
- Regulation S-T, Rule 13 (17 CFR 232.13); Regulation NMS, Rule 612 (17 CFR 242.612).
- Nasdaq Listing Rules 5450(a)(1), 5550(a)(2) and 5810(c)(3)(A); NYSE Listed Company Manual §802.01C.
- FINRA. *Tick Size Pilot Program*. https://www.finra.org/rules-guidance/key-topics/tick-size-pilot-program
- U.S. Securities and Exchange Commission. *Insider Transactions Data Sets*. https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
- U.S. Securities and Exchange Commission. *Accessing EDGAR Data* (fair-access policy). https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- French, K. R. *Data Library*. https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- Tiingo. *Pricing* and *End-of-Day API documentation*. https://www.tiingo.com/about/pricing

---

## Appendix D — Changes from the first draft

| Topic | First draft (v1) | This version |
|---|---|---|
| Period | 2011 Q1 – 2026 Q3 (63 quarters) | Insider data 2006 Q1 – 2026 Q3 (83 quarters); returns studied from 2016 (free price budget, §5.2) |
| Horizon | 60 days | 5, 21, 63, 126, 252 days; primary 63 |
| Benchmark | IWM | SPY, IWM, equal-weighted industry (primary), FF5 + UMD |
| Label | Beat IWM by ≥ 5 points | Industry-adjusted BHAR net of the trade's own cost > 0 |
| Universe | Price ≥ $0.50; trades of $10k–$500M | Unadjusted price ≥ $2, ADDV20 ≥ $100k, 18/20 active sessions; purchases ≥ $25k per filing (D46) |
| Gates | Whole-filing footnote scan | Transaction-level footnotes; offering filter; point-in-time joint-filer merging; SPAC/fund exclusion at T; timeliness rule; price check |
| Clusters | 21-day cooldown; any owners | 63-session cooldown; must include an officer or director |
| Comparison groups | None | Solo CEO/CFO (B1, confirmatory); solo other insider (B2, exploratory) |
| Sales | Discarded | Kept (product lookup, selling features) |
| Fundamentals | Full point-in-time XBRL | Shares outstanding plus five simple items, first-filed values only (D43) |
| Macro data | VIX, yield curve, credit spreads, Fed funds rate as features | None (regime analysis only) |
| Prices | Tiingo with a yfinance fallback | Yahoo for listed stocks, Tiingo for delisted ones; unadjusted prices for price-level rules; three delisting classes and bounds |
| Entry | Unspecified | Open of the session after the filing date |
| Costs | None | Spread + square-root impact per trade |
| Statistics | Not specified | Pre-registered decision rules; time-robust errors; Holm–Bonferroni; stated power |
| ML validation | Purged CV mentioned; LightGBM calibrated with random 3-fold | Purged expanding walk-forward; three-way split; concurrency weights; six baselines; sealed holdout |
| Model selection | ROC-AUC, Brier, IC | Log loss with the one-standard-error rule; plus calibration, rank IC, net-of-cost alpha, deflated Sharpe ratio |
| Database | PostgreSQL | DuckDB + Parquet |
| Product | Three API endpoints | Screener, stock lookup, model card; API |
| Code issues fixed | Liabilities fallback used `LiabilitiesAndStockholdersEquity` (equals total assets); `annualize_flow` missing `def`; the "18-feature" list had 19 names; column names did not match the SEC files (`ISSUERCIK`, `AFF10B5ONE`); deprecated scikit-learn `penalty` argument | Resolved or made moot by the redesign |

---

## Appendix E — Parameter register

Every number in the design, its basis, and how it is checked. Sensitivity variants run on the development period only, using the default event set: they add no new companies, so they need no new prices. "Convention" marks values taken from common practice that are not varied.

| Parameter | Value | Basis | Sensitivity |
|---|---|---|---|
| Insider data period | 2006 Q1 – 2026 Q3 | All available SEC data sets | — |
| Labelled window start | 1 Jan 2012 | Earliest year every source is complete without workarounds: XBRL share counts for all filers from mid-2011 (§5.2, D42) | 2016 start (smaller; best price coverage) |
| Holdout | Signal dates 1 Jan 2023 – 1 Jun 2026 | Most recent ~3.4 years; factor data end on 31 Aug 2026 | Fixed |
| G6 minimum value | $25,000 per entity per filing | Removes token purchases, which are many filings but almost no dollars (pilot: 25–39% of filings below $10k, < 0.1% of dollars), and stops a token purchase counting as a cluster's second buyer (D46) | $10k; $50k |
| G6 timeliness | Filed ≤ 30 days after the trade | The two-business-day rule; later filings describe old trades | 10; 90 days |
| G8 tolerance | ±10% of the day's range | Allows for odd-lot and off-hours prints | Convention |
| Cluster window | 14 calendar days | Trading windows; two-day filing (§6.4) | 7; 30 days |
| Cluster minimum entities | 2, including an officer or director | Smallest independent agreement | 3 |
| Cluster / solo minimum value | $100,000 | ≈ 1.3 × the median clean purchase | $50k; $250k |
| Cooldown | 63 sessions | One primary label window; costs ~13% of clusters | 21 calendar days |
| Price floor | Unadjusted close ≥ $2 | §6.5 | $1; $5 |
| Position size Q | $10,000 | Owner's decision: a small retail position | $25k; $50k |
| Liquidity floor | ADDV20 ≥ $100k (= Q ÷ 10%) | §6.5 | $250k (Q = $25k); $500k (Q = $50k) |
| Activity floor | Volume on ≥ 18 of 20 sessions | Stale prices | 15 of 20 |
| Horizons | 5, 21, 63, 126, 252 sessions | One week to one year | — |
| Primary horizon | 63 sessions | §6.6 | Other horizons reported |
| Factor beta window | Sessions T−252 to T−21, ≥ 120 observations | About one year, skipping the month before the event | Convention |
| Spread and ADDV window | 20 sessions | About one month | Convention |
| Volatility window | 63 sessions | About one quarter | Convention |
| Impact coefficient | 1 | Of order one in Tóth et al. (2011); never estimated on micro-caps (§6.8) | 0.5; 2 |
| Delisting returns | 0% acquired; −30% NYSE/NYSE American; −55% Nasdaq and other venues; unknown = performance-related | Shumway (1997); Shumway & Warther (1999) | 0%; −100% |
| Merger look-back | 12 months before the last trade | Typical time to complete a deal | Convention |
| Selling look-back (F12, F13) | 90 days | About one quarter | Convention |
| Repeat-buying look-back (F14) | 365 days | One year | Convention |
| Routine definition (F9) | Same calendar month in each of 3 prior years | Cohen et al. (2012) | — |
| F10 shrinkage | k = 5, toward the 36-month base rate | Weak prior | Convention |
| Winsorising | 1st / 99th percentiles | Common practice | Convention |
| Training-window split | Last 12 months = 6 tuning + 6 calibration | Keeps tuning and calibration separate | Convention |
| Fold-1 minimum fit size | 500 events | Enough for the small grids | Convention |
| Portfolio cut-off | 80th percentile (top quintile) | Common practice | Top tercile |
| Calendar-time minimum positions | 10 per day | Avoids returns dominated by one or two stocks | Keep all days |
| Newey–West lags | ⌈H/21⌉ (monthly series); 10 (daily regressions) | Overlap length | Convention |
| Significance | One-sided 5%; Holm–Bonferroni over five tests | §3.3 | — |
| Model grids | §7.2 (25 configurations) | Small and fixed in advance | — |
