# Contract: commands

The commands this feature adds to `sentinel`. Exit codes follow the existing CLI: 0 done, 1 failed
(or partial), 2 usage error, 3 configuration error (missing `.env` key, missing tool).

## `sentinel fetch <source> [options]`

Downloads one source into `data/raw/` ([raw-layout.md](raw-layout.md)), one manifest line per
stored file. A rerun skips what is stored; an interrupted run resumes. Prints what it fetched,
skipped and failed.

| `<source>` | Fetches | Options |
|---|---|---|
| `sec-tickers` | today's SEC company–ticker list | |
| `sec-daily` | for each filing day: the master index; headers of company filings with details (8-K, 10-Q, 10-K, 10-KT, 20-F, 40-F, 6-K, amendments); submissions documents of CIKs not seen before; `companyfacts` of periodic-report filers | `--from`, `--to` (filing days; default: the day after the last stored index, to yesterday) |
| `form4` | for each filing day, every Form 3, 4, 5 and amendment in the index (full submission) | `--from`, `--to`; `--quarterly` fetches newly published quarterly data sets instead |
| `sec-bulk` | new copies of `submissions.zip` and `companyfacts.zip` (a new base) | |
| `yahoo` | the 10-day window for every symbol in the latest SEC list plus SPY and IWM; full history again for symbols whose window shows a split or dividend | `--full-missing` also fetches the full history of listed symbols never asked; `--window-days N` |
| `tiingo` | new days for the listed companies priced from Tiingo; full history after a split or dividend. Outside the paid plan: does nothing and says so (exit 0) | |
| `fred` | today's copy of each series | |
| `cboe` | today's copy of the VIX history | |
| `finra` | short-volume files for each trading day not yet stored | `--from` |
| `all` | every source above except `sec-bulk`, sources in parallel, each within its limits | |

Requires: `SEC_USER_AGENT` (SEC sources), `FRED_API_KEY` (`fred`), `TIINGO_API` (`tiingo`) in `.env`.

## `sentinel update [--scheduled] [--no-fetch]`

The daily update. In order: take the lock (stop if another update runs); check free disk (at least
20 GB); `fetch all`; stage the new files; rebuild reference, core, features and labels; check the
calendar against the newest price files; publish `serving.duckdb` and write the export, each
swapped in whole; compare the new serving copy with the previous one; record the run in `ops.*` and
`data/logs/update-<date>.log`.

- `--scheduled`: marks the run as started by the schedule (in `ops.update_run.trigger`).
- `--no-fetch`: skip downloading; use the stored files only (for checks and tests).

Output: one line per source (fetched / nothing new / failed / plan ended) and per layer, then a
summary: status, each dataset's latest date, coverage counts, published changes, duration.

Exit: 0 `complete` or `nothing_new`; 1 `partial` or `failed` (the status line says which).

## `sentinel status [--runs N]`

Prints the last `N` runs (default 5: start, duration, status, failures), each dataset's latest
date, the coverage summary (listed companies by price source; unpriced with reasons; Tiingo-only),
and the schedule's next run if installed. Reads only; never takes the lock. Exit 0.

## `sentinel verify [--keep]`

Rebuilds every layer from the stored files into a scratch database (`data/verify.duckdb`) and
compares each table's row count and checksum with `data/sentinel.duckdb`. Prints the tables that
differ. Exit 0 when identical, 1 otherwise. `--keep` keeps the scratch database. Takes about as
long as a full build.

## `sentinel schedule install|remove|show [--time HH:MM]`

- `install`: writes the task definition (weekdays at `--time`, default 23:00 local; run as soon as
  possible after a missed start; one instance at a time) and registers it in Windows Task Scheduler
  as `EDGAR-SENTINEL\daily update`, running
  `wsl.exe -d <distro> --cd <repo> -- <uv> run sentinel update --scheduled`.
- `remove`: deletes the task.
- `show`: the task's state, last result and next run time.

Exit 3 when Windows Task Scheduler cannot be reached from WSL.
