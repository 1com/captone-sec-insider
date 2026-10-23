# Contract: Command-Line Interface

Entry point: `uv run sentinel <command> [options]`. `uv run sentinel --help` lists every command below, grouped into help panels by phase. Each line starts with its plan step number, for example `[Step 1] Download the quarterly SEC insider data sets`.

## Exit codes (all commands)

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Run failed or found problems: failed quarters, verify mismatches, missing inputs |
| 2 | Usage error: bad options or arguments (typer default) |
| 3 | Configuration error: no SEC contact, params file invalid or incomplete |
| 4 | Step not yet implemented |
| 5 | The SEC rejected the client (HTTP 403). The run stopped and nothing was retried |

## Commands implemented in this feature

### `sentinel check` — [Step 0]

Validates the environment without using the network:
- `.env` is present, `SEC_USER_AGENT` contains an e-mail address, and `TIINGO_API` is reported as set or unset (the value is never shown);
- `config/params.yaml` loads and passes the Appendix E register check;
- the `data/` folders exist or can be created, and `data/` is git-ignored.

Output: one line per check, `OK`, `WARN` or `FAIL`. Exits 0 if no `FAIL`, otherwise 3.

### `sentinel fetch-sec` — [Step 1]

Downloads every quarter in the configured range that is not already stored.

| Option | Default | Effect |
|---|---|---|
| `--quarters 2019q1,2023q2` | all in range | Limit to listed quarters (each must be in range) |
| `--refetch QUARTER` | — | Download a dated replacement copy of one stored quarter (role `refetch`). The original is untouched |
| `--dry-run` | off | Resolve URLs and print the plan; download nothing |

Behaviour:
- Writes to `data/raw/sec/insider/` and `data/raw/manifest.jsonl`.
- Prints a progress line per quarter: `stored`, `skipped (verified)`, `failed (<reason>)`.
- Ends with a summary: stored, skipped, failed, total bytes.
- Exits 0 if every quarter is stored, 1 if any failed, 3 if no contact is configured, 5 on a 403.

Skipping: a quarter already stored is skipped only if its SHA-256 matches the manifest (FR-014). Re-hashing the whole 0.93 GB archive takes seconds, well within SC-003's one minute. A mismatch is reported as `failed (stored file differs from manifest)` and the file is never overwritten.

### `sentinel verify-sec` — [Step 1]

Re-hashes every file the manifest lists under `sec/` and scans for unrecorded files. Works offline.

Output: counts of `ok`, `mismatch`, `missing` and `unrecorded`, with one line per non-`ok` file. Exits 0 only if every expected quarter is `ok` and nothing is `unrecorded`, otherwise 1.

### `sentinel fetch-sec-tickers` — [Step 6, partial]

Saves today's SEC `company_tickers_exchange.json` to `data/raw/sec/reference/company_tickers_exchange_YYYYMMDD.json` with a manifest line. If today's snapshot already exists, it is skipped. Exit codes are as for `fetch-sec`.

### `sentinel candidates-provisional` — [Step 5, provisional]

Builds the provisional delisted-candidate list. It needs all 83 quarters stored and matching the manifest, plus at least one ticker snapshot.

| Option | Default | Effect |
|---|---|---|
| `--tickers-snapshot PATH` | latest in `data/raw/sec/reference/` | Which SEC ticker snapshot to use |
| `--no-tiingo` | off | Skip the Tiingo list. Every `tiingo_match` becomes `not_checked`. The run is fully offline |
| `--rebuild-scratch` | off | Delete and rebuild the scratch DuckDB, which is otherwise reused when the inputs are unchanged |

Writes the files in [provisional-outputs.md](provisional-outputs.md) and prints the §5.2 table (one row per start year) next to the pilot figures. Exits 0 on success, 1 if inputs are missing or incomplete.

## Stub commands (exit 4: "not yet implemented — plan Step N")

| Panel | Command | Step |
|---|---|---|
| Phase 1 — Insider data | `stage` | 2 |
| | `entities` | 3 |
| | `gates` | 4 |
| | `detect-prelim` | 5 |
| | `symbols` | 6 |
| Phase 2 — Prices, labels, features | `fetch-prices` | 7 |
| | `fetch-reference` | 7 |
| | `detect` | 7 |
| | `delistings` | 8 |
| | `shares-out` | 9 |
| | `costs` | 10 |
| | `prereg-status` | 10a |
| | `labels` | 11 |
| | `features` | 12 |
| | `serve` | P |
| Phase 3 — Analysis | `event-study` | 13 |
| | `ml-dataset` | 14 |
| | `baselines` | 15 |
| | `tournament` | 16 |
| | `explain` | 17 |
| Phase 4 — Holdout and delivery | `holdout` | 18 |
| | `score-live` | 19 |
| | `robustness` | 20 |
| | `report` | 21 |

Command names may be refined by the feature that implements each step. This feature fixes only the listing, grouping and exit behaviour.
