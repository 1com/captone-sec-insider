# Research: Project Skeleton, SEC Insider-Data Ingest and Provisional Delisted-Candidate List

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-22

All findings below come from live checks run on 2026-10-22: the SEC download page, four sample quarters (2006 Q1, 2019 Q1, 2023 Q2, 2026 Q3) downloaded to a scratch folder, the SEC ticker map, Tiingo's public ticker list (read in memory only), and PyPI. No project data was written.

## R1. Where the 83 quarterly files live

- **Decision**: read the file links from the SEC's [Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) page in one request. If a quarter is missing from the page, try the two known folder patterns directly.
- **Findings**:
  - The page links exactly 83 files, `2006q1_form345.zip` to `2026q3_form345.zip`.
  - 81 files (2006 Q1 – 2026 Q1) are under `/files/structureddata/data/insider-transactions-data-sets/`.
  - 2026 Q2 and 2026 Q3 are under `/files/datastandardsinnovation/data/insider-transactions-data-sets/`.
  - Sizes run from 8.0 MB (2025 Q3) to 17.3 MB (2006 Q1), **0.93 GB in total**.
- **Rationale**: the SEC has already moved files between folders once. Reading the page makes the downloader follow future moves instead of hard-coding them, and the fallback covers a page-layout change.
- **Alternatives considered**: hard-coding one pattern per quarter range breaks on the next move. Trying both patterns for every quarter adds up to 83 wasted requests.

## R2. Archive contents and format drift

- **Decision**: treat every table as tab-separated, UTF-8, **with quoting disabled**, reading every column as text. Required members, checked before a file is accepted: `SUBMISSION.tsv`, `REPORTINGOWNER.tsv`, `NONDERIV_TRANS.tsv` and `FOOTNOTES.tsv`.
- **Findings**:
  - Every sample has the same eight tables. The metadata and readme files were renamed between 2019 and 2023 (`insider_transactions_metadata.json` → `FORM_345_metadata.json`), so they are not required.
  - All four samples decode as strict UTF-8, and every line has the same field count as its header, so there are no embedded tabs or newlines.
  - Fields do contain literal `"` characters (up to 3,664 per quarter in `FOOTNOTES`). A parser that treats quotes as special would merge rows.
  - Columns are identical from 2006 to 2026 in `REPORTINGOWNER`, `NONDERIV_TRANS` and `FOOTNOTES`. `SUBMISSION` gains one column, `AFF10B5ONE` (the 10b5-1 checkbox), from 2023 onward.
  - `AFF10B5ONE` takes the values `0`, `1`, `false`, `true` and blank. The box counts as ticked when the value is `1` or `true`. Blank or absent counts as not ticked.
  - Dates are formatted `DD-MON-YYYY`, e.g. `31-MAR-2006`.
  - The footnote columns (`*_FN`) hold comma-separated footnote IDs, e.g. `F2, F3, F5, F4`. They join to `FOOTNOTES` on (`ACCESSION_NUMBER`, `FOOTNOTE_ID`).
  - `RPTOWNER_RELATIONSHIP` is a comma-separated set of roles, e.g. `Director,Officer,TenPercentOwner`. Titles are free text, e.g. `President & CEO`, or `See Remarks`.
- **Rationale**: these choices let one reader handle all 83 quarters without per-year special cases, except the checkbox column.

## R3. Can the pilot's gates be reproduced?

- **Decision**: rebuild the simplified gates from Appendix A with the rules below. Measured on 2019 Q1, they reproduce the pilot's funnel almost exactly.

| Gate (2019 Q1) | Pilot (A.1) | Prototype | Gap |
|---|---|---|---|
| Purchase lines (code P, acquired) | 12,796 | 12,796 | 0 |
| On an original Form 4 | 11,938 | 11,938 | 0 |
| Common stock | 12,385 | 12,418 | +0.3% |
| Flagged by plan footnotes | 5,009 | 5,060 | +1.0% |
| Flagged by offering footnotes | 107 | 107 | 0 |

