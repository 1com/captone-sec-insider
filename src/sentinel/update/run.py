"""`sentinel update`: the daily update (specs/001-daily-data-refresh, contracts/cli.md).

In order: take the update lock; refuse below `update.min_free_gb` of free disk; fetch every daily
source (`raw.run("all")`: each source from where it last stopped, so missed days are caught up);
re-stage the sources with stored files not yet applied (`ops.staged_file`); rebuild the layers
above staging in full; publish the serving copy and write the export, keeping the previous copy
to report what changed; record the run in `ops` and in `data/logs/update-<date>.log`.

A step's own check failing (`db.StepFailed`, e.g. the calendar refusing an old SPY file) keeps
that table as it was and makes the run `partial`; any other error stops the run as `failed`, with
the previous serving copy and export left in place. With no new file, no staging change and a
complete previous run, nothing is rebuilt and the run is `nothing_new`.
"""

import contextlib
import os
import shutil
from collections.abc import Callable
from datetime import date, datetime

from sentinel import build, db, raw
from sentinel.config import Paths, sources
from sentinel.raw import manifest
from sentinel.serving import export as serving_export
from sentinel.serving import publish as serving_publish
from sentinel.update import record

LAYERS = ("reference", "core", "features", "labels")


class UpdateLocked(Exception):
    """Another update is running."""


class DiskFull(Exception):
    """Too little free disk to start."""


@contextlib.contextmanager
def lock(p: Paths):
    """The update lock: a file holding the running process's id; a dead process's is replaced."""
    path = p.update_lock
    if path.exists():
        try:
            pid = int(path.read_text().strip())
            os.kill(pid, 0)
        except ValueError, ProcessLookupError:
            pass  # stale: its process is gone
        except PermissionError:
            raise UpdateLocked(f"an update is already running (pid {pid})") from None
        else:
            raise UpdateLocked(f"an update is already running (pid {pid})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{os.getpid()}\n")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def check_disk(p: Paths) -> None:
    need = sources(p)["update"]["min_free_gb"]
    free = shutil.disk_usage(p.data).free / 1e9
    if free < need:
        raise DiskFull(f"only {free:,.1f} GB free; the update needs {need} GB")


def _last_status(con) -> str | None:
    row = con.execute("select status from ops.update_run where finished_at is not null "
                      "order by started_at desc limit 1").fetchone()  # fmt: skip
    return row[0] if row else None


def _build(con, p: Paths, layers, echo, errors: list[str]) -> None:
    for layer in layers:
        for name, step in build.LAYERS[layer].items():
            echo(f"{layer}: {name}")
            try:
                step(con, p, echo)
                build.release_memory()
            except db.StepFailed as e:  # the step's own check: keep its table, go on
                errors.append(f"{layer}.{name}: {e}")
                echo(f"  {layer}.{name} kept as it was: {e}")


def update(p: Paths, today: date | None = None, scheduled: bool = False, fetch: bool = True,
           echo=print, layers=LAYERS, publish: Callable = serving_publish.publish,
           export: Callable = serving_export.export, notes: list[str] = ()) -> dict:  # fmt: skip
    """Run the update; returns the run's record (status, sources, changes, log file). `notes` go
    to the top of the log (e.g. a scheduled run without its memory cap)."""
    today = today or date.today()
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    log_file = p.logs / f"update-{today}.log"
    lines = [f"run {run_id} ({'scheduled' if scheduled else 'manual'})", *notes]

    def say(line: str) -> None:
        echo(line)
        lines.append(line)

    with lock(p):
        check_disk(p)
        con = db.connect(p)
        reports, errors, status, app = [], [], "failed", {}
        try:
            record.create(con)
            last = _last_status(con)
            con.execute("insert into ops.update_run values (?, ?, ?, null, 'fetching', 0, ?)",
                        [run_id, "scheduled" if scheduled else "manual", datetime.now(),
                         log_file.as_posix()])  # fmt: skip
            before = record.checksums(con)
            if fetch:
                reports = raw.run(p, "all", today, say, con=con)
                for r in reports:
                    say(r.summary())
            entries = [e for e in manifest.read_all(p.manifest) if e.role == "original"]
            steps = record.unstaged_steps(con, entries, build.STAGING_SOURCES)
            stored = sum(r.files_stored for r in reports)
            failed = [r.source for r in reports if r.status == "failed"]
            if not stored and not steps and last in ("complete", "nothing_new"):
                status = "partial" if failed else "nothing_new"
                say("nothing new: no layer rebuilt")
            else:
                con.execute("update ops.update_run set status = 'staging' where run_id = ?",
                            [run_id])  # fmt: skip
                if steps:
                    build.run(con, p, "staging", only=steps, echo=say)
                con.execute("update ops.update_run set status = 'building' where run_id = ?",
                            [run_id])  # fmt: skip
                _build(con, p, layers, say, errors)
                status = "partial" if failed or errors else "complete"
            after = record.checksums(con)
        except BaseException as e:
            status = "failed"
            errors.append(f"{type(e).__name__}: {e}")
            con.close()
            _finish(p, run_id, status, reports, {}, {}, {}, lines + errors, log_file)
            raise
        con.close()
        if status != "nothing_new" and not (status == "partial" and not steps and not stored):
            try:
                if p.serving_db.exists():
                    shutil.copy2(p.serving_db, p.serving_prev)
                publish(p, say)
                export(p, say)
                app = record.app_changes(p.serving_prev, p.serving_db)
            except BaseException as e:
                errors.append(f"publish: {type(e).__name__}: {e}")
                _finish(p, run_id, "failed", reports, before, after, {}, lines + errors, log_file)
                raise
        elif p.serving_db.exists():  # nothing published: the product's tables are unchanged
            app = record.app_changes(p.serving_db, p.serving_db)
        for name, (_, a, add, chg, rem) in sorted(app.items()):
            say(f"  app.{name}: {a:,} rows; {add:,} added, {chg:,} changed, {rem:,} removed")
        _finish(p, run_id, status, reports, before, after, app, lines + errors, log_file)
        say(f"update {run_id}: {status}")
        return {"run_id": run_id, "status": status, "errors": errors, "app": app,
                "sources": {r.source: r.status for r in reports}, "log_file": log_file}  # fmt: skip


def _finish(p: Paths, run_id: str, status: str, reports, before, after, app, lines, log_file):
    con = db.connect(p)
    try:
        record.create(con)
        record.record_sources(con, run_id, reports)
        record.record_tables(con, run_id, before, after, app)
        if status in ("complete", "partial"):
            record.record_coverage(con, run_id)
        con.execute(
            "update ops.update_run set finished_at = ?, status = ?, raw_bytes_added = ? "
            "where run_id = ?",
            [datetime.now(), status, sum(r.bytes for r in reports), run_id],
        )
    finally:
        con.close()
    record.write_log(log_file, [*lines, f"status: {status}"])
