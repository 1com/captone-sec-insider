# Research: Daily data refresh

Phase 0 of [plan.md](plan.md). Each decision states what was chosen, why, and what else was
considered. Facts marked *(checked 29 Oct)* were verified on live data or the build database.

## R1. Download commands: port v1's fetchers into the raw layer

**Decision**: Port v1's downloaders (tag `v1-final`, `src/sentinel/ingest/`) into
`src/sentinel/raw/`, one module per source, behind one command `sentinel fetch <source>`. Every
module keeps v1's guarantees: a file is written under a temporary name, checked, then renamed and
made read-only; one manifest line per stored file (URL without secrets); a rerun skips what is
stored; failures are reported, never stored. Daily files go under
`data/raw/<source>/daily/<YYYY-MM-DD>/` (as `docs/architecture.md` already states); text answers are
stored gzip-compressed with `mtime=0`, so the same answer always gives the same bytes.

**Rationale**: v1's fetchers ran for weeks against the same providers and limits; porting keeps
their tested behaviour (retries, rate limiting, `.part` files, absent lists) and v2 already has the
shared `raw/http.py` and `raw/manifest.py`.

**Alternatives considered**: rewriting the fetchers from scratch (loses tested edge cases); one
generic fetcher driven by configuration (the sources differ too much: bulk zips, per-filing pages,
batch price downloads, API pagination).

## R2. Finding each day's new SEC filings

**Decision**: Read the SEC's nightly master index for each filing day,
`https://www.sec.gov/Archives/edgar/daily-index/<YYYY>/QTR<n>/master.<YYYYMMDD>.idx`
(`CIK|Company Name|Form Type|Date Filed|File Name`), and fetch from it only what the platform uses.
*(checked 29 Oct: the 28 October index holds 4,473 filings, of them 505 Form 4, 4 Form 4/A, 85
Form 3, 389 8-K and 168 10-Q.)* Days are filing days; an index that is not yet published is retried
on the next run.

**Rationale**: one small request per day lists every filing with its form and file; everything
else is fetched per filing, so a day costs about 1,000–1,500 requests (2–3 minutes at 8 per second).

**Alternatives considered**: re-downloading `submissions.zip` and `companyfacts.zip` every day
(about 3 GB a day stored unchanged, roughly 90 GB a month); the "latest filings" Atom feed (pages
of 100 entries, easy to miss filings, no per-day completeness).

## R3. Form 4 filings as they are filed

**Decision**: For each Form 3, 4, 5 and their amendments in a day's index, fetch the full submission
text (`…/<accession>.txt`, about 5 KB) and store it gzip-compressed. It carries both the SEC header,
with the acceptance time, and the `ownershipDocument` XML. *(checked 29 Oct: a 28 October Form 4
had `ACCEPTANCE-DATETIME 20261028165703` and schema `X0609`.)* A new staging module parses the XML
into tables with the same columns as the quarterly data sets (`stg_sec_form4_daily.submission`,
`reportingowner`, `nonderiv_trans`, `nonderiv_holding`, `deriv_trans`, `deriv_holding`,
`footnotes`, `owner_signature`), so `core.insider_*` reads both through one union. `known_at` uses
the acceptance time (the same day when accepted before the 4 pm close on a session), which the
quarterly data sets lack.

Reconciliation: an accession in a quarterly data set is taken from the data set; daily rows are used
only for accessions no data set holds yet. A check table lists accessions whose two versions differ
(owners, line counts, values). The parser is validated by parsing a past quarter's filings and
comparing them with that quarter's data set (named real check).

**Rationale**: about 600 requests a day; the data sets are derived from these same documents, so a
parser can match them exactly; v1 never parsed the documents (it read the quarterly sets only).

**Alternatives considered**: waiting for the quarterly data sets (up to three months late); the
filing index pages plus the XML (two requests per filing, no gain); third-party insider feeds
(licensing, not the primary source).

## R4. Company filings and filer details each day

**Decision**: The newest stored `submissions.zip` stays the base of `stg_sec_filings`. Each day adds
the index rows of company-like filers (form, filing date, accession). For the forms whose details
the platform uses (8-K and its 8-K items, 10-Q, 10-K, 10-KT, 20-F, 40-F, 6-K and amendments: about
600–700 a day), v1's header fetcher adds the 8-K items, the period of report and the acceptance
time. A CIK that the base does not know (a new registrant) gets its submissions document fetched
once, for its name, SIC, entity type and tickers. Base rows win for accessions the base holds; daily
rows fill the rest. A new base (`sentinel fetch sec-bulk`) is only needed for a full refresh.

**Rationale**: forms counted by the features (offerings, late filings, 13D, EFFECT) need only the
form and date from the index; the details matter only for results releases and report dates.

