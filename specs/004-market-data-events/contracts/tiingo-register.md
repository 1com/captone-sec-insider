# Contract: Tiingo Deletion Register (FR-005, SC-007; constitution VI)

Tiingo data may be stored only while the paid plan is active. When the plan ends, it must be deleted everywhere the project controls: `data/raw/`, the warehouse, caches and backups. Per-security values derived from Tiingo prices count as Tiingo data. Only aggregates that cannot reconstruct prices may be kept.

## What is registered

1. **Raw files**: every manifest line with `source = tiingo`. All of them live under `data/raw/tiingo/`:
   - `supported_tickers.zip`
   - `meta/{ticker}.json.gz`
   - `prices/{ticker}.csv.gz`
2. **Warehouse**: the list `TIINGO_DERIVED` in `sentinel.core.tiingo` names each table and its predicate.

   | Table | Predicate |
   |---|---|
   | `stg.price_tiingo` | whole table |
   | `core.tiingo_listing` | whole table |
   | `core.price_series` | `price_source = 'tiingo'` |
   | `core.price_daily` | `price_source = 'tiingo'` |
   | `core.price_check` | `price_source = 'tiingo'` |
   | `evt.event_candidate` | `price_source = 'tiingo'` |
   | `evt.event` | `price_source = 'tiingo'` |
   | `evt.event_cost` | `price_source = 'tiingo'` |
   | `core.delisting` | `price_source = 'tiingo'` |
   | later features: `lab.*`, `hold.*`, `feat.*`, `ml.*` rows of Tiingo-priced events | added by those features |

3. **Test**: any warehouse table with a `price_source` column that is missing from `TIINGO_DERIVED` fails the suite.

`audit.*` tables hold counts and shares only (aggregates) and are kept.

## Guard

- `ops.tiingo_paid_from: 2026-10-29`
- `ops.tiingo_paid_until`: set by the researcher on subscribing, to the day the plan ends

Writing Tiingo data (fetching, or building `stg.price_tiingo`) outside `[paid_from, paid_until)` exits 6.

## Deletion (`sentinel tiingo-delete --yes`)

1. Stop if a warehouse lock is held (`sentinel explore` or another step).
2. Delete the registered rows and tables in one transaction.
3. Rewrite the warehouse into a fresh file:
   - attach a new file and `COPY FROM DATABASE`;
   - check row counts;
   - replace the old file and delete it.
   This removes freed blocks that may still hold deleted values.
4. Delete `data/raw/tiingo/` and any `data/**/*tiingo*` file.
5. Append one manifest line per deleted file: `role = deleted`, original path, deletion time.
6. Verify W12 (nothing left) and print a decision-log line to record in `docs/initialplan.md` §12, giving the date, files, bytes and rows deleted.

## Researcher checklist (quickstart)

- No copies of `data/` outside the repository: backups, other disks, cloud sync.
- `tiingo-status` the day before `paid_until`.
- Run the offline rebuild check (SC-008) before deleting.
