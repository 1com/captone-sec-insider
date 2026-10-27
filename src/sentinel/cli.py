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
OUTSIDE_PAID_WINDOW = 6  # Tiingo data outside the paid month (feature 004)
NOT_LOCKED = 7  # a step that computes returns, before prereg-v1 (feature 006)

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


def _step_symbols(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.core import symbols
    from sentinel.ingest.sec_reference import latest_snapshot

    warehouse.require_tables(con, ["core.filing"], "entities")
    warehouse.require_tables(con, ["evt.prelim_event"], "detect-prelim")
    snapshot = latest_snapshot(paths)
    if snapshot is None:
        raise warehouse.MissingInput("run `sentinel fetch-sec-tickers` first: no ticker snapshot")
    n_map, n_unmatched = symbols.build_symbol_map(con, snapshot, params)
    cov = symbols.coverage(con)
    share = cov["mapped"] / cov["event_companies"] if cov["event_companies"] else 1.0
    unmatched = ", ".join(f"{k} {v:,}" for k, v in cov["unmatched"].items()) or "none"
    typer.echo(
        f"symbols: {n_map:,} ticker rows, {n_unmatched:,} unmatched issuers ({snapshot.name})\n"
        f"  event companies {cov['event_companies']:,}: mapped {cov['mapped']:,} ({share:.1%}; "
        f"Yahoo {cov['yahoo']:,}, Tiingo {cov['tiingo']:,}); unmatched: {unmatched}"
    )
    problems = 0
    for name, found in (
        ("W10 event companies neither mapped nor listed", symbols.check_events_covered(con)),
        ("W11 tickers not from SEC data", symbols.check_sec_only(con, snapshot)),
    ):
        if found:
            problems += 1
            typer.echo(f"  {name}: {len(found):,} (first {found[0]})")
    return n_map + n_unmatched, not problems


def _step_headers(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel.ingest import sec_headers

    n = sec_headers.load_headers(con, paths)
    failed = con.execute("select count(*) from core.header_failure").fetchone()[0]
    wanted, parsed, no_sic = con.execute(
        """
        select count(distinct e.signal_accession), count(distinct h.accession),
               count(distinct h.accession) filter (where h.sic is null)
        from evt.prelim_event e left join core.filing_header h on h.accession = e.signal_accession
        where e.signal_date >= cast(? as DATE)
        """,
        [str(registered_value(params, "labelled_window_start"))],
    ).fetchone()
    share = parsed / wanted if wanted else 1.0
    typer.echo(
        f"headers: {n:,} parsed; {failed:,} failures listed\n"
        f"  signal filings from the labelled start: {parsed:,} of {wanted:,} have a header "
        f"({share:.1%}); {no_sic:,} without a SIC code (D45)"
    )
    return n, True


def _step_invariants(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.ingest.sec_reference import latest_snapshot

    problems = warehouse.check_invariants(con, params, latest_snapshot(paths), paths)
    for problem in problems:
        typer.echo(f"  {problem}")
    typer.echo(f"invariants: {'all hold' if not problems else f'{len(problems)} broken'}")
    return 0, not problems


def _step_prices(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.core import prices

    warehouse.require_tables(con, ["core.symbol_map"], "symbols")
    r = prices.build(con, paths, params)
    chosen = ", ".join(f"{k} {v:,}" for k, v in r.chosen.items()) or "none"
    issues = ", ".join(f"{k} {v:,}" for k, v in r.issues.items()) or "none"
    typer.echo(
        f"prices: {r.yahoo_rows:,} Yahoo rows, {r.tiingo_rows:,} Tiingo rows → "
        f"{r.daily_rows:,} daily rows\n"
        f"  universe {r.universe:,} issuers; chosen series: {chosen}; unpriced {r.unpriced:,}\n"
        f"  price issues: {issues}"
    )
    problems = prices.check_one_series(con) + prices.check_valid_prices(con)
    for problem in problems[:10]:
        typer.echo(f"  W14/W15: {problem}")
    return r.daily_rows, not problems


def _step_detect(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.events import final

    r = final.detect(con, params)
    outcomes = ", ".join(f"{k} {v:,}" for k, v in sorted(r.outcomes.items()))
    events = ", ".join(f"{k} {v:,}" for k, v in sorted(r.events.items()))
    rate = r.g8_passed / r.g8_checked if r.g8_checked else 0.0
    typer.echo(
        f"detect: G8 {r.g8_passed:,} of {r.g8_checked:,} lines pass ({rate:.1%})\n"
        f"  {r.candidates:,} candidates: {outcomes}\n  events: {events or 'none'}"
    )
    for group, (n, k) in r.coverage.items():
        typer.echo(f"  coverage from 2012, {group}: {k:,} of {n:,} ({k / n:.1%})" if n else "")
    problems = []
    for name, found in (
        ("W18 entry sessions", final.check_entry_sessions(con)),
        ("W19 cooldown", final.check_cooldown(con, params)),
        ("W20 kept events", final.check_kept_events(con, params)),
        ("W21 funnel", final.check_funnel(con)),
    ):
        if found:
            problems.append(name)
            typer.echo(f"  {name}: {len(found):,} (first {found[0]})")
    if r.needs_header:
        raise warehouse.NeedsFetch(
            f"{len(r.needs_header):,} signal filings have no header yet: run "
            "`sentinel fetch-headers --final`, then `sentinel detect` "
            "(or `sentinel detect --fetch-missing-headers`)"
        )
    return r.candidates, not problems


def _step_company(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import warehouse
    from sentinel.core import company

    warehouse.require_tables(con, ["evt.prelim_event"], "detect-prelim")
    n_issuers, n_filings = company.build_profiles(con, paths, params)
    typer.echo(f"company-facts: {n_issuers:,} issuer profiles, {n_filings:,} filings")
    report = company.build_facts(con, paths, params)
    typer.echo(f"  XBRL facts: {report}")
    problems = company.check_first_filed(con)
    for problem in problems:
        typer.echo(f"  W22: duplicate fact {problem}")
    return n_issuers + n_filings + report.rows, not problems


def _step_delistings(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel.core import delistings

    r = delistings.build(con, params)
    classes = ", ".join(f"{k} {v:,}" for k, v in sorted(r.classes.items())) or "none"
    venues = ", ".join(f"{k} {v:,}" for k, v in sorted(r.venues.items())) or "none"
    typer.echo(f"delistings: {r.ended_early:,} series end early; {classes}; venues: {venues}")
    problems = delistings.check_delistings(con, params)
    for problem in problems[:10]:
        typer.echo(f"  W23: {problem}")
    return r.ended_early, not problems


def _step_reference(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel.core import reference

    pilot = reference.build_tick_pilot(con, paths)
    r = reference.build_french(con, paths)
    typer.echo(
        f"reference: tick pilot {pilot if pilot is not None else 'not stored'} intervals; "
        f"French factors {r.factor_rows:,} rows through {r.last_date}, industries "
        f"{r.industry_rows:,}, SIC ranges {r.sic_ranges:,}, breakpoints {r.breakpoints:,}"
    )
    if r.missing_files:
        typer.echo(f"  not stored: {', '.join(r.missing_files)}")
    unmapped = reference.unmapped_sics(con) if r.sic_ranges else []
    if unmapped:
        shown = ", ".join(f"{sic} ({n:,})" for sic, n in unmapped[:15])
        typer.echo(f"  header SICs outside the 49 industries: {shown}")
    return (pilot or 0) + r.factor_rows + r.industry_rows, True


def _step_costs(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel.events import costs

    r = costs.build(con, params)
    median = f"{r.median_cost:.2%}" if r.median_cost is not None else "–"
    typer.echo(
        f"costs: {r.events:,} priced events, {r.with_cost:,} with a cost (median {median}); "
        f"{r.pilot_days:,} on tick-pilot days"
    )
    flags = costs.write_report(con, params, paths.reports_004 / "costs.md")
    typer.echo(f"  wrote costs.md; jumps at a price other than $2: {'; '.join(flags) or 'none'}")
    problems = costs.check_costs(con)
    for problem in problems[:10]:
        typer.echo(f"  W24: {problem}")
    return r.events, not problems


def _step_labels(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import lock
    from sentinel.labels import build as labels

    lock.require(paths.root, paths.params_file)
    r = labels.build(con, params)
    measures = ", ".join(f"{m} {n:,}" for m, n in r.by_measure.items())
    typer.echo(
        f"labels: {r.events:,} events, {r.rows:,} rows ({measures}); "
        f"{r.no_entry_price:,} positions without an entry price\n"
        f"  63-session industry labels: {r.delisted_windows:,} delisted in the window, "
        f"{r.entry_at_close:,} entered at the close, {r.null_net:,} without a cost (no net)\n"
        f"  purchase outcomes for F10: {r.purchase_outcomes:,}"
    )
    problems = labels.check_labels(con, params)
    for problem in problems[:10]:
        typer.echo(f"  W30: {problem}")
    return r.rows, not problems


def _step_features(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import lock
    from sentinel.features import build as features

    lock.require(paths.root, paths.params_file)
    r = features.build(con, params)
    sparse = [f"{f} {n:,}" for f, n in r.non_null.items() if n < r.events]
    typer.echo(
        f"features: {r.events:,} events; features with missing values: "
        f"{'; '.join(sparse) or 'none'}"
    )
    return r.events, True


def _step_ml_dataset(paths: Paths, params: dict, con) -> tuple[int, bool]:
    from sentinel import lock
    from sentinel.ml import dataset

    lock.require(paths.root, paths.params_file)
    r = dataset.build(con, params, paths)
    typer.echo(f"ml-dataset: {r.rows:,} clusters, {r.positives:,} with y = 1; version {r.version}")
    typer.echo(f"  {'fold':<6}{'part':<11}{'events':>8}{'y = 1':>8}{'eff. size':>11}  dropped")
    for fold, part, events, positives, _, effective, dropped in r.summary:
        typer.echo(
            f"  {fold:<6}{part:<11}{events:>8,}{positives:>8,}{effective or 0:>11,.0f}  "
            f"{'yes' if dropped else ''}"
        )
    typer.echo("  multi-horizon table (D54): events and y = 1 in the fit set, by test fold")
    fits = {(f, h): (e, p) for f, h, part, e, p, *_ in r.horizon_summary if part == "fit"}
    for fold, horizon in sorted(fits):
        events, positives = fits[(fold, horizon)]
        typer.echo(f"  {fold}  {horizon:>3} sessions  {events:>6,} events  {positives:>6,} y = 1")
    return r.rows, True


STEPS: dict = {
    "stage": _step_stage,
    "entities": _step_entities,
    "gates": _step_gates,
    "prelim": _step_prelim,
    "symbols": _step_symbols,
    "headers": _step_headers,
    "prices": _step_prices,
    "detect": _step_detect,
    "reference": _step_reference,
    "company": _step_company,
    "delistings": _step_delistings,
    "costs": _step_costs,
    "invariants": _step_invariants,
    "labels": _step_labels,
    "features": _step_features,
    "ml-dataset": _step_ml_dataset,
}


def _run_steps(names: list[str]) -> int:
    """Run warehouse steps in order on one connection, logging each; stop at the first failure."""
    import duckdb

    from sentinel import lock, warehouse
    from sentinel.core.tiingo_register import OutsidePaidWindow

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
            except warehouse.NeedsFetch as e:
                typer.echo(str(e), err=True)
                return CONFIG
            except warehouse.MissingInput as e:
                typer.echo(str(e), err=True)
                return FAILED
            except OutsidePaidWindow as e:
                typer.echo(str(e), err=True)
                return OUTSIDE_PAID_WINDOW
            except lock.NotLocked as e:
                typer.echo(f"{name}: {e}", err=True)
                return NOT_LOCKED
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
    audit_app, name="audit", rich_help_panel=P1, help="[QA] Hand-audit sheets for steps 3–10."
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


@audit_app.command("no-sic")
def audit_no_sic(
    force: bool = typer.Option(False, "--force", help="Replace an existing sheet and verdicts."),
):
    """D45: count events whose filing header has no SIC; write 30 companies to classify."""
    import duckdb

    from sentinel import warehouse
    from sentinel.core import audit

    paths, params = _context()
    start = str(registered_value(params, "labelled_window_start"))
    try:
        con = warehouse.connect(paths, read_only=True)
    except duckdb.IOException as e:
        _fail(f"cannot open {paths.warehouse.name}: {e}", FAILED)
    with con:
        try:
            warehouse.require_tables(con, ["core.filing_header"], "fetch-headers")
        except warehouse.MissingInput as e:
            _fail(str(e), FAILED)
        typer.echo(f"{'year':<6}{'group':<7}{'events':>8}{'no SIC':>8}")
        for year, group, events, no_sic in audit.no_sic_counts(con, start):
            typer.echo(f"{year:<6}{group:<7}{events:>8,}{no_sic:>8,}")
        try:
            n = audit.make_no_sic_sheet(con, paths.audits, start, force=force)
            typer.echo(f"wrote {n} companies to {paths.audits / audit.NO_SIC_SHEET}.csv")
        except audit.SheetsExist:
            typer.echo(f"kept the existing {audit.NO_SIC_SHEET}.csv")
    counts = audit.summarize_no_sic(paths.audits)
    typer.echo(
        "verdicts: "
        + ", ".join(f"{k} {v}" for k, v in counts.items())
        + f" (allowed: {', '.join(audit.NO_SIC_VERDICTS)})"
    )
    if counts["blank"] or counts["invalid"]:
        raise typer.Exit(OK)
    if counts["operating_company"] >= audit.NO_SIC_FALLBACK_AT:
        typer.echo("D45: fallback — issuers without a header SIC keep their current SIC (§11)")
    else:
        typer.echo("D45 stands: issuers without a header SIC are excluded by G7")
    raise typer.Exit(OK)


@audit_app.command("golden")
def audit_golden(
    force: bool = typer.Option(False, "--force", help="Replace an existing sheet and verdicts."),
):
    """Feature 004: write 30 final events to check against EDGAR (golden set, SC-003)."""
    import duckdb

    from sentinel import warehouse
    from sentinel.core import audit

    paths, _ = _context()
    try:
        with warehouse.connect(paths, read_only=True) as con:
            warehouse.require_tables(con, ["evt.event", "evt.event_member"], "detect")
            n = audit.make_golden_sheet(con, paths.audits_004, force=force)
    except (duckdb.IOException, warehouse.MissingInput) as e:
        _fail(str(e), FAILED)
    except audit.SheetsExist as e:
        _fail(f"kept the existing sheet: {e}", FAILED)
    typer.echo(f"wrote {n} events to {paths.audits_004 / audit.GOLDEN_SHEET}.csv")


@audit_app.command("golden-summary")
def audit_golden_summary():
    """Feature 004: agreement of the golden set with EDGAR (exit 1 while checks are blank)."""
    from sentinel.core import audit

    paths, _ = _context()
    try:
        s = audit.summarize_golden(paths.audits_004)
    except FileNotFoundError:
        _fail("no golden set yet: run `sentinel audit golden`", FAILED)
    agreement = f"{s.agreement:.0%}" if s.agreement is not None else "–"
    typer.echo(
        f"golden set: {s.events} events; all checks yes {s.all_yes}, with a no {s.with_no}, "
        f"unclear {s.unclear}, not filled in {s.blank}; agreement {agreement} (target 30/30)"
    )
    raise typer.Exit(FAILED if s.blank else OK)


@audit_app.command("delistings")
def audit_delistings(
    force: bool = typer.Option(False, "--force", help="Replace an existing sheet and verdicts."),
):
    """Feature 004: write 30 delisting classifications to check by hand (SC-004)."""
    import duckdb

    from sentinel import warehouse
    from sentinel.core import audit

    paths, _ = _context()
    try:
        with warehouse.connect(paths, read_only=True) as con:
            warehouse.require_tables(con, ["core.delisting"], "delistings")
            n = audit.make_delisting_sheet(con, paths.audits_004, force=force)
    except (duckdb.IOException, warehouse.MissingInput) as e:
        _fail(str(e), FAILED)
    except audit.SheetsExist as e:
        _fail(f"kept the existing sheet: {e}", FAILED)
    typer.echo(f"wrote {n} issuers to {paths.audits_004 / audit.DELISTING_SHEET}.csv")


@audit_app.command("delistings-summary")
def audit_delistings_summary():
    """Feature 004: agreement with the delisting classes (exit 1 while verdicts are blank)."""
    from sentinel.core import audit

    paths, _ = _context()
    try:
        s = audit.summarize_delistings(paths.audits_004)
    except FileNotFoundError:
        _fail("no delisting sheet yet: run `sentinel audit delistings`", FAILED)
    for cls, c in s.items():
        judged = c["agree"] + c["disagree"]
        share = f"{c['agree'] / judged:.0%}" if judged else "–"
        typer.echo(
            f"{cls:<12} agree {c['agree']}, disagree {c['disagree']}, unclear {c['unclear']}, "
            f"blank {c['blank']}, invalid {c['invalid']}: agreement {share}"
        )
    typer.echo("target: ≥ 90% overall (SC-004)")
    raise typer.Exit(FAILED if s.get("all", {}).get("blank") else OK)


@audit_app.command("market-caps")
def audit_market_caps():
    """Feature 004: market caps at the latest session against Yahoo's (SC-005; 10 companies)."""
    import duckdb

    from sentinel import warehouse
    from sentinel.core import audit
    from sentinel.ingest.manifest import FetchLock, FetchLocked

    paths, params = _context()
    if not params["ops"]["market_cap_examples"]:
        _fail("set ops.market_cap_examples (10 tickers) in config/params.yaml first", CONFIG)
    try:
        with FetchLock(paths.lock), warehouse.connect(paths, read_only=True) as con:
            warehouse.require_tables(con, ["core.price_daily"], "prices")
            warehouse.require_tables(con, ["core.xbrl_fact"], "company-facts")
            rows = audit.make_market_cap_sheet(con, paths, params)
    except (duckdb.IOException, warehouse.MissingInput, FetchLocked) as e:
        _fail(str(e), FAILED)
    ok = sum(1 for r in rows if r[-1])
    for r in rows:
        typer.echo(f"  {r[0]:<8} ratio {r[8] if r[8] is not None else '–'}")
    typer.echo(f"{ok} of {len(rows)} within 5% (target: 10 of 10, or each miss explained)")


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


@app.command("symbols", rich_help_panel=P1)
def symbols_cmd(
    tiingo_report: bool = typer.Option(
        False, "--tiingo-report", help="Also count matches in Tiingo's public list (in memory)."
    ),
):
    """[Step 6] Map every issuer to price symbols, from SEC data only."""
    code = _run_steps(["symbols"])
    if code != OK or not tiingo_report:
        raise typer.Exit(code)
    import httpx

    from sentinel import warehouse
    from sentinel.core import symbols

    paths, params = _context()
    with warehouse.connect(paths, read_only=True) as con:
        try:
            counts = symbols.tiingo_coverage(con, params)
        except httpx.HTTPError as e:
            _fail(f"cannot read Tiingo's public list: {e}", FAILED)
    typer.echo(
        "Tiingo public list, delisted event companies (held in memory, nothing stored): "
        + ", ".join(f"{k} {v:,}" for k, v in counts.items())
    )
    raise typer.Exit(OK)


def _fetch_headers(limit=None, retry_failures=False, final=False) -> int:
    """Fetch missing signal-filing headers (preliminary events, or final candidates with
    `final`), then load them; returns the exit code."""
    import duckdb

    from sentinel import warehouse
    from sentinel.ingest import sec_headers
    from sentinel.ingest.http import RetryPolicy, SecForbidden, make_client
    from sentinel.ingest.manifest import FetchLock, FetchLocked

    paths, params = _context()
    secrets = _secrets(paths)
    try:
        with warehouse.connect(paths, read_only=True) as con:
            if final:
                warehouse.require_tables(con, ["evt.event_candidate"], "detect")
                targets = sec_headers.final_targets(con, paths, retry_failures)
            else:
                warehouse.require_tables(con, ["evt.prelim_event"], "detect-prelim")
                targets = sec_headers.signal_accessions(con, params, paths, retry_failures)
    except (duckdb.IOException, warehouse.MissingInput) as e:
        typer.echo(str(e), err=True)
        return FAILED
    total = len(targets) if limit is None else min(limit, len(targets))
    typer.echo(f"fetch-headers: {len(targets):,} missing; fetching {total:,}")

    def progress(done):
        if done % 500 == 0 or done == total:
            typer.echo(f"  {done:,}/{total:,}")

    try:
        with FetchLock(paths.lock):
            ops = params["ops"]
            with make_client(secrets.sec_user_agent, ops["http_timeout_seconds"]) as client:
                report = sec_headers.fetch_headers(
                    paths,
                    params,
                    client,
                    sec_headers.header_limiter(params),
                    RetryPolicy.from_ops(ops),
                    targets,
                    limit=limit,
                    on_progress=progress,
                )
    except FetchLocked as e:
        typer.echo(str(e), err=True)
        return FAILED
    except SecForbidden as e:
        typer.echo(f"{e}. The SEC rejected the client; check SEC_USER_AGENT in .env.", err=True)
        return SEC_FORBIDDEN
    typer.echo(f"stored {report.stored:,}; failed {len(report.failed):,}")
    for accession, reason in report.failed[:10]:
        typer.echo(f"  {accession}: {reason}")
    try:
        with warehouse.connect(paths) as con:
            sec_headers.record_failures(con, report.failed)
    except duckdb.IOException as e:
        typer.echo(f"headers are stored, but failures could not be recorded: {e}", err=True)
        return FAILED
    return _run_steps(["headers"])


@app.command("fetch-headers", rich_help_panel=P1)
def fetch_headers_cmd(
    limit: int = typer.Option(None, "--limit", help="Fetch at most N missing headers."),
    retry_failures: bool = typer.Option(
        False, "--retry-failures", help="Also retry filings that failed before."
    ),
    final: bool = typer.Option(
        False, "--final", help="Headers of final-event candidates waiting for G7 (feature 004)."
    ),
):
    """[Step 6] Fetch the signal filings' EDGAR headers: SIC code at T and acceptance time."""
    raise typer.Exit(_fetch_headers(limit, retry_failures, final))


@app.command("build", rich_help_panel=P1)
def build_cmd():
    """[Steps 2–10] Rebuild the warehouse from data/raw (no network), then check its invariants."""
    from sentinel.ingest import sec_company, sec_headers, yahoo
    from sentinel.ingest.manifest import read_all

    paths = _paths()
    stored = {e.source for e in read_all(paths.manifest) if e.role == "original"}
    steps = ["stage", "entities", "gates", "prelim", "symbols"]
    if sec_headers.SOURCE in stored:
        steps.append("headers")
    # Feature 004: each step runs when its raw files are stored (a build never fetches).
    wanted = {
        "prices": yahoo.SOURCE in stored,
        "reference": bool({"french", "finra"} & stored),
        "company": sec_company.SOURCE in stored,
        "detect": yahoo.SOURCE in stored and sec_headers.SOURCE in stored,
        "delistings": yahoo.SOURCE in stored and sec_company.SOURCE in stored,
        "costs": yahoo.SOURCE in stored and sec_headers.SOURCE in stored,
    }
    for step, ok in wanted.items():
        if ok:
            steps.append(step)
        else:
            typer.echo(f"build: skipping {step} (its raw files are not stored yet)")
    raise typer.Exit(_run_steps([*steps, "invariants"]))


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


@app.command("fetch-prices", rich_help_panel=P2)
def fetch_prices_cmd(
    source: str = typer.Option(..., "--source", help="yahoo (listed) or tiingo (delisted)."),
    limit: int = typer.Option(None, "--limit", help="Fetch at most N tickers (for testing)."),
    retry_failures: bool = typer.Option(
        False, "--retry-failures", help="Also retry Yahoo tickers that failed before."
    ),
    crosscheck: bool = typer.Option(
        False,
        "--crosscheck",
        help="With --source tiingo: fetch the tickers of the chosen Yahoo series, to check Yahoo "
        "(audit.price_crosscheck); needs `sentinel prices` first.",
    ),  # fmt: skip
):
    """[Step 7] Fetch daily prices: Yahoo for listed stocks, SPY and IWM; Tiingo for delisted
    stocks (paid month only), or with --crosscheck for the listed ones, to check Yahoo."""
    import duckdb

    from sentinel import warehouse
    from sentinel.core import prices
    from sentinel.core.symbols import fetch_list
    from sentinel.core.tiingo_register import OutsidePaidWindow, require_paid_window
    from sentinel.ingest import tiingo, yahoo
    from sentinel.ingest.http import RateLimiter, RetryPolicy
    from sentinel.ingest.manifest import FetchLock, FetchLocked

    if source not in ("yahoo", "tiingo"):
        _fail("--source must be yahoo or tiingo", USAGE)
    if crosscheck and source != "tiingo":
        _fail("--crosscheck needs --source tiingo", USAGE)
    paths, params = _context()
    ops = params["ops"]
    try:
        if source == "tiingo":
            require_paid_window(params)
        with warehouse.connect(paths, read_only=True) as con:
            warehouse.require_tables(con, ["core.symbol_map", "evt.prelim_event"], "symbols")
            if crosscheck:
                warehouse.require_tables(con, ["core.price_series"], "prices")
            if source == "yahoo":
                tickers = yahoo.universe_tickers(con, params)
            else:
                fallback = []
                if warehouse.table_exists(con, "stg.price_yahoo"):
                    fallback = prices.yahoo_fallback_issuers(con, params)
                else:
                    typer.echo("note: run `sentinel prices` first to include Yahoo fallbacks")
    except (duckdb.IOException, warehouse.MissingInput) as e:
        _fail(str(e), FAILED)
    except OutsidePaidWindow as e:
        _fail(str(e), OUTSIDE_PAID_WINDOW)
    try:
        with FetchLock(paths.lock):
            if source == "yahoo":
                r = yahoo.download(
                    paths, params, tickers, limit=limit, retry_failures=retry_failures,
                    echo=typer.echo,
                )  # fmt: skip
                typer.echo(
                    f"yahoo: {r.stored:,} stored, {r.cached:,} already stored, "
                    f"{len(r.failed):,} failed (data/raw/yahoo/failures.csv)"
                )
                raise typer.Exit(OK)
            secrets = _secrets(paths)
            if not secrets.tiingo_api:
                _fail("TIINGO_API is not set in .env", CONFIG)
            if not (paths.tiingo / tiingo.LIST_FILE).exists():
                url = ops["tiingo_supported_tickers_url"]
                payload, _, _ = fetch_list(url, ops["http_timeout_seconds"])
                tiingo.store_list(paths, params, payload, url)
            listing = tiingo.stored_listing(paths, params)
            with warehouse.connect(paths, read_only=True) as con:
                if crosscheck:
                    targets = tiingo.crosscheck_targets(con)
                else:
                    targets = tiingo.resolve(con, listing, params, fallback_issuers=fallback)
            roles = {}
            for t in targets:
                roles[t.role] = roles.get(t.role, 0) + 1
            typer.echo(f"tiingo: {len(targets):,} tickers resolved ({roles})")
            rps = ops["tiingo_requests_per_second"]
            with tiingo.make_client(secrets.tiingo_api, ops["http_timeout_seconds"]) as client:
                r = tiingo.fetch(
                    paths, params, client, targets=targets, limiter=RateLimiter(rps, rps),
                    policy=RetryPolicy.from_ops(ops), limit=limit, echo=typer.echo,
                )  # fmt: skip
            typer.echo(
                f"tiingo: {r.stored:,} stored, {r.cached:,} already done, "
                f"{len(r.not_found):,} not in Tiingo, {len(r.failed):,} failed"
            )
            for ticker, reason in r.failed[:10]:
                typer.echo(f"  {ticker}: {reason}")
    except FetchLocked as e:
        _fail(str(e), FAILED)
    except OutsidePaidWindow as e:
        _fail(str(e), OUTSIDE_PAID_WINDOW)
    except tiingo.TiingoRejected as e:
        _fail(str(e), FAILED)


@app.command("prices", rich_help_panel=P2)
def prices_cmd():
    """[Step 7] Build one as-traded price series per issuer, and the market calendar."""
    raise typer.Exit(_run_steps(["prices"]))


@app.command("tiingo-status", rich_help_panel=P2)
def tiingo_status_cmd():
    """[Step 7] The Tiingo deletion register: stored files and rows, the paid window."""
    from datetime import date

    import duckdb

    from sentinel import warehouse
    from sentinel.core import tiingo_register

    paths, params = _context()
    con = None
    try:
        if paths.warehouse.exists():
            con = warehouse.connect(paths, read_only=True)
        st = tiingo_register.status(con, paths, params)
    except duckdb.IOException as e:
        _fail(str(e), FAILED)
    finally:
        if con is not None:
            con.close()
    if st.paid_until:
        left = (st.paid_until - date.today()).days
        window = f"open until {st.paid_until} ({left} days left)" if st.window_open else "closed"
    else:
        window = "closed: ops.tiingo_paid_until is not set"
    typer.echo(f"Tiingo paid window: {window}")
    typer.echo(f"  raw files: {st.files:,} ({st.bytes / 1e6:,.1f} MB) under data/raw/tiingo/")
    for table, n in st.rows.items():
        typer.echo(f"  {table}: {n:,} Tiingo rows")
    for problem in st.problems:
        typer.echo(f"  PROBLEM: {problem}")
    raise typer.Exit(FAILED if st.problems else OK)


@app.command("tiingo-delete", rich_help_panel=P2)
def tiingo_delete_cmd(
    yes: bool = typer.Option(False, "--yes", help="Really delete (otherwise a dry run)."),
):
    """[End of the paid month] Delete every Tiingo file and Tiingo-derived row (constitution VI)."""
    import duckdb

    from sentinel.core import tiingo_register

    paths, params = _context()
    try:
        report = tiingo_register.delete(paths, params, yes=yes)
    except duckdb.IOException as e:
        _fail(f"{e}\nClose `sentinel explore` and any running step first.", FAILED)
    typer.echo(f"{report.files:,} files ({report.bytes / 1e6:,.1f} MB)")
    for table, n in report.rows.items():
        typer.echo(f"  {table}: {n:,} rows")
    if not yes:
        typer.echo("dry run: nothing deleted. Run with --yes to delete.")
        raise typer.Exit(USAGE)
    typer.echo("deleted. Record this line in docs/initialplan.md §12:")
    typer.echo(f"  {report.log_line}")


@app.command("fetch-reference", rich_help_panel=P2)
def fetch_reference_cmd():
    """[Step 7] Download the French library files and FINRA's tick-size pilot change file."""
    import httpx

    from sentinel.ingest import finra, french
    from sentinel.ingest.manifest import FetchLock, FetchLocked

    paths, params = _context()
    try:
        with FetchLock(paths.lock):
            done = french.fetch(paths, params, echo=typer.echo)
            done[finra.FILE] = finra.fetch(paths, params, echo=typer.echo)
    except FetchLocked as e:
        _fail(str(e), FAILED)
    except httpx.HTTPError as e:
        _fail(f"download failed: {e}", FAILED)
    kept = sum(1 for v in done.values() if v == "kept")
    typer.echo(f"reference files: {len(done) - kept} stored, {kept} already stored")


@app.command("reference", rich_help_panel=P2)
def reference_cmd():
    """[Step 7] Load factors, industries, SIC definitions, breakpoints and tick-pilot intervals."""
    raise typer.Exit(_run_steps(["reference"]))


@app.command("detect", rich_help_panel=P2)
def detect_cmd(
    fetch_missing_headers: bool = typer.Option(
        False, "--fetch-missing-headers", help="Fetch missing signal-filing headers and rerun."
    ),
):
    """[Step 7] Final event detection: G8, G7, the floors and the 63-session cooldown."""
    code = _run_steps(["detect"])
    for _ in range(3):
        if code != CONFIG or not fetch_missing_headers:
            break
        code = _fetch_headers(final=True)
        if code == OK:
            code = _run_steps(["detect"])
    raise typer.Exit(code)


@app.command("coverage", rich_help_panel=P2)
def coverage_cmd():
    """[Step 7–10] Write specs/004-market-data-events/coverage.md (coverage, G8, outcomes)."""
    import duckdb

    from sentinel import warehouse
    from sentinel.events import coverage

    paths, params = _context()
    try:
        with warehouse.connect(paths, read_only=True) as con:
            warehouse.require_tables(con, ["audit.price_coverage", "audit.g8_rate"], "detect")
            out = paths.reports_004 / "coverage.md"
            coverage.write_report(con, params, out)
    except (duckdb.IOException, warehouse.MissingInput) as e:
        _fail(str(e), FAILED)
    typer.echo(f"wrote {out.relative_to(paths.root)}")


@app.command("fetch-company", rich_help_panel=P2)
def fetch_company_cmd():
    """[Steps 8–9] Download the SEC's bulk companyfacts.zip and submissions.zip (about 3 GB)."""
    from sentinel.ingest import sec_company
    from sentinel.ingest.http import RetryExhausted, SecForbidden
    from sentinel.ingest.manifest import FetchLock, FetchLocked

    paths, params = _context()
    secrets = _secrets(paths)
    client, limiter, policy = _sec_net(params, secrets)
    try:
        with FetchLock(paths.lock), client:
            done = sec_company.fetch(paths, params, client, limiter, policy, echo=typer.echo)
    except FetchLocked as e:
        _fail(str(e), FAILED)
    except SecForbidden as e:
        _fail(f"{e}. The SEC rejected the client; check SEC_USER_AGENT in .env.", SEC_FORBIDDEN)
    except RetryExhausted as e:
        _fail(str(e), FAILED)
    typer.echo(", ".join(f"{k}: {v}" for k, v in done.items()))


@app.command("company-facts", rich_help_panel=P2)
def company_facts_cmd():
    """[Steps 8–9] Load issuer profiles, filing histories and first-filed XBRL facts."""
    raise typer.Exit(_run_steps(["company"]))


@app.command("delistings", rich_help_panel=P2)
def delistings_cmd():
    """[Step 8] Classify early-ending price series and assign delisting returns."""
    raise typer.Exit(_run_steps(["delistings"]))


@app.command("costs", rich_help_panel=P2)
def costs_cmd():
    """[Step 10] Estimate spreads and round-trip costs per event; write costs.md."""
    raise typer.Exit(_run_steps(["costs"]))


@app.command("prereg-status", rich_help_panel=P2)
def prereg_status_cmd():
    """[Step 10a] Check the prereg-v1 tag: labels, features and the dataset need it."""
    from sentinel import lock

    paths = _paths()
    reason = lock.problem(paths.root, paths.params_file)
    if reason is not None:
        _fail(f"not locked: {reason}", NOT_LOCKED)
    typer.echo(f"locked: {lock.TAG} exists and config/params.yaml matches it")


@app.command("labels", rich_help_panel=P2)
def labels_cmd():
    """[Step 11] Development labels (windows ending by 31 December 2022); needs prereg-v1."""
    raise typer.Exit(_run_steps(["labels"]))


@app.command("features", rich_help_panel=P2)
def features_cmd():
    """[Step 12] Features F1–F29 as of T; needs prereg-v1 (F10 uses past returns)."""
    raise typer.Exit(_run_steps(["features"]))


@app.command("lookup", rich_help_panel=P2)
def lookup_cmd():
    """[Step P] Build data/lookup.duckdb for the stock lookup, from SEC tables only (offline)."""
    import duckdb

    from sentinel import warehouse
    from sentinel.api import lookup

    paths, params = _context()
    if not paths.warehouse.exists():
        _fail(f"{paths.warehouse} not found: run `sentinel stage` first", CONFIG)
    started = time.monotonic()
    try:
        report = lookup.build(paths, params)
    except warehouse.MissingInput as e:
        _fail(str(e), CONFIG)
    except duckdb.IOException as e:
        _fail(f"cannot open {paths.warehouse.name}; is a build step running? {e}", FAILED)
    rows = ", ".join(f"{table} {n:,}" for table, n in report.rows.items())
    typer.echo(f"lookup: {rows}")
    typer.echo(
        f"  data as of {report.data_as_of} (SEC data set {report.dataset}); "
        f"wrote {paths.lookup.relative_to(paths.root)} in {time.monotonic() - started:.0f} s"
    )


@app.command("serve", rich_help_panel=P2)
def serve_cmd(
    port: int = typer.Option(8766, "--port", help="Local port (8000 and 8765 are taken)."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to listen on."),
):
    """[Step P] Run the stock lookup page and API on data/lookup.duckdb (read-only)."""
    import socket

    import duckdb
    import uvicorn

    from sentinel import warehouse
    from sentinel.api import queries
    from sentinel.api.app import create_app

    paths = _paths()
    if not paths.lookup.exists():
        _fail(f"{paths.lookup} not found: run `sentinel lookup` first", CONFIG)
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError:
            _fail(f"port {port} is in use: choose another with --port", FAILED)
    con = queries.open_lookup(paths)
    meta = queries.meta(con)
    con.close()
    try:
        with warehouse.connect(paths, read_only=True) as wh:
            latest = wh.execute("select max(finished_at) from core.build_log").fetchone()[0]
        if latest and meta["warehouse_built_at"] and latest > meta["warehouse_built_at"]:
            typer.echo("warning: the warehouse was rebuilt after the lookup: run `sentinel lookup`")
    except duckdb.Error:
        pass  # the warehouse may be busy or absent; the lookup still serves
    typer.echo(f"Stock lookup: http://{host}:{port}  (data as of {meta['date']}; Ctrl-C to stop)")
    uvicorn.run(create_app(paths), host=host, port=port, log_level="warning")


# --- Phase 3 -----------------------------------------------------------------------------------

_stub("event-study", "13", P3, "Event study on the development period (H1–H3)")


@app.command("ml-dataset", rich_help_panel=P3)
def ml_dataset_cmd():
    """[Step 14] The ML dataset: folds, slices, purging, weights; needs prereg-v1."""
    raise typer.Exit(_run_steps(["ml-dataset"]))


_stub("baselines", "15", P3, "Fit and score the six baselines")
_stub("tournament", "16", P3, "Run the 25-configuration model tournament")
_stub("explain", "17", P3, "SHAP explanations and error analysis")

# --- Phase 4 -----------------------------------------------------------------------------------

_stub("holdout", "18", P4, "Guarded one-time holdout evaluation")
_stub("score-live", "19", P4, "Refit the production model and score the latest clusters")
_stub("robustness", "20", P4, "Pre-listed sensitivity variants (development period)")
_stub("report", "21", P4, "Final report and offline rebuild check")
