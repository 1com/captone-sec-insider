# EDGAR-SENTINEL MVP: 5-minute class demo

**Before class:**
- **Local version:** `uv run python -m mvp serve`, then open **http://127.0.0.1:8765**. To rebuild first: `uv run python -m mvp build --skip-prices` (about 30 s).
- **Shareable version:** https://claude.ai/artifact/EGrR4kQJK5Tuqbo8Lj5fwv. It is private until you share it from its Share menu.
- **Theme:** the moon button switches light and dark. Use light mode on a bright projector.
- **Internet:** the local version runs offline except for the live price chart on the Company tab.

## 0:00 – Overview (1 min)

- "The question: when several company insiders buy their own stock on the open market within two weeks, does the stock beat the market after trading costs?"
- Point at the **funnel**: 83 quarters of SEC Form 4 data, 4.5 million filings, down to about 2,100 tradable pilot events. "Every step removes something that would bias the answer: amendments, pre-planned 10b5-1 trades, company share sales, illiquid stocks."
- Read the **Pilot answer** box aloud. Then point at the amber banner: "These are 2006–2011 results at companies that still trade today. The real study, 2012–2026, stays sealed until its plan is pre-registered, so I can't fool myself."

## 1:00 – Findings (1.5 min)

- **Return-path chart.** "Day 0 is the morning after the filing becomes public. Before it, prices were falling: insiders buy dips. After it, clusters drift ahead of small caps." Toggle **IWM / SPY**.
- **Holding-period table.** "Gross and net of an estimated bid–ask cost, with bands that resample whole months, because events in the same month are not independent."
- **By-year chart.** "Honest caveat: 2009 carries much of the average, and the median event earned well under 1%."
- **Who is in the sample.** "Two in three pilot events are at companies that no longer trade. That survivorship bias is why the full study pays for delisted-stock prices."

## 2:30 – Model (1 min)

- "Two models, logistic regression and LightGBM, trained on 2006–2010 and tested once on 2011, against a model that sees only market data and a no-skill baseline."
- Read the **verdict**: "Not yet. In the pilot, insider details add little beyond market data. That is a real finding, and the full study has about five times as much data to test it."
- **Calibration** and **drivers**: "The page shows the model's working, not just a score."

## 3:30 – Latest clusters (45 s)

- "This is the product: every new cluster from July to September 2026, scored live." Filter to **Clusters** with a **$1M or more** minimum, then sort by **Score**.
- Point out the quality checks: "price check failed" marks a filing typo, such as a $1.80 price filed as $180,000. Funds and blank-check companies are excluded automatically.

## 4:15 – Company lookup (45 s)

- Search a ticker a teacher names, or use the default company. "Every insider buy and sell since 2006, who made it, the events and their scores." Each filing links to the original on SEC EDGAR.

## 5:00 – Close

- **Method & limits:** "What the full study adds: delisted stocks, merged co-filers, industry-adjusted returns, company financials, and a pre-registered model tournament with a sealed holdout."
