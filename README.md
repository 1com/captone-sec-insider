# EDGAR-SENTINEL

A market research platform for any US-traded stock: prices, financial statements as first filed,
SEC filings in plain English and an insider activity tracker in one place, with three forecasts a
retail investor cannot easily get elsewhere: **dilution risk**, the **expected results-day move**
and **expected volatility**. Updated every day.

This is version 2, rebuilt from scratch on 29 October 2026. Version 1 (an insider-trading study
that grew into this platform) is kept at the tag `v1-final`.

## Documents

| Document | What it says |
|---|---|
| [docs/spec.md](docs/spec.md) | what the platform does, for whom, which stocks get what, the data rules, how forecasts are judged |
| [docs/architecture.md](docs/architecture.md) | the six data layers, every table, the commands |
| [docs/lessons-from-v1.md](docs/lessons-from-v1.md) | what went wrong in v1 and the rule v2 follows instead |
| [docs/decisions.md](docs/decisions.md) | the decision log |
| [docs/plan.md](docs/plan.md) | the schedule to 17 November, the cut order, open questions |

## Status

Step 0 (fresh start) on 29 October 2026. The data pipeline is rebuilt layer by layer from the raw
files kept from v1; see [docs/plan.md](docs/plan.md).

## Setup

```bash
uv sync
cp .env.example .env    # SEC_USER_AGENT, FRED_API_KEY, TIINGO_API (Tiingo until 26 Nov 2026)
uv run pytest
```

Data lives in `data/` (git-ignored). Values derived from Tiingo prices are private and never
published.
