# Quickstart: running and checking the EDA notebooks

## Prerequisites

- `data/exports/ml/` holds the three training sets (`sentinel export`, run by `sentinel update`).
- `uv sync` (dev group includes `nbconvert`, `nbstripout`).
- Once per clone: `uv run nbstripout --install --attributes .gitattributes` (the filter that keeps
  outputs out of commits).

## Run a notebook

```sh
cap() { systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 "$@"; }
cap uv run jupyter nbconvert --to notebook --execute --inplace notebooks/004-eda-volatility.ipynb
cap uv run jupyter nbconvert --to notebook --execute --inplace notebooks/004-eda-results-move.ipynb
cap uv run jupyter nbconvert --to notebook --execute --inplace notebooks/004-eda-dilution.ipynb
```

Then open the notebook in VS Code; the outputs stay in the working copy only.

## Checks

1. Each command exits 0 in under 10 minutes (SC-001); running it twice gives the same tables.
2. `uv run pytest -q tests/unit/test_eda.py` passes.
3. `git diff --cached` of a notebook after `git add` shows no outputs (SC-005):
   `git show :notebooks/004-eda-volatility.ipynb | grep -c '"output_type"'` prints 0.
4. Each notebook ends with a Findings section covering the items of SC-003.
