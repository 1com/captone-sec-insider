"""`sentinel export`: a Parquet snapshot in `data/exports/` for sharing privately (it holds
Tiingo-derived prices, so it is never published) and for model work outside DuckDB.

- `ml/`: one training set per risk question, features joined to their label: `volatility` and
  `dilution` (month-end rows), `results_move` (release-eve rows); `latest` (each company's latest
  row, for scoring); and `feature_snapshot`, every feature row (the holdout's rows from 2023 have
  features but no labels). Rows keep `eligible`; the models learn from the eligible ones.
- `app/`: every table of `data/serving.duckdb`.
- `README.md`: generated; each file with its rows and columns.
"""

import shutil

import duckdb

from sentinel import db
from sentinel.config import Paths

ML = {
    "volatility": """
        select s.*, l.vol_63_future, l.window_end from b.feature.snapshot s
        join b.label.volatility l using (cik, as_of) where s.month_end order by s.cik, s.as_of
    """,
    "dilution": """
        select s.*, l.dilution, l.window_end from b.feature.snapshot s
        join b.label.dilution l using (cik, as_of) where s.month_end order by s.cik, s.as_of
    """,
    "results_move": """
        select s.*, l.filing_date, l.report_date, l.close_after, l.move, l.prev4_mean, l.n_prev
        from b.feature.snapshot s join b.label.results_move l using (cik, as_of)
        order by s.cik, l.filing_date
    """,
    "latest": "select * from b.feature.snapshot where latest order by cik",
    "feature_snapshot": "select * from b.feature.snapshot order by cik, as_of",
}


def export(p: Paths, echo=print) -> dict:
    """Write the Parquet snapshot; returns rows per file."""
    for f in (p.build_db, p.serving_db):
        if not f.exists():
            raise FileNotFoundError(f"{f} not found: run `sentinel build` and `sentinel publish`")
    tmp = p.exports.with_name("exports.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "ml").mkdir(parents=True)
    (tmp / "app").mkdir()
    rows: dict[str, tuple[int, list[tuple[str, str]]]] = {}
    with duckdb.connect(config={"memory_limit": db.MEMORY_LIMIT}) as con:
        con.execute(f"attach '{p.build_db.as_posix()}' as b (read_only)")
        con.execute(f"attach '{p.serving_db.as_posix()}' as s (read_only)")
        db.require(con, ["label.volatility", "label.dilution", "label.results_move"],
                   "sentinel export")  # fmt: skip
        apps = [r[0] for r in con.execute(
            "select table_name from duckdb_tables() where database_name = 's' "
            "and schema_name = 'app' order by 1").fetchall()]  # fmt: skip
        jobs = [(f"ml/{k}.parquet", sql) for k, sql in ML.items()]
        jobs += [(f"app/{t}.parquet", f"select * from s.app.{t}") for t in apps]
        for name, sql in jobs:
            con.execute(f"copy ({sql}) to '{(tmp / name).as_posix()}' "
                        "(format parquet, compression zstd)")  # fmt: skip
            described = con.execute(f"describe select * from '{(tmp / name).as_posix()}'")
            columns = [(c, t) for c, t, *_ in described.fetchall()]
            n = con.execute(f"select count(*) from '{(tmp / name).as_posix()}'").fetchone()[0]
            rows[name] = (n, columns)
            echo(f"  {name}: {n:,} rows")
    (tmp / "README.md").write_text(_readme(rows), encoding="utf-8")
    shutil.rmtree(p.exports, ignore_errors=True)
    tmp.rename(p.exports)
    return {name: n for name, (n, _) in rows.items()}


def _readme(rows: dict[str, tuple[int, list[tuple[str, str]]]]) -> str:
    lines = [
        "# Data export (private)",
        "",
        "Written by `sentinel export`; do not edit. Holds Tiingo-derived prices: share privately,",
        "never publish. Definitions: `docs/architecture.md`, `src/sentinel/features/`,",
        "`src/sentinel/labels/risk.py`, `config/risk_params.yaml`.",
        "",
        "| File | Rows | Columns |",
        "|---|---:|---:|",
        *(f"| `{name}` | {n:,} | {len(cols)} |" for name, (n, cols) in rows.items()),
    ]
    for name, (_, cols) in rows.items():
        lines += ["", f"## `{name}`", "", ", ".join(f"`{c}` ({t.lower()})" for c, t in cols)]
    return "\n".join(lines) + "\n"
