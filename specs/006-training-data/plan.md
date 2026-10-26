# Implementation Plan: Training Data (Labels, Features, ML Dataset)

**Branch**: `006-training-data` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

## Summary

Three warehouse steps, run after `prereg-v1`: `sentinel labels` (Step 11: `lab.event_label`, `lab.purchase_outcome`), `sentinel features` (Step 12: `feat.event_features`) and `sentinel ml-dataset` (Step 14: `ml.dataset`, `ml.dataset_fold`, `ml.dataset_summary`, `ml.dataset_version`, Parquet copies). All three are written and tested on synthetic warehouses before the lock and refuse the real warehouse until the tag exists (research R1). Target: the dataset final by Thursday 29 October 2026.

## Technical Context

- **Language**: Python 3.14, uv; DuckDB 1.5 (memory limit 3 GB, steps under the 5 GB systemd ceiling); NumPy for the factor regressions; pyarrow for Parquet.
- **Inputs**: `evt.event`, `evt.event_member`, `evt.event_cost`, `core.price_daily`, `core.session`, `stg.price_yahoo` (SPY, IWM), `core.ff_factor_daily`, `core.ff_industry_daily`, `core.sic_industry`, `core.delisting`, `core.priced_purchase`, `core.clean_purchase`, `core.transaction`, `core.owner_role`, `core.company_filing`, `core.xbrl_fact`.
- **Scale**: about 20,000 priced events × 5 horizons × 5 measures (≤ 500,000 label rows); about 100,000 purchase outcomes; about 5,000 dataset rows.
- **Testing**: pytest on synthetic warehouses (`market_events` fixture); a feature truncation test; the slow offline-rebuild test extended to the new tables.

## Constitution Check

| Principle | How this feature complies |
|---|---|
| I Point-in-time | Features use filings ≤ T and prices ≤ T; XBRL first-filed values only; F10 only windows ended before T; truncation test |
| II Survivorship | Delisting returns inside windows; bounds stored; unpriced events stay counted (no label) |
| III Pre-registration, holdout | Commands refuse to run before `prereg-v1`; open details decided before the lock (D53); windows end by 2022-12-31; `hold` never read |
| IV Honest statistics | Gross and net stored; cost-null events counted, not imputed |
| V Reproducibility | Deterministic SQL and seeded nothing (no randomness); dataset version with commit and parameter hash; offline rebuild covers the new tables |
| VI Data use | Tiingo-derived tables registered |
| VII Simplicity | No new dependency |

Pass. One scheduling note: the plan's task order puts the dataset after the event-study approval; the dataset is built first here, but no model is fitted before that approval, which is what the method requires.

## Project Structure

```
src/sentinel/labels/      returns.py (windows, adjusted prices), build.py (event labels, purchase outcomes)
src/sentinel/features/    build.py (F1–F29)
src/sentinel/ml/          dataset.py (folds, slices, purging, weights, version)
src/sentinel/lock.py      the prereg-v1 guard
tests/unit/               test_labels.py, test_features.py, test_ml_dataset.py, test_lock.py
```
