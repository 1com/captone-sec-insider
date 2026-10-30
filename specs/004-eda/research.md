# Research: EDA and data-quality report

## R1. Error measures the EDA reports

**Decision**: the EDA reports, for information only (the model features choose their own measure
under D60):

- **Volatility**: errors on the log of volatility (the answer is modelled as its log,
  `risk_params` v5): mean absolute error and root mean squared error of `log(vol_63)` against
  `log(vol_63_future)`, plus Spearman rank correlation; also the share of rows where the future
  falls inside the naive range ±25%.
- **Results-day move**: mean and median absolute error of `prev4_mean` against `move`, Spearman
  rank correlation, and the same for a constant (the training median) as a floor.
- **Dilution**: base rate; for single features and simple rules the area under the ROC curve (AUC),
  lift in the top decile, and the Brier score of the base rate.

**Rationale**: these are the standard measures for a positive skewed amount (log errors), a size
(absolute errors, ranks) and a rare yes/no (AUC, lift, Brier). Reporting several keeps the EDA from
pre-empting 005–007.

**Alternatives considered**: QLIKE for volatility (common in finance; noted as an option for 005);
pinball loss for ranges (belongs to calibration in 005).

## R2. Development rows only

**Decision**: every notebook keeps rows with `as_of <= 2022-12-31` and drops the rest on load. Rows
with a missing answer are counted and then left out of every relation to the answer. Test years
2019–2022 are shown separately where a measure is given per year.

**Rationale**: the export already holds answers only for windows ending by 2022-12-31; the filter
guarantees no holdout row is explored even if the export changes.

## R3. Memory

**Decision**: load with pyarrow, only the needed columns where a section needs few; convert float
features to float32 for the correlation tables; the largest file (734,203 × 110) is about 0.6 GB as
float64, so whole-file loads fit the 5 GB cap. Each notebook runs under
`systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0`.

**Rationale**: measured sizes; no sampling needed for counts, a fixed-seed sample (200,000 rows)
only for scatter plots.

## R4. Shared helpers in the package

**Decision**: `src/sentinel/eda.py` holds the helpers the three notebooks share: `load(name)` (the
development rows of one training set), `FAMILIES` (each feature's family by name), `missing_table`,
`extremes_table`, `rank_table` (Spearman with the answer, overall and per year), `decile_table`,
`redundant_pairs`, `purge_table`. Unit-tested on synthetic frames.

**Rationale**: the same method in three notebooks; tested code instead of copied cells; the 008
report can reuse it.

**Alternatives considered**: one helper file inside `notebooks/` (not tested, not linted with the
package); copying cells (three diverging copies).

## R5. Notebook outputs

**Decision**: `nbstripout` installed as a git filter (`.gitattributes`: `*.ipynb filter=nbstripout`),
so the working copy keeps outputs for reading while commits never contain them. Notebooks run in
place: `uv run jupyter nbconvert --to notebook --execute --inplace notebooks/<name>.ipynb`.

**Rationale**: the repository is public and outputs could show Tiingo-derived values (docs/plan.md,
"Notebooks and code"); 003 adds the CI check later.

## R6. Findings with numbers

**Decision**: each notebook's Findings section is markdown written after executing it, quoting the
aggregates the notebook printed (counts, shares, medians, correlations). It cites the section that
shows each number, so a rerun on a newer export can be compared.

**Rationale**: the user asked for findings at the end of each notebook; a markdown cell keeps them
readable on GitHub without outputs.

## R7. Size bands and sectors

**Decision**: size bands from `market_cap` (as-traded): micro < $300 M, small $300 M – 2 B, mid
2–10 B, large ≥ 10 B, and "unknown" where market value is missing (foreign filers by design).
Sectors as given in `sector` (the 12 Fama–French industries by SIC).

**Rationale**: the usual US size bands; readable by a non-specialist.
