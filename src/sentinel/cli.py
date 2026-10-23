"""`uv run sentinel <command>` — one command per pipeline step (docs/initialplan.md §9.2).

Commands are registered in step order so `--help` reads as the plan. Steps not built yet exit 4.
Contract: specs/001-skeleton-sec-ingest/contracts/cli.md
"""

import logging
import time
from datetime import datetime

import typer

from sentinel.config import (
    ConfigError,
    Paths,
    RedactingFilter,
    Secrets,
    load_params,
    load_secrets,
    registered_value,
    repo_root,
)

OK, FAILED, USAGE, CONFIG, NOT_IMPLEMENTED, SEC_FORBIDDEN = 0, 1, 2, 3, 4, 5

P0 = "Phase 0 — Set-up"
P1 = "Phase 1 — Insider data"
P2 = "Phase 2 — Prices, labels, features"
P3 = "Phase 3 — Analysis"
P4 = "Phase 4 — Holdout and delivery"

app = typer.Typer(
    name="sentinel",
    help="EDGAR-SENTINEL: do clusters of insider purchases predict returns net of costs?",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Log every HTTP request.")):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter())
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


def _not_implemented(step: str) -> None:
    typer.echo(f"not yet implemented — plan Step {step}", err=True)
    raise typer.Exit(NOT_IMPLEMENTED)


def _stub(name: str, step: str, panel: str, description: str) -> None:
    def command():
        _not_implemented(step)

    app.command(name, help=f"[Step {step}] {description}", rich_help_panel=panel)(command)


def _fail(message: str, code: int):
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _paths() -> Paths:
    return Paths.from_root(repo_root())


def _context() -> tuple[Paths, dict]:
    try:
        paths = _paths()
        return paths, load_params(paths.params_file)
    except ConfigError as e:
        _fail(f"configuration error: {e}", CONFIG)


def _data_ignored(paths: Paths) -> bool:
    import subprocess

    probe = subprocess.run(
        ["git", "check-ignore", "-q", "data/raw/probe"], cwd=paths.root, capture_output=True
    )
    return probe.returncode == 0


def _secrets(paths: Paths) -> Secrets:
    try:
        secrets = load_secrets(paths.env_file)
    except ConfigError as e:
        _fail(f"configuration error: {e}", CONFIG)
    for warning in secrets.warnings:
        typer.echo(f"warning: {warning}", err=True)
    return secrets


def _sec_net(params: dict, secrets: Secrets):
    from sentinel.ingest.http import RateLimiter, RetryPolicy, make_client

    ops = params["ops"]
    client = make_client(secrets.sec_user_agent, ops["http_timeout_seconds"])
    limiter = RateLimiter(ops["sec_target_requests_per_second"], ops["sec_max_requests_per_second"])
    return client, limiter, RetryPolicy.from_ops(ops)


# --- Warehouse steps (feature 002) --------------------------------------------------------------


def _step_stage(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel.core import stage

    archives = stage.stored_archives(paths)
    if not archives:
        _fail("no stored archives: run `sentinel fetch-sec` first", FAILED)
    done = []

    def progress(quarter):
        done.append(quarter)
        if len(done) % 10 == 0 or len(done) == len(archives):
            typer.echo(f"  staged {len(done)}/{len(archives)} quarters (last {quarter})")

    report = stage.stage_all(con, archives, on_progress=progress)
    typer.echo(
        f"stage: {report.total_rows:,} rows, {len(stage.TABLE_SPECS)} tables × "
        f"{len(archives)} quarters"
    )
    for (table, column), n in list(report.issues_by_column.items())[:10]:
        typer.echo(f"  conversion issues {table}.{column}: {n:,}")
    for table, quarter, expected, loaded in report.mismatches:
        typer.echo(f"  MISMATCH {table} {quarter}: file {expected:,}, loaded {loaded:,}")
    return report.total_rows, not report.mismatches


def _step_entities(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.core import entities

    warehouse.require_tables(con, ["stg.submission", "stg.reportingowner"], "stage")
    r = entities.build(con, params)
    typer.echo(
        f"entities: {r.filings:,} filings, {r.owners:,} owners, {r.entities:,} entities "
        f"({r.multi_member:,} with several owners), {r.role_intervals:,} role intervals"
    )
    problems = 0
    for name, found in (
        ("W7 membership not monotonic", entities.check_monotonic(con)),
        ("W8 filing owners in several entities", entities.check_filings_map_to_one_entity(con)),
    ):
        if found:
            problems += 1
            typer.echo(f"  {name}: {len(found):,} (first {found[0]})")
    return r.rows_written, not problems


def _step_gates(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.core import gates

    warehouse.require_tables(
        con, ["stg.nonderiv_trans", "stg.footnotes", "stg.nonderiv_holding"], "stage"
    )
    warehouse.require_tables(
        con, ["core.filing", "core.entity_member", "core.owner_role"], "entities"
    )
    r = gates.build(con, params)
    for gate, unit, rows_in, rows_out in gates.funnel_totals(con):
        typer.echo(f"  {gate:<18} {rows_in:>12,} → {rows_out:>12,} {unit}")
    typer.echo(
        f"gates: {r.lines:,} lines, {r.clean_purchases:,} clean purchases; holdings not "
        f"computable: before {r.null_before:,}, after {r.null_after:,}"
    )
    problems = 0
    for name, found in (
        ("W5 funnel does not reconcile", gates.check_funnel(con)),
        ("W6 clean purchases below the G6 minimum", gates.check_min_value(con, params)),
    ):
        if found:
            problems += 1
            typer.echo(f"  {name}: {len(found):,} (first {found[0]})")
    return r.rows_written, not problems


def _step_prelim(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.events import prelim

    warehouse.require_tables(con, ["core.entity_member", "core.owner_role"], "entities")
    warehouse.require_tables(con, ["core.transaction", "core.clean_purchase"], "gates")
    by_group = prelim.detect_prelim(con, params)
    labelled = dict(
        con.execute(
            'select "group", count(*) from evt.prelim_event where in_labelled_window group by 1'
        ).fetchall()
    )
    for group in ("A", "B1", "B2"):
        typer.echo(
            f"  {group:<3} {by_group.get(group, 0):>7,} events, "
            f"{labelled.get(group, 0):>7,} in the labelled window"
        )
    events = sum(by_group.values())
    members = warehouse.row_count(con, "evt.prelim_event_member")
    typer.echo(f"detect-prelim: {events:,} events with {members:,} member purchases")
    return events + members, True


STEPS: dict = {
    "stage": _step_stage,
    "entities": _step_entities,
    "gates": _step_gates,
    "prelim": _step_prelim,
}


def _run_steps(names: list[str]) -> int:
    """Run warehouse steps in order on one connection, logging each; stop at the first failure."""
    import duckdb

    from sentinel import warehouse

    paths, params = _context()
    fingerprint = warehouse.input_fingerprint(paths)
    try:
        con = warehouse.connect(paths)
    except duckdb.IOException as e:
        _fail(f"cannot open {paths.warehouse.name}: {e}", FAILED)
    with con:
        for name in names:
            started, t0 = datetime.now(), time.monotonic()
            try:
                rows, ok = STEPS[name](paths, params, con)
            except warehouse.MissingInput as e:
                typer.echo(str(e), err=True)
                return FAILED
            warehouse.log_build(con, name, started, fingerprint, rows)
            typer.echo(f"{name}: {rows:,} rows written in {time.monotonic() - t0:.0f} s")
            if not ok:
                return FAILED
    return OK


# --- Phase 0 -----------------------------------------------------------------------------------


@app.command("explore", rich_help_panel=P0)
def explore(port: int = typer.Option(4213, "--port", help="Local port for the DuckDB UI.")):
    """Query the warehouse (read-only) in the DuckDB UI, a SQL notebook in the browser."""
    import duckdb

    from sentinel import warehouse

    paths = _paths()
    if not paths.warehouse.exists():
        _fail(f"{paths.warehouse} not found: run `sentinel stage` first", FAILED)
    try:
        con = warehouse.explore_connection(paths)
    except duckdb.IOException as e:
        _fail(f"cannot open {paths.warehouse.name}; is a build step running? {e}", FAILED)
    con.execute(f"set ui_local_port = {port}")
    con.execute("install ui; load ui")
    con.execute("call start_ui_server()")
    typer.echo(f"DuckDB UI: http://localhost:{port}  (see docs/explore.md)")
    typer.echo("The warehouse is attached read-only as `warehouse`, e.g.")
    typer.echo("  select * from warehouse.evt.prelim_event limit 10;")
    typer.echo("Press Ctrl-C to stop. Build steps cannot write to the warehouse while this runs.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        con.execute("call stop_ui_server()")
        con.close()
        typer.echo("stopped")


@app.command("check", rich_help_panel=P0)
def check():
    """[Step 0] Check .env, the parameter file and data folders (offline)."""
    from sentinel.config import check_register

    paths = _paths()
    results: list[tuple[str, str]] = []

    if not paths.env_file.is_file():
        results.append(("FAIL", f".env not found at {paths.env_file}"))
    else:
        results.append(("OK", ".env present"))
        try:
            secrets = load_secrets(paths.env_file)
            results.append(("OK", "SEC_USER_AGENT contains a contact e-mail"))
            results += [("WARN", w) for w in secrets.warnings]
            results.append(("OK", f"TIINGO_API {'set' if secrets.tiingo_api else 'not set'}"))
        except ConfigError as e:
            results.append(("FAIL", str(e)))

    try:
        params = load_params(paths.params_file)
        results.append(("OK", f"{paths.params_file.name} loads (version {params.get('version')})"))
        problems = check_register(params, paths.plan_file)
        if problems:
            results += [("FAIL", p) for p in problems]
        else:
            n = len(params["registered"])
            results.append(("OK", f"{n} registered parameters match Appendix E"))
    except (ConfigError, OSError, StopIteration) as e:
        results.append(("FAIL", f"parameter file: {e}"))

    try:
        for folder in (paths.data_raw, paths.provisional):
            folder.mkdir(parents=True, exist_ok=True)
        results.append(("OK", "data/ folders exist"))
    except OSError as e:
        results.append(("FAIL", f"cannot create data/ folders: {e}"))
    results.append(
        ("OK", "data/ is git-ignored")
        if _data_ignored(paths)
        else ("FAIL", "data/ is not git-ignored")
    )

    for level, message in results:
        typer.echo(f"{level:<4}  {message}")
    raise typer.Exit(CONFIG if any(level == "FAIL" for level, _ in results) else OK)


# --- Phase 1 -----------------------------------------------------------------------------------


@app.command("fetch-sec", rich_help_panel=P1)
def fetch_sec(
    quarters: str = typer.Option(None, "--quarters", help="Only these, e.g. 2019q1,2023q2."),
    refetch: str = typer.Option(None, "--refetch", help="Store a dated copy of one quarter."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Resolve URLs; download nothing."),
):
    """[Step 1] Download the quarterly SEC insider data sets."""
    from sentinel.ingest.http import SecForbidden
    from sentinel.ingest.manifest import FetchLock, FetchLocked
    from sentinel.ingest.sec_bulk import fetch_quarters

    paths, params = _context()
    secrets = _secrets(paths)
    keys = [k.strip() for k in quarters.split(",")] if quarters else None

    def progress(r):
        detail = {"stored": f"{r.bytes / 1e6:.1f} MB", "skipped": "verified"}.get(
            r.status, r.reason
        )
        typer.echo(f"{r.key}  {r.status:<8} {detail or r.url}")

    try:
        with FetchLock(paths.lock):
            client, limiter, policy = _sec_net(params, secrets)
            with client:
                summary = fetch_quarters(
                    paths,
                    params,
                    client,
                    limiter,
                    policy,
                    keys=keys,
                    refetch=refetch,
                    dry_run=dry_run,
                    on_result=progress,
                )
    except FetchLocked as e:
        _fail(str(e), FAILED)
    except SecForbidden as e:
        _fail(f"{e}. The SEC rejected the client; check SEC_USER_AGENT in .env.", SEC_FORBIDDEN)
    except ValueError as e:
        _fail(str(e), USAGE)

    typer.echo(
        f"stored={summary.count('stored')} skipped={summary.count('skipped')} "
        f"failed={summary.count('failed')} planned={summary.count('planned')} "
        f"downloaded={summary.bytes / 1e6:.1f} MB"
    )
    raise typer.Exit(FAILED if summary.count("failed") else OK)


@app.command("verify-sec", rich_help_panel=P1)
def verify_sec():
    """[Step 1] Re-hash stored SEC archives against the manifest (offline)."""
    from sentinel.ingest.manifest import find_original, verify
    from sentinel.ingest.sec_bulk import SOURCE, quarters_in_range

    paths, params = _context()
    report = verify(paths, prefix="sec/")
    period = registered_value(params, "insider_data_period")
    keys = quarters_in_range(str(period["start"]), str(period["end"]))
    absent = [k for k in keys if find_original(paths.manifest, SOURCE, k) is None]

    typer.echo(
        f"ok={len(report.ok)} mismatch={len(report.mismatch)} missing={len(report.missing)} "
        f"unrecorded={len(report.unrecorded)}  "
        f"quarters stored: {len(keys) - len(absent)}/{len(keys)}"
    )
    for label, items in (
        ("mismatch", report.mismatch),
        ("missing", report.missing),
        ("unrecorded", report.unrecorded),
        ("not downloaded", absent),
    ):
        for item in items:
            typer.echo(f"  {label}: {item}")
    clean = not (report.mismatch or report.missing or report.unrecorded or absent)
    raise typer.Exit(OK if clean else FAILED)


@app.command("stage", rich_help_panel=P1)
def stage_cmd():
    """[Step 2] Load the data sets into typed staging tables."""
    raise typer.Exit(_run_steps(["stage"]))


@app.command("entities", rich_help_panel=P1)
def entities_cmd():
    """[Step 3] Build point-in-time insider entities and roles."""
    raise typer.Exit(_run_steps(["entities"]))


@app.command("gates", rich_help_panel=P1)
def gates_cmd():
    """[Step 4] Apply purchase gates G1–G6 and record the funnel."""
    raise typer.Exit(_run_steps(["gates"]))


audit_app = typer.Typer(no_args_is_help=True)
app.add_typer(
    audit_app, name="audit", rich_help_panel=P1, help="[QA] Hand-audit sheets for steps 3–4."
)


@audit_app.command("sheets")
def audit_sheets(
    force: bool = typer.Option(False, "--force", help="Replace existing sheets and verdicts."),
):
    """Write 50-row samples of entities, excluded and kept purchases to check by hand."""
    import duckdb

    from sentinel import warehouse
    from sentinel.core import audit

    paths = _paths()
    try:
        con = warehouse.connect(paths, read_only=True)
    except duckdb.IOException as e:
        _fail(f"cannot open {paths.warehouse.name}: {e}", FAILED)
    with con:
        try:
            warehouse.require_tables(con, ["core.entity_member", "core.owner_role"], "entities")
            warehouse.require_tables(con, ["core.transaction", "core.clean_purchase"], "gates")
            counts = audit.make_sheets(con, paths.audits, force=force)
        except (warehouse.MissingInput, audit.SheetsExist) as e:
            _fail(str(e), FAILED)
    for sheet, n in counts.items():
        typer.echo(f"  {sheet}.csv: {n} rows")
    typer.echo(f"written to {paths.audits}/: fill in `verdict` (correct/wrong/unclear) and `notes`")


@audit_app.command("summary")
def audit_summary():
    """Count the verdicts per sheet; exit 1 while any verdict is blank or invalid."""
    from sentinel.core import audit

    paths = _paths()
    try:
        summary = audit.summarize(paths.audits)
    except FileNotFoundError as e:
        _fail(f"{e.filename} not found: run `sentinel audit sheets` first", FAILED)
    typer.echo(
        f"{'sheet':<16} {'rows':>4} {'correct':>7} {'wrong':>5} {'unclear':>7} {'blank':>5} "
        f"{'invalid':>7} {'agreement':>9}"
    )
    incomplete = False
    for sheet, s in summary.items():
        rate = "—" if s.agreement is None else f"{100 * s.agreement:.1f}%"
        typer.echo(
            f"{sheet:<16} {s.rows:>4} {s.correct:>7} {s.wrong:>5} {s.unclear:>7} {s.blank:>5} "
            f"{s.invalid:>7} {rate:>9}"
        )
        incomplete |= bool(s.blank or s.invalid)
    if incomplete:
        typer.echo("some verdicts are blank or not one of: correct, wrong, unclear", err=True)
    raise typer.Exit(FAILED if incomplete else OK)


@app.command("detect-prelim", rich_help_panel=P1)
def detect_prelim_cmd():
    """[Step 5] Preliminary event detection (A, B1, B2), to choose which symbols to price."""
    raise typer.Exit(_run_steps(["prelim"]))


@app.command("compare-provisional", rich_help_panel=P1)
def compare_provisional():
    """[QA] Compare the preliminary events with feature 001's provisional events."""
    import duckdb

    from sentinel import warehouse
    from sentinel.events import compare

    paths, params = _context()
    parquet = paths.provisional / "events_PROVISIONAL.parquet"
    if not parquet.is_file():
        _fail(f"{parquet} not found: run `sentinel candidates-provisional` first", FAILED)
    try:
        con = warehouse.connect(paths, read_only=True)
    except duckdb.IOException as e:
        _fail(f"cannot open {paths.warehouse.name}: {e}", FAILED)
    with con:
        try:
            warehouse.require_tables(con, ["evt.prelim_event"], "detect-prelim")
        except warehouse.MissingInput as e:
            _fail(str(e), FAILED)
        table = compare.tabulate(con, parquet, params)
    out = paths.audits.parent / "comparison.md"
    compare.write_report(out, compare.render(table, params, parquet.name))
    for group, rows in table.items():
        totals = [sum(r.variants[i] for r in rows) for i in range(4)]
        prov = "—" if group == "B2" else f"{sum(r.provisional for r in rows):,}"
        flagged = [str(r.year) for r in rows if r.flagged]
        typer.echo(
            f"  {group:<3} feature 001 {prov:>7}; production / + $2 / − O/D / pilot G6: "
            f"{' / '.join(f'{n:,}' for n in totals)}; flagged years: {', '.join(flagged) or '—'}"
        )
    a_total = sum(r.variants[1] for r in table["A"])
    a_feature001 = sum(r.provisional for r in table["A"])
    ok = a_total <= a_feature001
    typer.echo(f"SC-005: A under production + $2 {a_total:,} ≤ {a_feature001:,}: {ok}")
    typer.echo(f"written to {out}")
    raise typer.Exit(OK if ok else FAILED)


@app.command("candidates-provisional", rich_help_panel=P1)
def candidates_provisional(
    tickers_snapshot: str = typer.Option(None, "--tickers-snapshot", help="SEC ticker snapshot."),
    no_tiingo: bool = typer.Option(False, "--no-tiingo", help="Skip Tiingo's list (offline)."),
    rebuild_scratch: bool = typer.Option(False, "--rebuild-scratch", help="Rebuild scratch DB."),
):
    """[Step 5, provisional] Rank likely-delisted companies to price (look-ahead; not research)."""
    from pathlib import Path

    from sentinel.provisional.candidates import InputsMissing, run

    paths, params = _context()
    try:
        years = run(
            paths,
            params,
            tickers_snapshot=Path(tickers_snapshot) if tickers_snapshot else None,
            use_tiingo=not no_tiingo,
            rebuild=rebuild_scratch,
            echo=typer.echo,
        )
    except InputsMissing as e:
        _fail(f"inputs missing: {e}", FAILED)

    ref = params["provisional"]["pilot_reference"]["by_start_year"]
    typer.echo("\nPlan §5.2 table (ours / pilot):")
    typer.echo(f"{'start':>6} {'events':>15} {'companies':>13} {'in Tiingo':>12} {'unmatched':>12}")
    for r in years:
        p = ref.get(r["start_year"], {})
        cells = [
            f"{r[k] if r[k] is not None else 'n/a'}/{p.get(k, '?')}"
            for k in ("events", "companies", "delisted_in_tiingo", "unmatched")
        ]
        typer.echo(
            f"{r['start_year']:>6} {cells[0]:>15} {cells[1]:>13} {cells[2]:>12} {cells[3]:>12}"
        )
    typer.echo(f"\nwritten to {paths.provisional}/ (see summary_PROVISIONAL.md)")


_stub("symbols", "6", P1, "Map issuers to price symbols")


@app.command("fetch-sec-tickers", rich_help_panel=P1)
def fetch_sec_tickers():
    """[Step 6, partial] Save today's SEC company-ticker map."""
    from sentinel.ingest.http import RetryExhausted, SecForbidden
    from sentinel.ingest.manifest import FetchLock, FetchLocked
    from sentinel.ingest.sec_reference import fetch_company_tickers

    paths, params = _context()
    secrets = _secrets(paths)
    try:
        with FetchLock(paths.lock):
            client, limiter, policy = _sec_net(params, secrets)
            with client:
                status, path = fetch_company_tickers(paths, params, client, limiter, policy)
    except FetchLocked as e:
        _fail(str(e), FAILED)
    except SecForbidden as e:
        _fail(f"{e}. The SEC rejected the client; check SEC_USER_AGENT in .env.", SEC_FORBIDDEN)
    except (RetryExhausted, ValueError) as e:
        _fail(f"failed: {e}", FAILED)
    typer.echo(f"{status}: {path.relative_to(paths.root)}")


# --- Phase 2 -----------------------------------------------------------------------------------

_stub("fetch-prices", "7", P2, "Fetch prices: Yahoo (listed), Tiingo (delisted)")
_stub("fetch-reference", "7", P2, "Download factor, industry and breakpoint files")
_stub("detect", "7", P2, "Final event detection with G7, G8, floors and cooldown")
_stub("delistings", "8", P2, "Classify delistings and assign delisting returns")
_stub("shares-out", "9", P2, "Load shares outstanding from XBRL")
_stub("costs", "10", P2, "Estimate spreads and trading costs")
_stub("prereg-status", "10a", P2, "Check the prereg-v1 pre-registration tag")
_stub("labels", "11", P2, "Compute development labels (windows ending by 2022-12-31)")
_stub("features", "12", P2, "Compute features F1–F24 as of T")
_stub("serve", "P", P2, "Run the stock lookup page and API")

# --- Phase 3 -----------------------------------------------------------------------------------

_stub("event-study", "13", P3, "Event study on the development period (H1–H3)")
_stub("ml-dataset", "14", P3, "Build the ML dataset: folds, splits, purging, weights")
_stub("baselines", "15", P3, "Fit and score the six baselines")
_stub("tournament", "16", P3, "Run the 25-configuration model tournament")
_stub("explain", "17", P3, "SHAP explanations and error analysis")

# --- Phase 4 -----------------------------------------------------------------------------------

_stub("holdout", "18", P4, "Guarded one-time holdout evaluation")
_stub("score-live", "19", P4, "Refit the production model and score the latest clusters")
_stub("robustness", "20", P4, "Pre-listed sensitivity variants (development period)")
_stub("report", "21", P4, "Final report and offline rebuild check")
