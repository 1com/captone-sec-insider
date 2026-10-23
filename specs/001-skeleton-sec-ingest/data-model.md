# Data Model: Project Skeleton, SEC Insider-Data Ingest and Provisional Delisted-Candidate List

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Source columns are named as they appear in the SEC files ([research.md](research.md) R2). File formats are in [contracts/](contracts/).

## 1. Quarter

One calendar quarter of SEC insider data.

| Field | Type | Rule |
|---|---|---|
| `key` | text `YYYYqN` | Generated from `insider_data_period.start` to `.end` in params (2006q1 … 2026q3). 83 keys |
| `filename` | text | `{key}_form345.zip` |
| `url` | text | Taken from the SEC landing page. Falls back to the two known folders (R1) |

## 2. Raw file and manifest entry

One stored file under `data/raw/` and its line in `data/raw/manifest.jsonl`. Full schema: [contracts/raw-manifest.md](contracts/raw-manifest.md).

| Field | Type | Rule |
|---|---|---|
| `path` | text | Relative to `data/raw/`. Unique across the manifest |
| `source` | enum | `sec_insider_bulk` or `sec_company_tickers` |
| `key` | text | Quarter key, or snapshot date `YYYYMMDD` |
| `url` | text | The URL actually fetched, after redirects |
| `fetched_at` | timestamp (UTC, ISO 8601) | Set when the transfer completes |
| `bytes` | integer > 0 | Must equal the size on disk |
| `sha256` | 64 hex characters | Computed while streaming. Must equal a re-hash |
| `http_last_modified`, `http_etag` | text or null | Recorded when the server sends them |
| `role` | enum | `original` or `refetch` |
| `tool` | text | `sentinel <version>+<git short hash>` |

**Download states (per quarter)**:

```
missing ──fetch──► downloading (.part, hashing) ──complete──► validating (zip CRC + required tables)
   ▲                     │ error / interrupt                     │ invalid
   │                     ▼                                       ▼
   └──────────── .part removed; quarter reported failed ◄───────┘
validating ──ok──► stored: rename to final name, chmod 0444, append manifest line (fsync)
stored ──verify──► ok | mismatch (reported, never replaced) | missing (reported)
```

**Invariants**:
- A file under its final name always has exactly one manifest line with role `original` (or one per refetch), and that line's hash matches the file.
- Manifest lines are never edited or removed.
- A file in `data/raw/` with no manifest line is reported as `unrecorded` and left alone.

## 3. Parameter

One entry in `config/params.yaml`. Full schema: [contracts/params-schema.md](contracts/params-schema.md).

| Field | Type | Rule |
|---|---|---|
| `value` | number, text, date, list or map | The machine-readable value used by code |
| `unit` | text | e.g. `usd`, `calendar_days`, `sessions`, `requests_per_second` |
| `register.parameter` | text | Appendix E *Parameter* cell, verbatim. Registered parameters only |
| `register.value` | text | Appendix E *Value* cell, verbatim |
| `register.sensitivity` | text | Appendix E *Sensitivity* cell, verbatim |
| `sensitivity` | list | Machine-readable variants, where they exist |

**Validation**:
- Every Appendix E row maps to exactly one registered entry, and its verbatim cells equal the document.
- `ops.*` and `provisional.*` entries have no `register` block.

## 4. Secrets and settings

Read from `.env`. Never written anywhere.

| Field | Rule |
|---|---|
| `SEC_USER_AGENT` | Required by SEC commands. Must contain an e-mail address. A warning is shown if it has no name part (the SEC asks for a name and an e-mail) |
| `TIINGO_API` | Optional in this feature. Always redacted in output |

## 5. Scratch tables (provisional DuckDB, `data/provisional/provisional_PROVISIONAL.duckdb`)

Rebuildable at any time. Not a warehouse layer.

| Table | One row per | Key | Columns kept |
|---|---|---|---|
| `p_submission` | Filing | `accession` | `filing_date` (parsed from `DD-MON-YYYY`), `document_type`, `issuer_cik`, `issuer_name`, `symbol_raw`, `aff10b5one` (normalised to true, false or null), `quarter` |
| `p_owner` | Filing × owner | (`accession`, `owner_cik`) | `relationship`, `title`, `is_officer`, `is_director`, `is_ceo_cfo` |
| `p_purchase_line` | Code-P transaction line | (`accession`, `line_sk`) | `security_title`, `trans_date`, `acq_disp`, `shares`, `price`, `fn_ids` (list of footnote IDs from all `*_FN` columns) |
| `p_footnote` | Footnote cited by a P line | (`accession`, `footnote_id`) | `text` |

