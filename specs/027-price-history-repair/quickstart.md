# Quickstart: Price history repair, then retrain and test (027)

Every heavy step runs under the memory cap, one at a time, never during the 10:00 update:
`systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 <command>`.

## 1. Baseline (before any change to the build)

```bash
uv run sentinel audit            # on the build as it is: must reproduce the 11 Nov counts
```

The JSON of that day is the "before" of the report.

## 2. Old tickers' prices (once, before 26 November)

```bash
uv run sentinel fetch tiingo --former   # about 1,400 requests, 12 minutes; a second run asks nothing
```

## 3. Rebuild and check

```bash
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 bash -c \
  'uv run sentinel build staging --only tiingo && uv run sentinel build reference && \
   uv run sentinel build core && uv run sentinel build features && uv run sentinel build labels && \
   uv run sentinel publish && uv run sentinel export'
uv run sentinel verify           # a full rebuild equals the update
uv run sentinel audit            # the "after": every named case passes, no ticker-day twice
uv run pytest -q                 # unit tests, the truncation test
uv run pytest -q tests/real      # named real cases
```

Expected: MGP Ingredients, Viavi, Palatin, AMN Healthcare and Digital Realty priced from January
2010; Ingersoll Rand from 12 May 2017; Standard BioTools without LaBranche's prices; Heidmar without
its 2010 block; Telephone & Data Systems priced; Chatham Lodging from CLDT; DocGo and Redwire from
their mergers; Fabrinet unchanged.

Then: the hand check of 30 remaining cuts drawn at random (recorded in `docs/decisions.md`), and
the three EDA notebooks re-run (README, Notebooks).

## 4. Retrain and approve

```bash
for n in 007-dilution-model 006-results-move-model 005-volatility-model; do
  systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 \
    uv run jupyter nbconvert --to notebook --execute --inplace notebooks/$n.ipynb
done
uv run sentinel report           # the model report from the new records
```

The researcher reads each executed notebook and approves it (or not); approvals logged in
`docs/decisions.md`.

## 5. Prepare and run the holdout test

```bash
mkdir -p data/frozen/<export date>/ml && cp -p data/exports/ml/*.parquet data/frozen/<export date>/ml/
uv run sentinel holdout --freeze-levels   # the levels again, from the kept rows; must match the records
uv run sentinel holdout --check
# by the researcher, once (by Tue 17 Nov if all of the above is done; otherwise after the hand-in):
systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 uv run sentinel holdout --run
uv run sentinel report
```
