# Data model: Model report (008)

- **Report record** (one per notebook execution; contracts/report-record.md): an MLflow run named
  `report` in the question's experiment, tags `report=true`, `trial`, `git_commit`, `export_date`,
  `data_hash`; artifact `report.json` (the question's tables).
- **Holdout record** (written by 010): a run per question in experiment `010-holdout`, artifact
  `holdout.json`.
- **Model report** (`docs/report/model_report.md` and `docs/report/figures/`): generated Markdown and
  PNG figures; no date of generation; each section names its record.
- **Model card data** (`docs/report/model_card.json`; contracts/model-card.md): per question, the
  chosen level, the deciding measure per test year, the bands with hit rates, the coverage, the
  holdout results, the source record.

State: notebooks write records → `sentinel report` reads the newest non-trial record per question →
writes the report and the model card data; re-run after any notebook re-run or after 010.
