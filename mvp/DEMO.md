# EDGAR-SENTINEL MVP: 5-minute class demo

**Before class:**
- **Public site:** https://1com.github.io/captone-sec-insider/ (anyone can open it).
- **Local version:** `uv run python -m mvp serve`, then open **http://127.0.0.1:8765**. To rebuild first: `uv run python -m mvp build --skip-prices` (about 30 s).
- **Theme:** the moon button switches light and dark. Use light mode on a bright projector.

## 0:00 – New insider buying (1.5 min)

- "This is the product. Every time several insiders, or the CEO or CFO, buy their own company's stock on the open market, it appears here with a score."
- **Score:** "The model's estimated chance that the stock beats small caps (IWM) over the 63 trading days after the filing, after trading costs."
- **Time left:** "How much of that 3-month window remains. Events whose window has passed are hidden unless you choose 'All events'."
- **Evidence line and banner:** "I show how reliable the scores are right next to them: so far, barely better than a coin flip."
- **Quality checks:** "price check failed" marks a filing typo, such as a $1.80 price filed as $180,000. Funds and blank-check companies are excluded automatically.
- Filter to **Clusters** with a **$1M or more** minimum, then sort by **Score**.

## 1:30 – Does it work? (1 min)

- **The question:** "Does a stock beat the market after insiders cluster-buy, once costs are paid?"
- **Funnel:** "4.5 million SEC filings, down to about 2,100 tradable pilot events."
- **Pilot answer:** read it aloud. "These are 2006–2011 results at companies that still trade. The real 2012–2026 study stays sealed until its plan is pre-registered."

## 2:30 – Findings (1 min)

- **Return-path chart:** "Day 0 is the morning after the filing. Before it, prices were falling: insiders buy dips. After it, clusters drift ahead of small caps."
- **By-year chart:** "2009 carries much of the average; the typical event earned under 1%."
- **Who is in the sample:** "Two in three pilot events are at companies that no longer trade. That's why the full study pays for delisted-stock prices."

## 3:30 – Model (45 s)

- "Logistic regression and LightGBM, trained on 2006–2010 and tested once on 2011, against a market-data-only model and a no-skill baseline. Verdict: not yet. The full study has about five times as much data."

## 4:15 – Company lookup (45 s)

- Search a ticker a teacher names. "Every insider buy and sell since 2006, who made it, the events and their scores, with links to the original SEC filings."

## 5:00 – Close

- **Method & limits:** delisted stocks, merged co-filers, industry-adjusted returns, company financials, daily filing updates, and a pre-registered model tournament with a sealed holdout.
