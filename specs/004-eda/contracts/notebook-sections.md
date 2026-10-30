# Contract: the sections of every EDA notebook

Each notebook (`notebooks/004-eda-<set>.ipynb`) follows this order, so the three read alike and a
reader can jump between them. A section that does not apply says so in one line.

0. **What this notebook answers**: the question, the row, the answer and the baseline in plain
   words, with one worked example in words (no single company's prices).
1. **Load**: the development rows (`sentinel.eda.load`); rows, columns, companies, date range.
2. **Columns by family**: the table of families and counts; data types.
3. **Coverage**: rows and companies per year; by coverage level and filer type; by sector; by size
   band. Eligible share and why rows are not eligible.
4. **Missing values**: per feature overall (eligible rows), by year for the most-missing, and why.
5. **Impossible and extreme values**: counts per rule (data-model.md validation rules) and the
   1st / 99th percentiles of each feature.
6. **The answer**: distribution (log scale where skewed), by year, sector, size; base rate for
   dilution.
7. **The naive baseline**: its skill (research R1) overall and per test year 2019–2022.
8. **Feature–answer relations**: Spearman with the answer for every feature (sorted), the answer by
   decile for the strongest ten, and their per-year stability.
9. **Redundant features**: pairs with |Spearman| ≥ 0.9.
10. **Leakage and purging**: window ends after the row date; no feature with |Spearman| ≥ 0.95
    against the answer unless explained (the baseline itself); rows left in each walk-forward
    training set after the purge.
11. **Findings**: clean; cleaning rules (what, why, rows affected); modelling advice; open questions.
