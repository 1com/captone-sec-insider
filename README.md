# EDGAR-SENTINEL

Do clusters of insider purchases (SEC Form 4) predict stock returns after trading costs? This is a research pipeline first and a screener second. The full design is in [docs/initialplan.md](docs/initialplan.md), and the project rules are in [.specify/memory/constitution.md](.specify/memory/constitution.md).

## Setup

```bash
uv sync
```

Create a `.env` file in the repository root. It is git-ignored and never committed.

```
SEC_USER_AGENT="Your Name your@email"   # required by the SEC's fair-access policy
TIINGO_API=...                          # Tiingo key (delisted-stock prices)
```

Check the setup (works offline):

```bash
uv run sentinel check
```

## Commands available so far

| Command | Plan step | What it does |
|---|---|---|
| `sentinel check` | 0 | Checks `.env`, `config/params.yaml` against Appendix E, and the data folders |
| `sentinel fetch-sec` | 1 | Downloads the 83 quarterly SEC insider data sets (2006 Q1 – 2026 Q3, about 0.9 GB) into `data/raw/sec/insider/`, recording a SHA-256 for each in `data/raw/manifest.jsonl`. Resumable; at most 10 requests per second |
| `sentinel verify-sec` | 1 | Re-hashes the stored archives against the manifest (offline) |
| `sentinel fetch-sec-tickers` | 6 (partial) | Saves today's SEC company-ticker map |
| `sentinel candidates-provisional` | 5 (provisional) | Ranks likely-delisted companies whose prices must come from Tiingo. Look-ahead, used only to plan the price pull; output goes to `data/provisional/` |

`uv run sentinel --help` lists every pipeline step. Steps not built yet exit with code 4.

## Data layout

Everything under `data/` is git-ignored and can be regenerated:

- `data/raw/`: downloads exactly as received, read-only, recorded in `manifest.jsonl`.
- `data/provisional/`: the provisional candidate list and its summary against the pilot.
- Later features add `data/warehouse.duckdb`, rebuilt from `data/raw/` by commands.

## Development

```bash
uv run pytest            # offline; network tests need --run-network
uv run ruff check .
```

Features follow spec-kit: `specs/<feature>/` holds each feature's spec, plan, tasks and run notes. The current feature is [specs/001-skeleton-sec-ingest/](specs/001-skeleton-sec-ingest/).
