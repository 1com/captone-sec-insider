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
from sentinel.warehouse import exact_sum, require_tables

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
    horizon_summary: list[tuple] = field(default_factory=list)


def _months_before(day: date, months: int) -> date:
    total = day.year * 12 + day.month - 1 - months
    return date(total // 12, total % 12 + 1, day.day)


def _rows(con, params: dict) -> None:
    """`_ds` (the primary horizon, for `ml.dataset`) and `_dh` (every horizon of the product
    model, for `ml.dataset_horizon`): one row per cluster and horizon with a net label."""
    primary = registered_value(params, "primary_horizon")
    horizons = ", ".join(str(h) for h in params["rules"]["ml_horizons"])
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
    con.execute(
        f"""
        create or replace temp table _dh as
        select f.event_id, l.horizon, f.issuer_cik, f.signal_date, f.t_session,
               l.exit_session as window_end, cast(l.net > 0 as INTEGER) as y, l.net, l.gross,
               {inputs}, f.price_source
        from feat.event_features f
        join lab.event_label l on l.event_id = f.event_id and l.horizon in ({horizons})
         and l.measure = 'ind_ew' and l.net is not null
        join stg.price_yahoo spy on spy.ticker = 'SPY' and spy.session = f.t_session
        where f."group" = 'A'
        """
    )


def _uniqueness(con, params: dict) -> None:
    """`_uq` and `_uh`: mean over a window's sessions of 1 ÷ (priced A events whose windows of the
    same length cover it), for the primary horizon and for every horizon."""
    horizons = sorted(
        {registered_value(params, "primary_horizon"), *params["rules"]["ml_horizons"]}
    )
    con.execute(
        f"""
        create or replace temp table _uh as
        with h(horizon) as (values {", ".join(f"({x})" for x in horizons)}),
        windows as (
            select e.event_id, h.horizon, s.session_no + 1 as a, s.session_no + h.horizon as b
            from evt.event e join core.session s on s.session = e.t_session
            cross join h where e.priced and e."group" = 'A'
        ),
        crowd as (
            select w.horizon, c.session_no, count(*) as n
            from windows w join core.session c on c.session_no between w.a and w.b
            group by 1, 2
        )
        select w.event_id, w.horizon,
               {exact_sum("1.0 / c.n", 18)} / count(*) as uniqueness
        from windows w join crowd c on c.horizon = w.horizon and c.session_no between w.a and w.b
        group by 1, 2
        """
    )
    primary = registered_value(params, "primary_horizon")
    con.execute(
        f"create or replace temp table _uq as select event_id, uniqueness from _uh "
        f"where horizon = {primary}"
    )


def _folds(con, params: dict, table: str = "_ds") -> list[tuple]:
    """Fold rows before weights: (fold, event_id, part), or (fold, event_id, horizon, part) for
    a table with a `horizon` column."""
    split = registered_value(params, "training_window_split")
    rows = []
    horizon = ", horizon" if table == "_dh" else ""
    events = con.execute(
        f"select event_id, signal_date, window_end{horizon} from {table}"
    ).fetchall()
    for year in params["rules"]["ml_test_years"]:
        start = date(year, 1, 1)
        calibrate = _months_before(start, split["calibration_months"])
        tune = _months_before(calibrate, split["tuning_months"])
        for event_id, signal, end, *h in events:
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
            rows.append((year, event_id, *h, part))
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
            f"""
            create or replace table ml.dataset_fold as
            with train as (
                select f.fold, {exact_sum("d.uniqueness", 18)} / count(*) as mean_u from _fold f
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
                   {exact_sum("f.weight", 12)} as weight_sum,
                   {exact_sum("f.weight", 12)} ^ 2
                       / nullif({exact_sum("f.weight * f.weight", 12)}, 0) as effective_size,
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
    _horizon_tables(con, params)
    report.horizon_summary = con.execute("select * from ml.dataset_horizon_summary").fetchall()
    report.version = _version(con, paths)
    for name in ("_ds", "_dh", "_uq", "_uh", "_fold", "_foldh"):
        con.execute(f"drop table if exists {name}")
    return report


def _horizon_tables(con, params: dict) -> None:
    """`ml.dataset_horizon`, `ml.dataset_horizon_fold` and `ml.dataset_horizon_summary` (D54): the
    same events at every product horizon, with the folds, purging and weights of each horizon's
    own windows. The input of the one multi-horizon model; exploratory, next to the primary."""
    folds = _folds(con, params, "_dh")
    con.execute(
        "create or replace temp table _foldh (fold INTEGER, event_id VARCHAR, horizon INTEGER, "
        "part VARCHAR)"
    )
    if folds:
        con.executemany("insert into _foldh values (?, ?, ?, ?)", folds)
    con.execute("begin transaction")
    try:
        con.execute(
            """
            create or replace table ml.dataset_horizon as
            select d.*, u.uniqueness from _dh d join _uh u using (event_id, horizon)
            order by event_id, horizon
            """
        )
        con.execute(
            f"""
            create or replace table ml.dataset_horizon_fold as
            with train as (
                select f.fold, f.horizon, {exact_sum("d.uniqueness", 18)} / count(*) as mean_u
                from _foldh f
                join ml.dataset_horizon d using (event_id, horizon)
                where f.part in ('fit', 'tune', 'calibrate') group by 1, 2
            )
            select f.fold, f.event_id, f.horizon, f.part,
                   case when f.part in ('fit', 'tune', 'calibrate')
                        then d.uniqueness / t.mean_u
                        when f.part = 'test' then 1.0 else 0.0 end as weight
            from _foldh f join ml.dataset_horizon d using (event_id, horizon)
            left join train t using (fold, horizon)
            order by f.fold, f.horizon, f.event_id
            """
        )
        con.execute(
            f"""
            create or replace table ml.dataset_horizon_summary as
            select f.fold, f.horizon, f.part, count(*) as events, sum(d.y) as positives,
                   {exact_sum("f.weight", 12)} as weight_sum,
                   {exact_sum("f.weight", 12)} ^ 2
                       / nullif({exact_sum("f.weight * f.weight", 12)}, 0) as effective_size
            from ml.dataset_horizon_fold f join ml.dataset_horizon d using (event_id, horizon)
            group by 1, 2, 3 order by 1, 2, 3
            """
        )
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def _version(con, paths: Paths) -> str:
    """Hash the dataset and its folds, append `ml.dataset_version`, write the Parquet copies."""
    digest = hashlib.sha256()
    tables = ("ml.dataset", "ml.dataset_fold", "ml.dataset_horizon", "ml.dataset_horizon_fold")
    for table in tables:
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
    for table in tables:
        name = table.removeprefix("ml.")
        target = str(out / f"{name}-{version}.parquet").replace("'", "''")
        con.execute(f"copy (select * from {table} order by all) to '{target}' (format parquet)")
    return version
