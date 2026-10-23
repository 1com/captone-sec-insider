# Contract: Provisional Outputs

All files are written to `data/provisional/` and are rebuilt on every run. Each file name contains `PROVISIONAL`. Each tabular file has a first column `status` whose value is always `PROVISIONAL`. These files must never be read by production code (a guard test enforces this).

| File | Content |
|---|---|
| `delisted_candidates_PROVISIONAL.csv` | The ranked pull list (below) |
| `events_PROVISIONAL.parquet` | Every provisional A/B1 event from 2006 onward, all companies |
| `funnel_PROVISIONAL.csv` | Per quarter × gate: `rows_in`, `rows_out`, `rows_removed` |
| `summary_PROVISIONAL.md` | Comparison with the pilot (below) |
| `run_PROVISIONAL.json` | Run metadata ([data-model.md](../data-model.md) §12) |
| `provisional_PROVISIONAL.duckdb` | Scratch database (reusable cache; safe to delete) |

## `delisted_candidates_PROVISIONAL.csv`

UTF-8, comma-separated, header row, sorted by `rank`.

| Column | Type | Notes |
|---|---|---|
| `status` | text | Always `PROVISIONAL` |
| `rank` | int | 1 = highest priority |
| `tier` | int | 1 = has at least one cluster (A) event, 2 = solo CEO/CFO (B1) only |
| `issuer_cik` | int | |
| `issuer_name` | text | From the latest filing |
| `last_ticker` | text | Normalised. Empty if never reported |
| `all_tickers` | text | Distinct normalised tickers separated by `|`, sorted |
| `n_events_a` | int | A events, all years from 2006 |
| `n_events_b1` | int | B1 events, all years from 2006 |
| `n_events_labelled` | int | A + B1 events with signal date ≥ the labelled-window start (2016-01-01) |
| `first_signal_date` | date | Earliest event |
| `last_signal_date` | date | Latest event |
| `tiingo_match` | enum | `matched` · `ticker_only` · `unmatched` · `not_checked` |
| `tiingo_matched_ticker` | text | The ticker under which Tiingo lists the match: a reported ticker, normalised, or its bankruptcy form with a `Q` suffix. Empty otherwise |

## `summary_PROVISIONAL.md`

Sections, each set against the pilot figures stored in `provisional.pilot_reference`:

1. **Header**: a warning that the list is provisional and look-ahead, plus the run time, git commit, params hash, ticker-snapshot date and the Tiingo list's Last-Modified time.
2. **Plan §5.2 table**, one row per start year (2006, 2009, 2011, 2014, 2016). Each row shows A + B1 events, companies, likely delisted and matched in Tiingo's list, and likely delisted and not matched (`unmatched` + `ticker_only`), as ours, the pilot's, and the % gap. Any gap beyond ±15% is marked **CHECK**. This table is also the evidence for revisiting the labelled-window start before `prereg-v1`.
3. **Per-year A and B1 counts** for 2006 – 2026, against Appendix A.3.
4. **Funnel for 2019 Q1 and 2023 Q1**, against Appendix A.1. Any gap beyond 1% is marked **CHECK** (SC-005).
5. **Companies now on OTC or with no exchange** in the SEC map. These are not candidates, but they are counted here because they explain part of any gap with the pilot ([research.md](../research.md) R5).
6. **Data notes**: duplicates removed by key and quarters read.
