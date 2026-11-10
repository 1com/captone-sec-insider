# Contract: the model card data (`docs/report/model_card.json`)

Written by `sentinel report` from the same records as the report; read by the app's model card
page (011). One object per question, keyed `dilution`, `results_move`, `volatility`:

| Key | Content |
|---|---|
| `title`, `feature`, `approved` | e.g. "Dilution", "007", "V2-52" |
| `chosen` | the chosen level |
| `measure` | `{"name", "label", "lower_is_better"}`: the deciding measure |
| `test_years` | per test year: the deciding measure for the chosen level and for each simpler level |
| `bands` | per band: rows and what happened, per test year and over the four years (the hit rates of D47) |
| `coverage` | volatility only: the 80% range's coverage per test year |
| `holdout` | the holdout record's results when 010 has run; `null` before |
| `source` | experiment, run id, git commit, export date, data hash |

Aggregates only. Regenerated with the report; never edited by hand.