**Deduplication**: if the same key appears in two quarterly files, the first occurrence in quarter order is kept, and the number of duplicates is reported.

## 6. Gated purchase line

A `p_purchase_line` row with one boolean per pilot gate, evaluated in order. The per-quarter funnel is computed from these flags.

| Gate flag | Passes when |
|---|---|
| `g_purchase` | `TRANS_CODE = 'P'` and `acq_disp = 'A'` |
| `g_original_form4` | `document_type = '4'` |
| `g_common` | The title matches `provisional.common_title_regex` and not `provisional.excluded_title_regex` |
| `g_no_checkbox` | `aff10b5one` is not true |
| `g_no_plan_fn` | No cited footnote matches `provisional.plan_footnote_regex` |
| `g_no_offering_fn` | No cited footnote matches `provisional.offering_footnote_regex` |
| `g_timely` | `filing_date − trans_date` ≤ `g6_timeliness` days, and ≥ 0 |
| `g_price` | `price` ≥ `provisional.price_standin_floor` ($2) |

## 7. Clean filing

One filing whose passing lines total at least the minimum value.

| Field | Rule |
|---|---|
| `accession`, `issuer_cik`, `filing_date` | From the submission |
| `owner_ciks` | The set of all reporting-owner CIKs on the filing |
| `has_ceo_cfo` | Any owner with `is_ceo_cfo` |
| `value_usd` | Σ shares × price over passing lines. Must be ≥ `g6_min_value` ($10,000) |

## 8. Buyer (per window)

A group of clean filings in one issuer's window [T − 13, T] whose `owner_ciks` sets are linked by overlap (connected components). This is computed on the fly and not stored.

## 9. Provisional event

| Field | Rule |
|---|---|
| `issuer_cik` | |
| `group` | `A` or `B1` |
| `signal_date` | The filing date T on which the conditions are first met outside a cooldown |
| `n_buyers` | ≥ 2 for A, exactly 1 for B1 |
| `total_value_usd` | ≥ `cluster_min_value` ($100,000) |
| `member_accessions` | The filings in the window |
| `in_labelled_window` | `signal_date` ≥ `labelled_window_start` |

**Rules**:
- **Cooldown**: no further event in the same group for the same issuer until `signal_date + provisional.cooldown_calendar_days` (91).
- Events before 2016 are kept, because they start cooldowns.
- **B1**: the only buyer in the window has `has_ceo_cfo` on at least one of its filings, and has bought at least $100,000.

## 10. Delisted candidate (the output list)

One company with at least one event from 2006 onward whose CIK is absent from the SEC ticker snapshot. Columns: [contracts/provisional-outputs.md](contracts/provisional-outputs.md).

| Field | Rule |
|---|---|
| `tier` | 1 if the company has at least one A event, otherwise 2 |
| `rank` | Ordered by `tier` ascending, `last_signal_date` descending, `issuer_cik` ascending. Dense, starting at 1 |
| `n_events_labelled` | A + B1 events on or after the labelled-window start |
| `last_ticker` | Non-blank symbol from the company's latest filing of any form |
| `all_tickers` | Distinct normalised symbols, sorted |
| `tiingo_match` | `matched`, `ticker_only`, `unmatched` or `not_checked` ([research.md](research.md) R5) |
| `tiingo_matched_ticker` | The ticker Tiingo lists the match under (a reported ticker, or its `Q`-suffixed bankruptcy form), otherwise null. No other Tiingo fields are stored |

## 11. Funnel count

One row per quarter × gate: `rows_in`, `rows_out`, `rows_removed`. Must satisfy `rows_in = rows_out + rows_removed`, and each gate's `rows_in` equals the previous gate's `rows_out`.

## 12. Run metadata

One JSON document per candidate run. It records:
- the git commit and SHA-256 of `params.yaml`;
- the manifest hashes of the archives and ticker snapshot used;
- the Tiingo list's Last-Modified time and SHA-256 (not its contents);
- the start and end times and the command line.
