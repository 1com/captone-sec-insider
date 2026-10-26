"""`sentinel ml-dataset` (Step 14): the table the models train on (plan §7.2; feature 006
research R11).

One row per development cluster (group A) with a target: its features, the fixed preprocessing
of the dollar features, the primary label and its average uniqueness. Each of the four yearly
test folds splits the earlier events into fit, tuning and calibration slices, purging any event
whose label window reaches into the next part. No randomness: a rebuild gives the same rows,
whose hash is the dataset version.
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import date

import duckdb

from sentinel.config import Paths, params_sha256, registered_value
from sentinel.warehouse import require_tables

INPUTS = ["evt.event", "feat.event_features", "lab.event_label", "core.session",
          "stg.price_yahoo"]  # fmt: skip
DOLLAR = ("f2", "f12", "f16", "f17")
PARTS = ("fit", "tune", "calibrate", "test", "purged")


@dataclass
class DatasetReport:
    rows: int = 0
    positives: int = 0
    version: str = ""
    summary: list[tuple] = field(default_factory=list)


def _months_before(day: date, months: int) -> date:
    total = day.year * 12 + day.month - 1 - months
    return date(total // 12, total % 12 + 1, day.day)


def _rows(con, params: dict) -> None:
    primary = registered_value(params, "primary_horizon")
    inputs = ", ".join(
        f"ln(1 + f.{c} / spy.close) as x_{c}" if c in DOLLAR else f"f.{c} as x_{c}"
        for c in (f"f{i}" for i in range(1, 30))
    )
    con.execute(
        f"""
        create or replace temp table _ds as
        select f.event_id, f.issuer_cik, f.signal_date, f.t_session, l.exit_session as window_end,
               cast(l.net > 0 as INTEGER) as y, l.net as net_{primary}, l.gross as gross_{primary},
               {inputs}, f.price_source
        from feat.event_features f
        join lab.event_label l on l.event_id = f.event_id and l.horizon = {primary}
         and l.measure = 'ind_ew' and l.net is not null
        join stg.price_yahoo spy on spy.ticker = 'SPY' and spy.session = f.t_session
        where f."group" = 'A'
        """
    )


def _uniqueness(con, params: dict) -> None:
    """`_uq`: mean over the window's sessions of 1 ÷ (priced A events whose windows cover it)."""
    primary = registered_value(params, "primary_horizon")
    con.execute(
        f"""
        create or replace temp table _uq as
        with windows as (
            select e.event_id, s.session_no + 1 as a, s.session_no + {primary} as b
            from evt.event e join core.session s on s.session = e.t_session
            where e.priced and e."group" = 'A'
        ),
        crowd as (
            select c.session_no, count(*) as n
            from windows w join core.session c on c.session_no between w.a and w.b
            group by 1
        )
        select d.event_id, avg(1.0 / c.n) as uniqueness
        from _ds d join windows w using (event_id)
        join crowd c on c.session_no between w.a and w.b
        group by 1
        """
    )


def _folds(con, params: dict) -> list[tuple]:
    """`ml.dataset_fold` rows: (fold, event_id, part) before weights."""
    split = registered_value(params, "training_window_split")
    rows = []
    events = con.execute("select event_id, signal_date, window_end from _ds").fetchall()
    for year in params["rules"]["ml_test_years"]:
        start = date(year, 1, 1)
        calibrate = _months_before(start, split["calibration_months"])
        tune = _months_before(calibrate, split["tuning_months"])
        for event_id, signal, end in events:
            if start <= signal < date(year + 1, 1, 1):
                part = "test"
            elif signal >= start:
                continue
            elif end >= start:
                part = "purged"
            elif signal >= calibrate:
                part = "calibrate"
            elif signal >= tune:
                part = "tune" if end < calibrate else "purged"
            else:
                part = "fit" if end < tune else "purged"
            rows.append((year, event_id, part))
    return rows