- **Rules used**:
  - **Original Form 4**: `SUBMISSION.DOCUMENT_TYPE = '4'`.
  - **Purchase**: `TRANS_CODE = 'P'` and `TRANS_ACQUIRED_DISP_CD = 'A'`.
  - **Common stock**: the security title matches `common | ordinary | class X | share(s)` and does not match `preferred | warrant | unit(s) | note(s) | option | right(s) | debenture`.
  - **Plan footnotes**: `10b5-1` (and its spelling variants), dividend reinvestment, DRIP, employee stock purchase, ESPP, automatic purchase or reinvestment.
  - **Offering footnotes**: public offering, underwrit-, private placement, registered direct, subscription agreement, securities purchase agreement, PIPE, rights offering, directly from the company or issuer.
  - **Footnote scope**: only the footnotes cited in that transaction line's own `*_FN` columns are scanned, as plan §6.2 requires.
- **Rationale**: SC-005 needs agreement within 1%. Three counts match exactly and two are within 1%. The regular expressions live in `config/params.yaml` under `provisional`, so they can be adjusted without code changes.

## R4. How buyers are counted in a cluster

- **Decision**: within each 14-day window, merge filings whose reporting-owner sets overlap. Each resulting group is one buyer. Owners on one joint filing are therefore one buyer, and a fund that files once with its general partner and once alone is still one buyer.
- **Findings**: `NONDERIV_TRANS` is recorded per filing (accession), not per owner, so a joint filing's dollar value belongs to the filing and is counted once.
- **Rationale**: this merges no more than the production rule in §6.3, which uses every co-filing up to T. The provisional cluster set is therefore a superset of the production set on this point. That is the safe direction for a priority list: a company that is wrongly left off is never priced, while one wrongly included only costs a symbol.
- **Alternatives considered**:
  - Counting every owner separately over-counts joint filings, which are 14–16% of clean filings.
  - Merging over the issuer's full history is not point-in-time and merges more than production, so the list could miss companies.

## R5. "Likely delisted" and the Tiingo cross-check

- **Decision**:
  - **Likely delisted** means the CIK is absent from the SEC's `company_tickers_exchange.json`.
  - That file is saved as a dated raw snapshot under `data/raw/sec/reference/` and recorded in the manifest.
  - Tiingo's `supported_tickers.zip` is downloaded **into memory only** during the candidate run and discarded at the end. Only a per-company match flag is kept.
- **Findings**:
  - **SEC ticker map**: 10,443 rows and 8,029 distinct CIKs, with fields `cik, name, ticker, exchange`. Exchanges are Nasdaq 4,372, NYSE 3,273, OTC 2,572, none 172, CBOE 44, TXSE 10.
  - **Tiingo list**: about 0.8 MB, updated daily (Last-Modified 2026-10-22 03:05 GMT), no API key needed. Columns are `ticker, exchange, assetType, priceCurrency, startDate, endDate`.
  - Among US-exchange stocks in the Tiingo list, 8,221 ended before October 2026, consistent with the plan's "about 8,100".
  - **Reused tickers**: 702 tickers appear more than once with different date ranges. Tiingo marks some special listings with suffixes (e.g., `AA-W`, `AAC-U`).
- **Matching rule**:
  1. Normalise SEC symbols: upper case, trimmed, `.` and `/` replaced by `-`. `NONE`, `N/A` and blank count as no ticker.
  2. Compare every distinct symbol the company reported against Tiingo rows that are stocks, priced in USD, on NYSE, NASDAQ, NYSE MKT, AMEX or NYSE ARCA.
  3. **`matched`**: a ticker matches and Tiingo's start–end range overlaps the company's 2016+ event span. **`ticker_only`**: a ticker matches but the dates don't overlap, so it is possibly a reused ticker. **`unmatched`**: no ticker matches. **`not_checked`**: the run used `--no-tiingo`.
