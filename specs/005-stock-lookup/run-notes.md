# Run Notes: Feature 005

Results of the real run (tasks T033 and T034), 2026-10-24. Heavy steps ran under `systemd-run --user -p MemoryMax=5G -p MemorySwapMax=1G`, with DuckDB capped at 3 GB.

## `sentinel lookup`

| Table | Rows |
|---|---|
| `lookup.issuer_search` | 20,899 |
| `lookup.filing_owner` | 4,874,337 |
| `lookup.transaction` | 7,353,719 |
| `lookup.footnote` | 4,667,292 |
| `lookup.holding` | 5,831,146 |
| `lookup.event` | 39,498 |
| `lookup.event_member` | 70,831 |
| `lookup.meta` | 1 |

- Data as of 2026-09-30 (SEC data set 2026q3).
- `data/lookup.duckdb`: 1,131 MB. Built in 35 s. Peak memory 4.7 GB, measured by systemd, which includes the page cache of the 5 GB warehouse file.
- Events: all 39,498 SEC-only events in the filings, signal dates 3 Jan 2006 to 30 Sep 2026 (A 15,391, B1 6,498, B2 17,609). The study's counts (feature 004) are lower because they keep only the labelled window and apply the price and company-type checks. The page says so.

### Two changes made during the run

The first two builds ran out of memory at the 3 GB DuckDB limit. DuckDB keeps list and text aggregate states in memory and cannot spill them to disk.

1. **Owners on each line.** The first design stored each filing's owners as a list on every transaction line (7.4 million lines), and building those lists failed. Owners are now read from `lookup.filing_owner` for the 100 lines of the page being served. The page and the JSON are unchanged; data-model.md is updated.
2. **Footnotes.** "First quarter wins" used `arg_min(text, quarter)` over 9.5 million footnotes, and that failed too. On the real data, `(accession, footnote_id)` never repeats across quarters (checked: 0 repeats), so footnotes are now joined on the filing's own quarter from `core.filing`, the warehouse's rule for the canonical copy.

The builder also spills large sorts to `data/lookup.duckdb.tmp` (deleted afterwards), because `/tmp` is a small RAM disk. It uses 2 threads and does not preserve insertion order; every table's order comes from its `ORDER BY`.

## Slow tests (T033)

`uv run pytest -m slow tests/integration/test_lookup_real.py`: 7 passed in 0.75 s.

| Check | Result |
|---|---|
| SC-003: every code in `lookup.transaction` has a description | Passed (codes A, C, D, E, F, G, H, I, J, L, M, O, P, S, U, W, X, Z and blank) |
| SC-001: `PYPL`, `paypal`, `1633917` find PayPal first; `SIVB` finds SVB Financial Group (CIK 719739) | Passed |
| SC-002: largest company (Google Inc., CIK 1288776, 76,529 lines), page and JSON | 0.08 s (limit 2 s) |
| SC-007: PayPal cluster of 23 Nov 2021 and Dorman's holdings | Passed |

## Checks by hand with `sentinel serve` (quickstart.md)

| # | Check | Result |
|---|---|---|
| 1 | Search `PYPL`, `paypal`, `1633917` | PayPal Holdings, Inc. first each time; 0.01 s per search after the first (0.16 s) |
| 2 | Old ticker `SIVB` | SVB FINANCIAL GROUP, tickers SIVBQ (current), SIVB, SVB |
| 3 | PayPal transactions | "Data as of 30 Sep 2026 · SEC data set 2026 Q3"; 1,942 lines. On page 6: five lines for DORMAN DAVID W, Director, code P "Bought shares on the open market or privately", 495, 605, 150, 72 and 225 shares at $186.47, held indirectly by "2021 Family Trust 1" to "5", link to accession 0001633917-21-000185 |
| 4 | Dorman's holdings, 23 Nov 2021 | 44,890 held directly, 1,547 indirectly, 46,437 total; the six holdings listed |
| 5 | Events | Cluster, signal date 23 Nov 2021, 2 buyers, $2,287,696.69, most senior buyer Director; members Donahoe John J ($1,999,227.60, 17 Nov) and DORMAN DAVID W ($288,469.09, 23 Nov), each with its EDGAR link; no return or outcome |
| 6 | Paging, Google Inc. (766 pages) | First page 0.035 s; pages 2, 383 and 766 as HTMX fragments in 0.02–0.04 s |
| 7 | Glossary | Every code on the PayPal page (A, F, M, P, S) has an entry |
| 8 | EDGAR links (SC-006) | 20 of 20 open the right filing: 20 companies drawn at random (seed 2005), one line each, fetched at one request per second with the SEC User-Agent; each folder page names the accession |

- **API**: `/api/issuers/1633917/transactions?page=1&page_size=2` returns `data_as_of`, the issuer and two transactions with every contract field. `/docs` returns 404.
- **Port in use**: a second `sentinel serve` stops with "port 8766 is in use: choose another with --port".

## Observation

PayPal's current CFO is shown as "Officer (EVP, Chief Fin & Op Officer)", not "CEO or CFO". Roles come from feature 002's rules (`core.owner_role`), and those rules don't recognise this wording of the title. The page shows the title, so a reader can see the role. Changing the rules would change the study's roles, so that is left to the study's own process, not this feature.
