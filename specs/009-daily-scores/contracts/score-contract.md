# Forecast and Outcome Contract (Feature 009)

## 1. DuckDB Table Schemas

### `score.daily`
Stored in `data/sentinel.duckdb` (Layer 5):
```sql
CREATE TABLE IF NOT EXISTS score.daily (
    cik VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    question VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    forecast_val DOUBLE NOT NULL,
    band INTEGER NOT NULL,
    coverage VARCHAR NOT NULL,
    extra_json VARCHAR,
    scored_at TIMESTAMP NOT NULL,
    PRIMARY KEY (cik, as_of, question, model_version)
);
```

### `score.outcome`
Stored in `data/sentinel.duckdb` (Layer 5):
```sql
CREATE TABLE IF NOT EXISTS score.outcome (
    cik VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    question VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    window_end DATE NOT NULL,
    forecast_val DOUBLE NOT NULL,
    forecast_band INTEGER NOT NULL,
    actual_val DOUBLE NOT NULL,
    error DOUBLE NOT NULL,
    is_hit BOOLEAN NOT NULL,
    evaluated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (cik, as_of, question, model_version)
);
```

### `model.registry`
Stored in `data/sentinel.duckdb` (Layer 5):
```sql
CREATE TABLE IF NOT EXISTS model.registry (
    question VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    algorithm VARCHAR NOT NULL,
    training_end DATE NOT NULL,
    features_count INTEGER NOT NULL,
    status VARCHAR NOT NULL, -- 'live', 'candidate', 'retired'
    registered_at TIMESTAMP NOT NULL,
    PRIMARY KEY (question, model_version)
);
```

## 2. Serving Copy (`data/serving.duckdb`, Layer 6)

The web API and UI consume:
- `app.daily_score`: View or copy of latest active forecasts from `score.daily`.
- `app.live_outcomes`: Out-of-sample evaluated track record from `score.outcome`.

## 3. Since 12 Nov 2026 (V2-72)

- `score.daily` holds the dilution forecasts of the approved frozen model (V2-59) with
  `model_version` = `lightgbm-<frozen MLflow run id>`, `forecast_val` the calibrated chance of a
  10%+ rise in shares outstanding within six months, `band` 1-5, and `extra_json` =
  `{"band_name": ..., "factors": [[feature, value, contribution], ...]}`: every input, the largest
  contribution (LightGBM `pred_contrib`, the trees' log-odds) first, a missing value `null`.
- `model.registry.status` = `approved` for the model the researcher approved and the holdout test
  scored; only such models' forecasts are published (`app.daily_score`, `app.live_outcomes`).
- `app.daily_score`: each company's newest approved forecast whose day is within 7 days of the
  newest; always present, empty when the build has none.

