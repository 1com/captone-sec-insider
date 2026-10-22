"""`uv run sentinel <command>` — one command per pipeline step (docs/initialplan.md §9.2).

Commands are registered in step order so `--help` reads as the plan. Steps not built yet exit 4.
Contract: specs/001-skeleton-sec-ingest/contracts/cli.md
"""

import logging

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


# --- Phase 0 -----------------------------------------------------------------------------------


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


_stub("stage", "2", P1, "Load the data sets into typed staging tables")
_stub("entities", "3", P1, "Build point-in-time insider entities and roles")
_stub("gates", "4", P1, "Apply purchase gates G1–G6 and record the funnel")
_stub("detect-prelim", "5", P1, "Preliminary event detection (A, B1, B2)")


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
