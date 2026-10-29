# Quickstart: validating the daily data refresh

Runnable checks that the feature works end to end, one per success criterion of [spec.md](spec.md).
Commands are in [contracts/cli.md](contracts/cli.md); tables in [data-model.md](data-model.md).
Heavy steps run under the memory cap:

```sh
cap() { systemd-run --user --scope -p MemoryMax=5G "$@"; }
```

## Prerequisites

- `.env` holds `SEC_USER_AGENT`, `FRED_API_KEY`, `TIINGO_API`.
- `data/raw/` holds the stored files; `data/sentinel.duckdb` is built (`sentinel build` per layer).
- Nothing else holds `data/sentinel.duckdb` open (close notebooks that use it).

## 1. The one-off refresh (SC-001, SC-002, SC-003)

```sh
uv run sentinel fetch sec-tickers
cap uv run sentinel fetch yahoo --full-missing     # every listed symbol never asked
uv run sentinel fetch sec-bulk                     # a new base of filings and financial values
cap uv run sentinel fetch form4 --from 2026-10-01  # Form 4s since the last quarterly data set
cap uv run sentinel update
uv run sentinel status
```

Expected:

- `status` shows prices, the calendar and short volume ending on the last completed trading
  session; filings, financial values and insider filings on the last filing day indexed.
- The coverage summary shows every SEC-listed symbol asked of Yahoo, and the unpriced listed
  companies (373 before) reduced to those no source has data for, each with a reason.
- Price-only stocks: at least 450 of the 636 priced on 29 October have prices from before 2025.
  Hitachi (CIK 47710) starts in April 2012 or earlier, Deutsche Telekom (946770) in June 2010 or
  earlier; Standard Life (abrdn) and NGK Spark Plug (Niterra) are priced.
- `tests/real` passes (`uv run pytest tests/real`).

## 2. The daily update equals a full rebuild (SC-005)

```sh
cap uv run sentinel verify
```

Expected: "all tables identical", exit 0.

## 3. A second run the same day changes nothing (SC-006)

```sh
cap uv run sentinel update
uv run sentinel status --runs 1
```

Expected: status `nothing_new`; every `app` table 0 added, 0 changed, 0 removed; every build table
with the same checksum.

## 4. Insider trades the evening after filing (SC-007)

After an update, pick a Form 4 from the latest indexed filing day in `app.insider_activity`
(`filing_date` = that day). Expected: it is there, with the person, role, value and `known_at`
(the filing day when accepted before 4 pm New York time on a session, otherwise the next session).

Parser check against a quarterly data set: fetch the daily submissions for a past quarter's last
week and run the reconciliation; expected: no differences in `core.form4_reconciliation` beyond
those the report explains.

## 5. Speed (SC-004)

`sentinel status` after a weekday update: duration 30 minutes or less.

## 6. The schedule (SC-008)

```sh
uv run sentinel schedule install
uv run sentinel schedule show
```

Expected: the task `EDGAR-SENTINEL\daily update`, next run on the next weekday at 23:00. After two
weekday evenings with the computer on, `sentinel status --runs 2` shows two scheduled runs. Turn the
computer off over one evening; the next start runs the update, and its run covers the missed day.

## 7. Limits (SC-009)

The run log lists requests per source; the tests check that each fetcher waits between requests
(SEC at most 10 a second) and that Tiingo is never asked outside the paid plan.

## 8. The unit tests

```sh
uv run pytest -q
```

Includes the synthetic checks: an update on day D equals a full rebuild; a rerun changes nothing;
missed days are caught up in order; a failing source leaves the others; the truncation test; the
Form 4 parser against a quarterly data set's rows; the newest-file-wins staging rules.