**Alternatives considered**: per-company submissions documents for every filer of the day (about
3,000 requests and 100+ MB a day); headers for every filing (doubles the requests for no use).

## R5. Financial values each day

**Decision**: For each company that filed a periodic report (10-Q, 10-K, 10-KT, 20-F, 40-F and
amendments) that day, fetch its `companyfacts` document from the SEC's API
(`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`), stored gzip-compressed. Staging
takes, per company, the newest document (the bulk zip or a later per-company file): each document
holds the company's whole history, so the newest one is complete.

**Rationale**: 50–500 companies a day (more in results season); the API updates within minutes of a
filing.

**Alternatives considered**: the daily bulk zip (1.4 GB a day stored unchanged); per-concept API
calls (21 items × companies, far more requests).

## R6. Yahoo prices: complete once, then daily

**Decision**:
- *Universe*: every ticker in the latest SEC list (10,443 symbols *(checked 29 Oct)*), plus SPY and
  IWM.
- *Once*: full history from 2010 for every symbol never asked (about 1,600: Yahoo files exist for
  8,844 of the 10,443 *(checked 29 Oct)*); symbols Yahoo has no data for are recorded, as in v1.
- *Daily*: one download of the last 10 calendar days for every symbol, in batches of 200 with
  pauses, stored per batch under `yahoo/daily/<date>/`.
- *Splits and dividends*: Yahoo rewrites past values after them (its `Close` is split-adjusted, its
  `Adj Close` also dividend-adjusted). When a symbol's daily window shows a split or a dividend, its
  full history is downloaded again and becomes its new base file. Staging keeps, per symbol and
  session, the value from the newest file, with the newest full-history file as the base, so the
  provider's adjustments stay consistent and `core` is unchanged.

**Rationale**: a short window per day is about 50 batches (5–7 minutes); full refetches happen only
for the 1–3% of symbols with an event that day; keeping the provider's adjustment avoids a second
adjustment method that could disagree with the one used so far.

**Alternatives considered**: computing our own adjusted series from as-traded closes, dividends and
splits (removes refetches, but changes every return v2 has built and needs its own validation);
full history for every symbol every day (about 10,000 downloads a day).

## R7. Tiingo while the plan lasts

**Decision**: Each day until 26 November 2026, fetch new days (from the last stored date) for the
listed companies priced from Tiingo (1,085 *(checked 29 Oct)*), at 2 requests a second, with a full
refetch after a split or dividend (`splitFactor` ≠ 1 or `divCash` ≠ 0), as for Yahoo. The code
refuses Tiingo requests outside `[paid_from, paid_until)` (`config/sources.yaml`); afterwards the
fetch reports "plan ended" and the coverage report flags the companies that depend on Tiingo alone.

**Rationale**: these companies have no other daily source; about 9 minutes a day, run alongside the
other sources.

**Alternatives considered**: every listed Tiingo symbol daily as a cross-check (6,877 companies,
about an hour a day at 2 per second); no daily Tiingo (those 1,085 companies would go stale at once).

## R8. Market and economic sources

**Decision**: As v1: one dated copy of each FRED series a day (market series in full; CPI and
unemployment as first releases from ALFRED), the full Cboe VIX history file each day, FINRA's
short-volume file per facility and trading day (a missing file goes to the absent list), and the
SEC's company–ticker list once a day. Staging keeps the newest copy for FRED and the VIX and appends
new FINRA days. FINRA publishes in the US evening, after a Berlin-evening run; the next run collects
it.

**Rationale**: all are small (under 10 MB a day together) and v1's behaviour already fits daily use.

**Alternatives considered**: requesting only new FRED observations (saves bytes, but a series'
vintages are then spread over many files and harder to check).

## R9. The trading calendar

**Decision**: The calendar stays SPY's sessions (`ref.calendar`), now extended daily by SPY's daily
rows. The update checks that the calendar's last day is not older than the newest session in the
day's price files; if SPY is missing, the run is partial and says so, instead of silently dropping
new days.

**Rationale**: the 23 October stop happened because SPY's file was older than the rest; a guard
makes that visible.

**Alternatives considered**: an exchange-holiday library (a new dependency; SPY is the market's own
record of sessions).

## R10. Making the update equal a full rebuild

**Decision**: Staging is a deterministic function of the stored files (each source: the base plus
newer files, newest wins per key), so it is the same whether built at once or file by file. The
update re-stages only the sources with new files; quarterly Form 4 sets, the bulk submissions and
companyfacts bases are re-staged only when a new base arrives. Reference, core, features, labels,
the serving copy and the export are rebuilt in full each run (about 15 minutes *(measured on the
29 October build: core 6.1, features 6.2, labels 1.1, publish and export 0.5)*). Equality is checked
by an order-independent checksum of every table (row count and XOR of row hashes) between the
updated database and a full rebuild into a scratch database (`sentinel verify`).

