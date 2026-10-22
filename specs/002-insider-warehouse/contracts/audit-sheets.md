# Contract: Hand-Audit Sheets (FR-025, SC-004)

`sentinel audit sheets` writes three UTF-8 CSVs to `specs/002-insider-warehouse/audits/`.
- **Seed**: fixed at 2002, and recorded in each file's first data column.
- **No accidental overwrites**: existing sheets are kept unless `--force` is given, so completed verdicts are never lost.
- **Committed**: the files hold public SEC data only, so they are committed with the feature.

## Common columns (last two are filled in by the researcher)

| Column | Content |
|---|---|
| `seed` | 2002 |
| `n` | 1–50 |
| `edgar_link` | `https://www.sec.gov/Archives/edgar/data/{issuer_cik}/{accession without dashes}/` |
| `verdict` | Blank. The researcher enters `correct`, `wrong` or `unclear` |
| `notes` | Blank. Free text |

## `entities.csv`: 50 random multi-member entities

The sample is drawn from entities that have at least 2 members at their latest date.

| Column | Content |
|---|---|
| `issuer_cik`, `issuer_name`, `entity_id`, `as_of` | Entity at its latest membership date |
| `members` | `owner_cik: owner_name (role)` entries separated by ` | ` |
| `linking_accessions` | The filings whose co-filing merged the members, with dates |

**The question to answer**: are these owners really one economic decision-maker, such as a fund with its general partner and manager, or spouses or family trusts?

## `gates_excluded.csv`: 50 random purchase lines excluded by G3–G6

These are code-P acquisition lines on original Form 4s that failed a later gate. The sample is stratified by the deciding gate, about 10 each for G3, G4a/G4b, G5 and G6a, plus G6b at filing level.

| Column | Content |
|---|---|
| `accession`, `line_sk`, `issuer_name`, `filing_date`, `security_title`, `shares`, `price` | The line |
| `deciding_gate` | The first gate it failed |
| `cited_footnotes` | The text of the cited footnotes, truncated to 500 characters |

**The question to answer**: was it right to exclude this purchase?

## `gates_kept.csv`: 50 random clean purchases

| Column | Content |
|---|---|
| `accession`, `issuer_name`, `filing_date`, `entity_role`, `value_usd`, `shares_before`, `shares_after` | The clean purchase |
| `cited_footnotes` | All footnote text cited by its lines |

**The question to answer**: is this a genuine, discretionary open-market purchase, and are the role and the holdings right?

## `sentinel audit summary`

- **Output**: per sheet, the counts of `correct`, `wrong`, `unclear` and blank, and the agreement rate = correct ÷ (correct + wrong).
- **Exit code**: 1 if any verdict is blank.
- **Pass mark (SC-004)**: agreement ≥ 90% per sheet.
- **Recording**: the researcher copies the output into `run-notes.md`, together with the error patterns found and any fixes.