- **Rationale**:
  - Matching on CIK avoids errors from reused tickers in the SEC map.
  - The date-overlap test handles reused tickers in Tiingo's list.
  - Keeping the Tiingo list in memory follows ToS §1.6(a). The run metadata records the list's Last-Modified time and SHA-256 hash, so differences between runs can be explained without keeping the list.
- **Consequence**: the Tiingo flag cannot be rebuilt offline. `--no-tiingo` gives a fully offline, deterministic run. The candidate list is provisional and not a key table, so constitution Principle V's offline-rebuild rule is not breached.
- **Revised after the first real run (2026-10-22)**:
  - Tiingo files a delisted company's whole history under its *final* ticker, often a bankruptcy `Q` ticker on an OTC venue (e.g. 2U → `TWOUQ` on `PINK`, history from 2014).
  - Matching therefore uses **every US venue** in the list (NYSE, NASDAQ, NYSE MKT, AMEX, NYSE ARCA, NYSE NAT, BATS, PINK, OTCMKTS, OTCGREY, EXPM, OTCBB, OTCQB, OTCQX, OTCCE, OTCD) and tries `TICKERQ` after `TICKER`.
  - Placeholders such as `[NONE]` and `N/A/` count as no ticker.
  - For 2016, matched coverage rose from 69% to 83%. Details in [run-notes.md](run-notes.md).
- **Known gap against the pilot**: companies that moved from an exchange to OTC stay in the SEC map and are not flagged as delisted. Yahoo usually carries their OTC prices, so they don't need Tiingo. They are counted separately in the summary because they may explain part of any gap against the pilot's 955 + 340.

## R6. Event detection for the provisional list

- **Decision**: follow the pilot (Appendix A.3), run per issuer across quarter boundaries.
  - A signal date T is the filing date of a clean filing.
  - **Cluster (A)**: in the window [T − 13 days, T] there are at least two buyers (R4) and at least $100,000 in total.
  - **Solo CEO/CFO (B1)**: in the same window, the only buyer includes a CEO or CFO and has bought at least $100,000.
  - **Cooldown**: 91 calendar days per issuer and per group, started only by events.
  - Processing starts in 2006 so that the cooldown is correct on 1 January 2016 (FR-018).
- **CEO/CFO test**: the owner's relationship includes `Officer`, and the title matches `\bCEO\b`, `\bCFO\b`, `chief executive`, `chief financial`, `principal executive` or `principal financial` (case-insensitive). `See Remarks` titles are not resolved, as in the pilot.
- **Deduplication**: submissions are keyed by `ACCESSION_NUMBER`, transaction lines by (`ACCESSION_NUMBER`, `NONDERIV_TRANS_SK`).
- **Last reported ticker**: the non-blank `ISSUERTRADINGSYMBOL` from the issuer's latest filing of any form type. Ties are broken by the higher accession number.

## R7. Processing engine for the candidate run

- **Decision**: stream each needed table from its zip with pyarrow's CSV reader (tab-delimited, quoting off, all text) and load it into a file-backed DuckDB scratch database, `data/provisional/provisional_PROVISIONAL.duckdb`. Gates and the funnel run in SQL. Event detection, which needs per-window grouping, runs in Python per issuer on the clean filings (about 190,000 rows according to A.3).
- **Rationale**:
  - DuckDB cannot read inside zip files without a community extension.
  - Streaming through pyarrow avoids extracting about 6 GB of text files to disk.
  - The zip-table reader (`sentinel.ingest.sec_tables`) is general, so Step 2's staging layer can reuse it.
- **Alternatives considered**: extracting to a temporary folder and using DuckDB's `read_csv` costs 6 GB of temporary disk. Plain pandas would be slower and use more memory on `FOOTNOTES`, about 11 million rows in total.

## R8. Downloader behaviour

