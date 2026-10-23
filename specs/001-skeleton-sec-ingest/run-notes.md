# Run Notes: Feature 001

Results of the real runs (tasks T018, T033, T044).

## T018: SEC archive download (2026-10-22)

| Check | Result | Criterion |
|---|---|---|
| `fetch-sec --dry-run` | 83 URLs resolved: 81 in `structureddata/`, 2026 Q2 and Q3 in `datastandardsinnovation/` | — |
| `fetch-sec` | stored=83, failed=0, 930.6 MB in **3 min 54 s** | SC-004: under 1 hour ✅ |
| Peak request rate (DEBUG log, 84 requests) | at most **2** requests in any 1-second window | ≤ 10 per second ✅ |
| `verify-sec` | ok=83, mismatch=0, missing=0, unrecorded=0; 83/83 quarters | SC-002 ✅ |
| `fetch-sec` rerun | skipped=83, fetched 0, **0.8 s** | SC-003: under 1 minute ✅ |
| Files on disk | `data/raw/sec/insider/*.zip`, mode `-r--r--r--`, 888 MB | FR-011 ✅ |

## T033: Provisional candidate list (2026-10-22)

`sentinel fetch-sec-tickers` stored `sec/reference/company_tickers_exchange_20261022.json`. A full `candidates-provisional` run takes about 55–80 s: 867,331 code-P lines → 187,394 clean filings (pilot A.3: 189,582, −1.2%) → 21,969 events → **3,560 likely-delisted candidates** (3,203 tier 1).

### Plan §5.2 table (final run, Tiingo list Last-Modified 2026-10-22 03:05 GMT)

| Start | Events (A+B1) | Companies | Delisted, in Tiingo | Delisted, not matched | Likely delisted |
|---|---|---|---|---|---|
| 2006 | 21,969 (+0.3%) | 6,659 (−0.3%) | 2,235 (+12.8%) | 1,325 (+7.5%) | 3,560 |
| 2009 | 17,718 (+0.5%) | 5,561 (0.0%) | 1,924 (+16.1%) | 676 (−4.5%) | 2,600 |
| 2011 | 16,174 (+0.6%) | 5,189 (+0.2%) | 1,772 (+17.0%) | 513 (−10.3%) | 2,285 |
| 2014 | 13,474 (+0.5%) | 4,564 (+0.4%) | 1,465 (+18.7%) | 325 (−21.3%) | 1,790 |
| 2016 | 11,237 (+0.7%) | 4,055 (+0.4%) | 1,152 (+20.6%) | 244 (−28.2%) | 1,396 |

### Why the CHECK marks are acceptable (SC-005, SC-006)

1. **Tiingo columns (2009–2016 rows).** The first run, limited to NYSE/Nasdaq-type venues as in R5, gave 957 matched / 439 unmatched for 2016. Inspection showed why: **Tiingo files a delisted company's whole history under its final ticker, often a bankruptcy `Q` ticker on an OTC venue**. For example, 2U's history since 2014 is under `TWOUQ` on `PINK`, and `TWOU` on Nasdaq is a new listing; WeWork's is under `WEWKQ` on `EXPM`. Matching was widened to every US venue, plus a `Q`-suffix try (122 matches come only from that), and placeholder tickers (`[NONE]`, `N/A/`) are now treated as blank (`params.yaml` version 2). Matched coverage of likely-delisted companies rose from 69% to **83%** for 2016. The pilot used the narrower match, so our matched column is now *above* the pilot's and our unmatched column *below* it. **The total of likely-delisted companies stays within +7.8% (2016) to +10.7% (2006) of the pilot**, and the per-company classification is now the more accurate one.
2. **"Delisted" is defined differently.** Ours: CIK absent from today's SEC ticker map. The pilot classified by reported ticker against Tiingo's list (A.1 note: "blank counted once"). Another 94 companies with 2016+ events are now OTC-only in the SEC map (summary §4). They are not candidates because Yahoo usually carries them.
3. **Remaining unmatched (244 for 2016)** are mostly non-traded BDCs, private-credit and interval funds with no ticker or a mutual-fund-style ticker (e.g. `CRAFX`). They can't be priced from any source and are largely removed later by G7 (SIC 6722/6726). The rest are SPAC-to-company renames whose Tiingo ticker differs from every reported one (e.g. BowX → WeWork → `WEWKQ`). These need the real symbol map (Step 6).
4. **Funnel (A.1).** Purchase lines and original Form 4 counts match exactly in both quarters. The other lines differ by 0.3–1.9%, except offering footnotes in 2023 Q1 (110 vs 118, −8 lines), filings passing G1–G5 (+1.1% / +1.7%) and clean filings (−1.3% / −2.7%). The pilot's code was not kept, so the regex lists are reconstructions. The differences are 8–51 lines per quarter, and the event counts that matter land within 0.7% for 2016. The regexes were **not tuned** to match the pilot, which is not ground truth. The production gates (Step 4) get their own hand audit of 50 excluded and 50 kept lines.
5. **Per-year B1 counts** run 0–10% above A.3, probably because the CEO/CFO regex also catches "principal executive/financial officer". All are within ±15%. Cluster counts are within −4.2% to +1.1% in every year.

### Other checks

- **SC-007 (determinism)**: two `--no-tiingo` runs gave an identical CSV (sha256 `37adf2bd0b1b3bbc…`) ✅
- **Tiingo storage**: `find data -iname '*tiingo*'` → 0 files ✅
- **Budget**: no longer binding. The one-month Tiingo Power plan (decision D39) covers about 2,235 matched symbols, so the window start can be chosen on research grounds before `prereg-v1`.

## T043–T044: Lint, tests and quickstart walk-through (2026-10-22)

| Quickstart step | Result |
|---|---|
| `uv sync`, `sentinel --help` | Every step from 0 to 21 plus P, in 5 phase panels ✅ (SC-001) |
| `sentinel check` | 7 × OK; exit 0 ✅ |
| `sentinel stage` | "not yet implemented — plan Step 2"; exit 4 ✅ |
| `uv run pytest` (offline) | 85 passed, 1 network test skipped ✅ (FR-007) |
| `uv run pytest --run-network tests/network` | 1 passed (live HEAD request to the SEC with the contact) ✅ |
| `ruff check` / `ruff format --check` | All checks passed; 30 files formatted ✅ |
| `git ls-files .env` | empty ✅ |
| Tiingo key in git history or any repo file outside `.env` | 0 occurrences ✅ (SC-009) |
| `fetch-sec` rerun / `verify-sec` | skipped=83 / ok=84 (83 archives + 1 ticker snapshot), 83/83 quarters ✅ |
| Manifest | 84 lines ✅ |
| Resume after interruption | Covered by `test_interrupted_quarter_resumes_and_stale_part_is_removed`. Not repeated live, because the stored archives are read-only and must not be deleted |
| Determinism / no Tiingo files | See T033 ✅ |
