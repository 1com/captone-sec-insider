"""Constitution guards for the MVP (Prototype Exception; spec FR-022)."""

import ast

import pandas as pd

from mvp.config import ROOT, SITE, WORK, load_settings


def mvp_imports_in_production() -> list[str]:
    offenders = []
    for path in (ROOT / "src" / "sentinel").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "mvp" or n.startswith("mvp.") for n in names):
                offenders.append(path.relative_to(ROOT).as_posix())
    return offenders


def run_checks() -> list[str]:
    s = load_settings()
    problems = []
    ret_file = WORK / "pilot_returns.parquet"
    if not ret_file.exists():
        problems.append("no build found: run `uv run python -m mvp build` first")
    else:
        dates = pd.to_datetime(pd.read_parquet(ret_file, columns=["signal_date"])["signal_date"])
        if len(dates) and dates.max().date() > s.pilot_end:
            problems.append(f"outcomes exist after the pilot sample: latest {dates.max().date()}")
        if len(dates) and dates.min().date() < s.pilot_start:
            problems.append(
                f"outcomes exist before the pilot sample: earliest {dates.min().date()}"
            )
    for path in mvp_imports_in_production():
        problems.append(f"production code imports the MVP: {path}")
    page = SITE / "index.html"
    if page.exists():
        html = page.read_text(encoding="utf-8")
        for section in ("overview", "findings", "model", "screener"):
            start = html.find(f'id="{section}"')
            end = html.find("</section>", start)
            if start < 0 or s.label not in html[start:end]:
                problems.append(f"pilot label missing on the {section} tab")
    return problems
