# Contract: raw file layout

Where each source's files are stored under `data/raw/`, and the manifest `source` and `key` of each.
Existing files keep their paths; new files follow the same conventions (dated copies for whole
files, year folders for per-filing SEC files). New text files are gzip-compressed with `mtime=0`.
`<date>` is the fetch day (`YYYY-MM-DD`); `<day>` a filing or trading day (`YYYYMMDD`).

| What | Manifest `source` | Path | Key | New? |
|---|---|---|---|---|
| Quarterly Form 3/4/5 data set | `sec_insider_bulk` | `sec/insider/<YYYY>q<N>_form345.zip` | `<YYYY>q<N>` | existing |
| SEC filings index of a day | `sec_index` | `sec/index/<YYYY>/master.<day>.idx.gz` | `master/<day>` | new |
| Form 3/4/5 full submission | `sec_ownership_filing` | `sec/form4/<YYYY>/<accession>.txt.gz` | `<accession>` | new |
| Filing header | `sec_filing_header` | `sec/headers/<YYYY>/<accession>.txt` | `<accession>` | existing pattern |
| Bulk filing histories and financial values | `sec_company` | `sec/company/companyfacts.zip`, `sec/company/submissions.zip` (23 Oct); new copies `sec/company/<date>/<name>.zip` | `companyfacts`, `submissions`; new `companyfacts/<date>`, `submissions/<date>` | new copies |
| One company's financial values | `sec_companyfacts_cik` | `sec/companyfacts/<date>/CIK<10 digits>.json.gz` | `<cik>/<date>` | new |
| One company's filing history (new registrants) | `sec_submissions_cik` | `sec/submissions/<date>/CIK<10 digits>.json.gz` | `<cik>/<date>` | new |
| SEC company–ticker list | `sec_company_tickers` | `sec/reference/company_tickers_exchange_<day>.json` | `<day>` | existing pattern, daily |
| Yahoo full history (v1) | `yahoo` | `yahoo/<T>.parquet`, `yahoo/panel/<T>.parquet` | `<T>`, `panel/<T>` | existing |
| Yahoo full history (new or after a split or dividend) | `yahoo` | `yahoo/history/<date>/<T>.parquet` | `history/<T>/<date>` | new |
| Yahoo daily window (all listed symbols) | `yahoo` | `yahoo/daily/<date>/batch-<NNN>.parquet` (long format, a `ticker` column) | `daily/<date>/<NNN>` | new |
| Tiingo prices (v1 and 29 Oct) | `tiingo` | `tiingo/{prices,panel_prices,listed_prices}/<T>.csv.gz` | as stored | existing |
| Tiingo new days | `tiingo` | `tiingo/daily/<date>/<T>.csv.gz` | `daily/<date>/<T>` | new |
| Tiingo full history after a split or dividend | `tiingo` | `tiingo/history/<date>/<T>.csv.gz` | `history/<T>/<date>` | new |
| FRED series | `fred` | `fred/<SERIES>-<mode>-<date>.json` (new copies `.json.gz`) | `<SERIES>-<mode>-<date>` | existing pattern |
| Cboe VIX history | `cboe` | `cboe/VIX_History-<date>.csv` (new copies `.csv.gz`) | `VIX_History-<date>` | existing pattern |
| FINRA short volume | `finra_short` | `finra/short_volume/<FACILITY>/<day>.txt.gz`; `finra/short_volume/absent.csv` | `<FACILITY>/<day>` | existing |
| SIC ranges (French) | `french` | `french/Siccodes{12,49}.zip` | file name | existing |

**Rules**

- A stored file is never overwritten or edited; a newer copy gets a new path and key.
- Staging reads only files with a manifest line, and checks size and SHA-256 before use.
- Secrets never appear in a path, key, URL or log line.
- Tiingo files are written only on days inside `[tiingo.paid_from, tiingo.paid_until)`.
