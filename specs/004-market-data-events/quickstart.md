# Quickstart: Validate Feature 004

**Prerequisites**:
- Feature 002 is complete: `sentinel build` passes, and the signal-filing headers from 2012 are loaded (T037).
- `.env` holds `SEC_USER_AGENT` and `TIINGO_API`.
- About 10 GB of free disk space: SEC bulk archives 3 GB, Yahoo about 1 GB, Tiingo about 0.5 GB, and the warehouse grows to about 6 GB.
- No `sentinel explore` session is open while a build step runs (the warehouse lock).
- For Steps 4–5 only: the Tiingo Power plan is active, and `ops.tiingo_paid_until` is set in `config/params.yaml`.

Contracts: [cli](contracts/cli.md), [warehouse invariants](contracts/warehouse-schema.md), [parameters](contracts/params-rules.md), [audit sheets](contracts/audit-sheets.md), [Tiingo register](contracts/tiingo-register.md).

**Heavy steps run under the memory ceiling**:

```bash
cap() { systemd-run --user --wait --pipe --quiet -p MemoryMax=5G -p MemorySwapMax=1G \
          --working-directory="$PWD" "$@"; }
```

## 1. Tests (offline)

```bash
uv run pytest            # unit + guards; slow and network tests skipped
uv run ruff check .
```

The unit tests include:
- the reverse-split as-traded rebuild;
- every G8, G7, floor and cooldown case in the spec;
- unpriced events;
- the Abdi–Ranaldo recovery on a synthetic path;
- the §6.8 illustration, about 3.5%;
- delisting classes and the re-map rule;
- first-filed XBRL;
- the Tiingo guard (exit 6) and the register completeness test.

## 2. Free sources (any day; about 30 minutes)

```bash
uv run sentinel fetch-reference                       # French library + FINRA pilot file
uv run sentinel fetch-company                         # SEC companyfacts.zip + submissions.zip (~3 GB)
uv run sentinel fetch-prices --source yahoo --limit 20  # smoke test
uv run sentinel fetch-prices --source yahoo           # ~4,500 tickers + SPY, IWM; ~10 min
uv run sentinel fetch-headers --final                 # warm-up and other candidate headers (~1,300)
cap uv run sentinel build
```

**Expected**:
- `reference`: factors and industries through 2026-08-31; 1,235 pilot tickers; every header SIC either maps to a 49-industry portfolio or appears in the unmapped list.
- `company-facts`: XBRL coverage per item at event dates is printed.
- `prices`: chosen series for the Yahoo issuers, and `audit.price_issue` counts.
- `detect` (Yahoo issuers priced, Tiingo issuers still unpriced): the G8 rate, then events by group and outcome. Coverage is below target until Tiingo is loaded.

## 3. Price checks on known stocks

```bash
uv run pytest -m slow tests/integration/test_prices_real.py
```

**Expected**:
- A listed stock with a reverse split shows an as-traded close before the split that differs from the split-adjusted close by the split ratio, with equal dollar volume.
- SPY's sessions match the exchange calendar for 2024, a known year.

## 4. Tiingo month (from Thursday 29 October 2026)

```bash
# After subscribing (auto-renew off): set ops.tiingo_paid_until in config/params.yaml
uv run sentinel tiingo-status                         # window open, register empty
uv run sentinel fetch-prices --source tiingo --limit 10
uv run sentinel fetch-prices --source tiingo          # ~6,000 requests, < 1 hour
cap uv run sentinel build
uv run sentinel coverage                              # writes coverage.md
```

**Expected**:
- SC-001: coverage ≥ 90% for A and B1 events from 2012, by year and delisting status.
- SC-002: G8 ≥ 95%.
- Unpriced events counted by year and group.
- `core.price_series` reports identity rejections (`dates`, `name`) for reused tickers.
- `tiingo-status` lists every Tiingo file and table (SC-007, first half).

## 5. Researcher checkpoints (about 2 hours in all)

```bash
uv run sentinel audit golden            # 30 events → audits/golden_set.csv
uv run sentinel audit delistings        # 30 issuers → audits/delisting_audit.csv
uv run sentinel audit market-caps       # 10 companies vs Yahoo's market cap
# … the researcher fills the verdict columns …
uv run sentinel audit golden-summary        # SC-003: 30/30 or all explained
uv run sentinel audit delistings-summary    # SC-004: ≥ 90% agreement
```

Before final detection, the D45 sheet result from feature 002 (`sentinel audit no-sic`) sets `rules.g7_no_sic`. If 3 or more of the 30 are operating companies, set it to `current_sic` and run `sentinel detect` again.

## 6. Point-in-time and memory (SC-006, SC-009)

```bash
cap uv run pytest -m slow tests/integration/test_truncation_events_real.py   # 20 (issuer, T) pairs
```

Peak memory for every step is read from the unit's cgroup `memory.peak` and recorded in the run notes. It must stay under 5 GB.

## 7. Offline rebuild (SC-008), before the paid month ends

```bash
# with the network disabled (e.g., unshare -rn), from the stored raw files:
time cap unshare -rn uv run sentinel build      # < 30 min; identical tables
uv run pytest -m slow tests/integration/test_rebuild_identical.py
```

## 8. Costs report

```bash
uv run sentinel costs        # writes costs.md: cost by price bucket, any jump at a price other than $2
```

## 9. End of the paid month (after the research that needs Tiingo data is done)

```bash
uv run sentinel tiingo-status
uv run sentinel tiingo-delete            # dry run: lists what will go
uv run sentinel tiingo-delete --yes      # deletes, rewrites the warehouse, verifies W12
```

Record the printed decision-log line in `docs/initialplan.md` §12. Check that no copy of `data/` exists elsewhere, such as backups or cloud sync (SC-007, second half).
