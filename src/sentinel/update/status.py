"""`sentinel status`: the recent update runs, each dataset's latest date, the price coverage of the
listed companies and the schedule's next run (contracts/cli.md). It only reads: it never takes the
update lock, and while an update holds the build database it says so and shows that run's log."""

from collections.abc import Callable

import duckdb

from sentinel.config import ConfigError, Paths
from sentinel.update import record, schedule


def _runs(con, runs: int) -> list[str]:
    if "ops.update_run" not in record.tables(con, ("ops",)):
        return ["runs: none yet"]
    out = [f"last {runs} runs:"]
    for run_id, trigger, started, finished, status in con.execute(
        "select run_id, trigger, started_at, finished_at, status from ops.update_run "
        "order by started_at desc limit ?", [runs]
    ).fetchall():  # fmt: skip
        took = f"{(finished - started).total_seconds() / 60:,.0f} min" if finished else "running"
        out.append(f"  {started:%Y-%m-%d %H:%M}  {trigger:<9}  {status:<11}  {took}")
        out += [f"      {source} failed: {error}" for source, error in con.execute(
            "select source, error from ops.update_source where run_id = ? and status = 'failed' "
            "order by source", [run_id]).fetchall()]  # fmt: skip
    return out


def _coverage(con) -> list[str]:
    if "core.price_coverage" not in record.tables(con, ("core",)):
        return []
    out = ["listed companies by price source:"]
    for source, reason, n in con.execute(
        "select source, reason, count(*) from core.price_coverage group by all order by 1, 3 desc"
    ).fetchall():
        out.append(f"  {source:<7} {reason:<40} {n:>6,}")
    (tiingo_only,) = con.execute(
        "select count(*) filter (where tiingo_only) from core.price_coverage"
    ).fetchone()
    out.append(f"  Tiingo only (stop updating when the plan ends): {tiingo_only:,}")
    return out


def _freshness(p: Paths) -> list[str]:
    if not p.serving_db.exists():
        return ["data as of: nothing published yet"]
    with duckdb.connect(str(p.serving_db), read_only=True) as con:
        if "app.freshness" not in record.tables(con, ("app",)):
            return ["data as of: not in the published copy (published before app.freshness)"]
        rows = con.execute("select dataset, latest_date from app.freshness order by 1").fetchall()
    return ["data as of:", *(f"  {dataset:<24} {latest}" for dataset, latest in rows)]


def lines(p: Paths, runs: int = 5, show: Callable = schedule.show) -> list[str]:
    out = []
    try:
        con = duckdb.connect(str(p.build_db), read_only=True)
    except duckdb.IOException, duckdb.ConnectionException:
        pid = p.update_lock.read_text().strip() if p.update_lock.exists() else "unknown"
        out.append(f"an update holds the build database (pid {pid}); its log so far:")
        logs = sorted(p.logs.glob("update-*.log"))
        out += [f"  {line}" for line in (logs[-1].read_text().splitlines()[-15:] if logs else [])]
    else:
        try:
            out += _runs(con, runs) + _coverage(con)
        finally:
            con.close()
    out += _freshness(p)
    try:
        task = show(p)
    except ConfigError as e:
        out.append(f"schedule: {e}")
    else:
        shown = "; ".join(f"{k.lower()} {v}" for k, v in (task or {}).items())
        out.append(f"schedule: {shown}" if task is not None else "schedule: not installed")
    return out