**Rationale**: a full rebuild above staging is exact by construction and fits the time budget;
making features incremental can come later if needed.

**Alternatives considered**: incremental core and features (faster, but each step then needs its
own proof of equality); a full rebuild of everything each night (re-staging 83 Form 4 quarters and
990,151 filers takes more than the 30-minute budget).

**Time budget (weekday)**: fetching in parallel by source, about 9 minutes while Tiingo runs (6
after 26 November); staging the new files, about 3; rebuild and publish, about 15; total about 27
minutes against SC-004's 30.

## R11. What changed: the run log

**Decision**: Before publishing, the previous serving copy is kept; after publishing, each `app`
table is compared with it by its key (rows added, changed, removed), and every build table gets its
checksum. The run's record goes to schema `ops` in the build database (`ops.update_run`,
`ops.update_source`, `ops.update_table`, `ops.coverage`) and to a text log
`data/logs/update-<date>.log`. `sentinel status` reads them.

**Rationale**: the product's tables are what users see; checksums prove "nothing changed" cheaply on
the large build tables.

**Alternatives considered**: keyed diffs of every build table (doubles disk use during a run).

## R12. Prices for renamed companies and the price-only history

**Decision**: For a listed company, the ticker that today's SEC list assigns to it is evidence of
identity: its series from either source is accepted without comparing company names (the date
check stays). Its history starts at the latest of: 1 January 2010; the start of the ticker's current
listing (the entry in Tiingo's ticker list whose dates reach today, or the first day the provider
has); and the day after another company last used the symbol (`ref.ticker_history`, Tiingo's ticker
list). The 400-day warm-up before a company's first evidence keeps applying to companies known only
from filings.

**Rationale**: the SEC's list is the authority on who holds a ticker today; the name check exists
for tickers found by Form 4 symbols and name searches, not for the SEC's own list. *(checked 29 Oct:
the price-only series reach back a median of eight years, 476 of 636 before 2025; Hitachi's Tiingo
series starts 27 April 2012, Deutsche Telekom's 21 June 2010.)*

**Alternatives considered**: a hand-made list of renames (stale at once); dropping the trim for
price-only stocks (would attach a reused ticker's earlier company).

## R13. Running on a schedule on this machine

**Decision**: A task in Windows Task Scheduler, created by `sentinel schedule install`, runs
`wsl.exe -d Ubuntu --cd /home/hashim/big_projects/capstone -- /home/hashim/.local/bin/uv run
sentinel update --scheduled` on weekdays at 23:00 local time (Berlin), with "run as soon as possible
after a missed start" set, so a run missed while the computer was off happens at the next start;
the update itself catches up every missed day (R10). The task is defined in an XML file the command
writes and imports with `schtasks.exe`. Inside, the update runs under the same 5 GB memory cap as
manual builds.

**Rationale**: *(checked 29 Oct: WSL runs systemd and can call `schtasks.exe` and `wsl.exe`.)* A
Windows task starts WSL when it is not running; a WSL timer fires only while WSL is up.

**Alternatives considered**: a systemd user timer with `Persistent=true` (simpler inside Linux,
but it never fires while WSL is shut down, which is the normal state when no terminal is open);
cron (same limitation, no catch-up).

## R14. Safety rails

**Decision**: one update at a time (a lock file with the process id, plus DuckDB's single-writer
lock: a notebook holding the database makes the run stop with that reason); a run refuses to start
with less than 20 GB of free disk; the serving copy and the export are swapped in whole (as today).

**Rationale**: FR-021, FR-026 and the edge cases of the spec.

## R15. Storage growth

**Decision**: accept about 30–130 MB of new raw files per weekday (Yahoo windows 5 MB, Form 4
submissions 4 MB, headers 3 MB, companyfacts 10–100 MB in results season, Tiingo 1 MB, the rest
under 10 MB): about 10–30 GB a year against 868 GB free *(checked 29 Oct)*. Each run logs the
growth.

## R16. Spec consistency: labels in the daily update

**Decision**: FR-022 is reworded: the update never computes an answer whose window ends after the
development cut-off (the holdout stays sealed); development answers are rebuilt by the same
registered step like everything else, so the update still equals a full rebuild (FR-015), and any
change to them (a revision of past data) is reported in the run log.

**Rationale**: "never change a label" and "equal a full rebuild" conflict when a provider revises
past prices; the registered step and the lock already protect the holdout.