- **Decision**:
  - **Order**: sequential downloads (the job is limited by bandwidth: about 1 GB in 83 files).
  - **Rate limit**: one shared limiter with a target of 5 requests per second and a hard ceiling of 10.
  - **Streaming**: each file streams to `<name>.part` in the destination folder, with the SHA-256 computed on the fly. The file is then fsynced, its zip CRCs and required members checked, and it is renamed to its final name, made read-only (`0444`) and appended to the manifest.
  - **Retries**: up to 5 attempts with exponential backoff and jitter on HTTP 429, 5xx, timeouts and connection errors, honouring `Retry-After`. HTTP 403 stops the whole run at once.
  - **Locking**: a lock file stops two runs from writing at the same time.
- **Rationale**: this meets FR-009 to FR-015 with the standard library plus httpx. Renaming within the same folder is atomic on Linux, which guarantees FR-011.
- **Manifest**: one append-only JSON Lines file, `data/raw/manifest.jsonl`, for every raw source. One line is written per stored file, then flushed and fsynced. JSON Lines makes appends safe, and the file can be read line by line.

## R9. Libraries and versions (Python 3.14.4, resolved 2026-10-22)

| Package | Pin | Role | Note |
|---|---|---|---|
| httpx | `>=0.28.1,<0.29` | HTTP with timeouts and streaming | Plan §8.3 |
| duckdb | `>=1.5.6,<2` | Scratch SQL engine for the candidate run | **DuckDB 2.0.0 was released on 2026-10-21**, a major version only a day old. Stay on the 1.5 line the plan verified until 2.x has settled |
| pyarrow | `>=25.0.1,<26` | Streaming CSV reader, Parquet | Plan §8.3 verified 25. Version 26.0.0 (2026-10-09) is newer than the plan verified |
| pyyaml | `>=6.0.3,<7` | Reads `config/params.yaml` | Small, standard |
| python-dotenv | `>=1.2.4,<2` | Reads `.env` | Small, standard |
| typer | `>=0.27.3,<0.28` | Command-line interface with help grouped by phase (`rich_help_panel`) | Pulls in click and rich. Grouping 25 commands into labelled phases is the reason over argparse. Not "heavy" under Principle VII; recorded here and in the decision log |
| pytest | `>=9.1.1,<10` (dev) | Tests | Plan §8.3 |
| ruff | `>=0.17.1,<0.18` (dev) | Linting and formatting | Plan §8.3 |
| respx | `>=0.23.1,<0.24` (dev) | Mocks httpx so tests never touch the network | Test-only |

- **Build backend**: `uv_build`, with module name `sentinel` (src layout). The distribution is named `edgar-sentinel` and the console script `sentinel`.

## R10. Parameter file and how it is checked against the register

- **Decision**:
  - Each parameter in `config/params.yaml` that comes from Appendix E carries a `register` block holding the Appendix E row's *Parameter*, *Value* and *Sensitivity* cells verbatim, next to the machine-readable `value`.
  - A test parses the Appendix E table from `docs/initialplan.md` and fails if any row has no matching entry, or if the stored verbatim cells differ from the document.
  - Parameters outside Appendix E sit in two clearly labelled sections, never mixed with registered ones: `ops` (rate limits, retries, timeouts) and `provisional` (the pilot's simplified rules).
- **Rationale**:
  - Comparing "$10,000 per entity per filing" with `10000` automatically would need a fragile prose parser. Comparing the verbatim cells catches every edit to the register (FR-004).
  - Whether each `value` agrees with its verbatim text is a one-time human review, backed by targeted assertions for the values this feature uses.
- **Alternative considered**: generating `params.yaml` from the Markdown table. Rejected, because the table's prose values are not machine-readable.

## R11. Keeping the tests offline

- **Decision**: an autouse pytest fixture blocks socket connections for every test not marked `network`. respx mocks all HTTP calls. Network tests are skipped unless `--run-network` is passed.
- **Rationale**: this meets FR-007 and SC-009 without adding the pytest-socket dependency.
