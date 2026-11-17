# Quickstart: checking the hand-in (019)

## 1. The number sheet

```bash
uv run python -m sentinel.presentation        # writes docs/presentation/numbers.md, seconds
uv run pytest -q tests/unit/test_presentation.py tests/unit/test_readme_numbers.py
```

Expected: the sheet lists every id of [contracts/number-sheet.md](contracts/number-sheet.md); the
tests pass (the sheet equals the model card and the reports; the README's results table equals the
model card).

## 2. The app shows the one-time test

```bash
bash scripts/start_web.sh      # or: uv run sentinel web (port 8100, this computer only)
```

Open http://localhost:8100, open a company with a forecast, then its model section. Expected: the
tables of [contracts/app-model-section.md](contracts/app-model-section.md), with the numbers of the
model report's "The holdout test (010)" for dilution.

```bash
uv run pytest -q tests/unit/test_web_app.py
uv run python -m sentinel.web.named_cases      # all checks pass
```

## 3. The demo path

Follow [demo.md](demo.md) on the live app with a clock, the day before and the morning of each
presentation. Expected: each step shows what it names, about 5 minutes in all; a step whose
company no longer fits uses its spare. The backup screenshots are in `data/handin/backup/` (never
committed).

## 4. A fresh copy

```bash
git clone https://github.com/1com/captone-sec-insider /tmp/fresh && cd /tmp/fresh
uv sync
uv run ruff check src tests && uv run ruff format --check src tests
uv run pytest -q tests/unit
```

Expected: installs by the README's instructions; every check passes without `data/`.

## 5. Nothing private

```bash
git ls-files | grep -E '\.(duckdb|parquet|env)$'     # expect nothing
# expect nothing; reads the commits, as the files on disk keep their outputs for the researcher
git ls-files '*.ipynb' | while read -r f; do git show "HEAD:$f" | grep -q '"output_type"' && echo "$f"; done
```

The number sheet, the README and the slides hold aggregates only; the slides are checked against
the sheet number by number.

## 6. Rehearsal

Slides and demo together, timed: 14 minutes or less (SC-001).
