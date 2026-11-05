## Description

- **Feature Number & Name**: <!-- e.g., 008 Model Report -->
- **Summary**: <!-- Brief summary of what was done, why, and key changes -->

---

## Verification & Pre-Merge Checklist

- [ ] `uv run ruff check src tests` passes cleanly
- [ ] `uv run ruff format --check src tests` passes cleanly
- [ ] `uv run pytest -q tests/unit` passes with all tests green
- [ ] No private data, `.env` secrets, or DuckDB database files (`data/*.duckdb`) are committed
- [ ] No Jupyter Notebook outputs or execution counts are committed (`nbstripout` applied)
- [ ] Truncation and look-ahead rules are respected (no future knowledge leaks)
- [ ] The 2023+ holdout dataset remains strictly sealed