def build(con: duckdb.DuckDBPyConnection, params: dict, paths: Paths) -> DatasetReport:
    """Rebuild `ml.dataset`, `ml.dataset_fold` and `ml.dataset_summary`; append a version row
    and write the Parquet copies under `data/ml/`."""
    require_tables(con, INPUTS, "features")
    _rows(con, params)
    _uniqueness(con, params)
    folds = _folds(con, params)
    con.execute("create or replace temp table _fold (fold INTEGER, event_id VARCHAR, part VARCHAR)")
    if folds:
        con.executemany("insert into _fold values (?, ?, ?)", folds)
    minimum = registered_value(params, "fold1_min_fit_size")
    first = min(params["rules"]["ml_test_years"])
    con.execute("begin transaction")
    try:
        con.execute(
            """
            create or replace table ml.dataset as
            select d.*, u.uniqueness from _ds d join _uq u using (event_id) order by event_id
            """
        )
        con.execute(
            """
            create or replace table ml.dataset_fold as
            with train as (
                select f.fold, avg(d.uniqueness) as mean_u from _fold f
                join ml.dataset d using (event_id)
                where f.part in ('fit', 'tune', 'calibrate') group by 1
            )
            select f.fold, f.event_id, f.part,
                   case when f.part in ('fit', 'tune', 'calibrate')
                        then d.uniqueness / t.mean_u
                        when f.part = 'test' then 1.0 else 0.0 end as weight
            from _fold f join ml.dataset d using (event_id) left join train t using (fold)
            order by f.fold, f.event_id
            """
        )
        con.execute(
            f"""
            create or replace table ml.dataset_summary as
            select f.fold, f.part, count(*) as events, sum(d.y) as positives,
                   sum(f.weight) as weight_sum,
                   sum(f.weight) ^ 2 / nullif(sum(f.weight ^ 2), 0) as effective_size,
                   f.fold = {first} and (select count(*) from ml.dataset_fold x
                                        where x.fold = {first} and x.part = 'fit') < {minimum}
                       as dropped
            from ml.dataset_fold f join ml.dataset d using (event_id)
            group by 1, 2 order by 1, 2
            """
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    report = DatasetReport()
    report.rows, report.positives = con.execute(
        "select count(*), coalesce(sum(y), 0) from ml.dataset"
    ).fetchone()
    report.summary = con.execute("select * from ml.dataset_summary").fetchall()
    report.version = _version(con, paths)
    for name in ("_ds", "_uq", "_fold"):
        con.execute(f"drop table if exists {name}")
    return report


def _version(con, paths: Paths) -> str:
    """Hash the dataset and its folds, append `ml.dataset_version`, write the Parquet copies."""
    digest = hashlib.sha256()
    for table in ("ml.dataset", "ml.dataset_fold"):
        rows = con.execute(f"select * from {table} order by all").fetchall()
        digest.update(json.dumps(rows, default=str).encode())
    version = digest.hexdigest()[:12]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=paths.root, capture_output=True, text=True
    )
    con.execute(
        "create table if not exists ml.dataset_version (version VARCHAR, built_at TIMESTAMP, "
        "git_commit VARCHAR, params_sha256 VARCHAR, rows BIGINT)"
    )
    con.execute(
        "insert into ml.dataset_version select ?, current_timestamp, ?, ?, count(*) "
        "from ml.dataset",
        [version, commit.stdout.strip() or "unknown",
         params_sha256(paths.params_file) if paths.params_file.exists() else "unknown"],
    )  # fmt: skip
    out = paths.root / "data" / "ml"
    out.mkdir(parents=True, exist_ok=True)
    for table, name in (("ml.dataset", "dataset"), ("ml.dataset_fold", "dataset_fold")):
        target = str(out / f"{name}-{version}.parquet").replace("'", "''")
        con.execute(f"copy (select * from {table} order by all) to '{target}' (format parquet)")
    return version
