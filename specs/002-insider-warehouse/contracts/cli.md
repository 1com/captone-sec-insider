# Contract: CLI Additions (Feature 002)

Extends [../../001-skeleton-sec-ingest/contracts/cli.md](../../001-skeleton-sec-ingest/contracts/cli.md). The exit codes are unchanged: 0 ok, 1 failed or problems found, 2 usage, 3 config, 4 not implemented, 5 SEC 403.

| Command | Step | Reads | Writes | Network |
|---|---|---|---|---|
| `sentinel stage` | 2 | `data/raw/sec/insider/*.zip` (manifest originals) | `stg.*`, `stg.conversion_issue`, `stg.load_report` | No |
| `sentinel entities` | 3 | `stg.submission`, `stg.reportingowner` | `core.filing`, `core.entity_member`, `core.owner_role` | No |
| `sentinel gates` | 4 | `stg.*`, `core.*` from Step 3 | `core.transaction`, `core.clean_purchase`, `audit.funnel` | No |
| `sentinel detect-prelim` | 5 | `core.clean_purchase`, `core.entity_member`, `core.owner_role` | `evt.prelim_event`, `evt.prelim_event_member` | No |
| `sentinel symbols` | 6 | `core.filing`, `evt.prelim_event`, the latest SEC ticker snapshot | `core.symbol_map`, `core.symbol_unmatched` | Optional: `--tiingo-report` fetches Tiingo's public list **into memory** to print coverage counts |
| `sentinel fetch-headers` | 6 | `evt.prelim_event` (T ≥ labelled start) | `data/raw/sec/headers/…`, manifest, `core.filing_header`, `core.header_failure` | Yes (SEC, ≤ 10/s) |
| `sentinel build` | 2–6 | as above | runs `stage`, `entities`, `gates`, `detect-prelim`, `symbols` in order, then re-parses any stored headers | No |
| `sentinel audit sheets [--force]` | QA | `core.*` | `specs/002-insider-warehouse/audits/{entities,gates_excluded,gates_kept}.csv` | No |
| `sentinel audit summary` | QA | the audit CSVs | prints agreement rates per sheet; exit 1 if any sheet has blank verdicts | No |
| `sentinel compare-provisional` | QA | `evt.prelim_event`, `data/provisional/events_PROVISIONAL.parquet` (as a file) | `specs/002-insider-warehouse/comparison.md` | No |

## Behaviour common to the build steps

- **Idempotent**: each step drops and recreates only its own tables, inside one transaction.
- **Dependencies**: a step whose input tables are missing exits 1, naming the step to run first.
- **Summary line**: each step prints rows written and the elapsed time, and appends a row to `core.build_log`.
- **`stage`**: prints `load_report` mismatches and exits 1 if any (table, quarter) count differs from its file.
- **`gates`**: exits 1 if the funnel does not reconcile.

## `fetch-headers` options

| Option | Default | Effect |
|---|---|---|
| `--limit N` | all | Fetch at most N missing headers (for testing) |
| `--retry-failures` | off | Also retry accessions listed in `core.header_failure` |

- **Resume**: headers already in the manifest are never refetched.
- **Progress**: every 500 headers.
- **Rate**: `ops.sec_header_target_requests_per_second` (8), ceiling `ops.sec_max_requests_per_second` (10).
- **403**: exit 5.
