"""Paths, settings and secrets.

Settings: `config/sources.yaml` (where data comes from, rate limits), `config/risk_params.yaml`
(the registered risk definitions, tag `prereg-risk-v5`, never edited) and `config/tracker.yaml`
(the insider tracker's rules). Secrets come only from the git-ignored `.env` and are never
exported into the process environment.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from dotenv import dotenv_values


class ConfigError(Exception):
    """The environment or a settings file is unusable (CLI exit code 3)."""


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").is_file():
            return folder
    raise ConfigError("cannot find the repository root (no pyproject.toml above this folder)")


@dataclass(frozen=True)
class Paths:
    """Every location the project reads or writes (docs/architecture.md)."""

    root: Path
    data: Path
    raw: Path
    manifest: Path
    lock: Path
    sec_insider: Path
    sec_company: Path
    sec_headers: Path
    sec_reference: Path
    yahoo: Path
    tiingo: Path
    fred: Path
    cboe: Path
    finra: Path
    french: Path
    build_db: Path
    serving_db: Path
    exports: Path
    mlflow_db: Path
    reports: Path
    sources_file: Path
    risk_params_file: Path
    tracker_file: Path
    env_file: Path

    @classmethod
    def from_root(cls, root: Path) -> Paths:
        data = root / "data"
        raw = data / "raw"
        return cls(
            root=root,
            data=data,
            raw=raw,
            manifest=raw / "manifest.jsonl",
            lock=raw / ".lock",
            sec_insider=raw / "sec" / "insider",
            sec_company=raw / "sec" / "company",
            sec_headers=raw / "sec" / "headers",
            sec_reference=raw / "sec" / "reference",
            yahoo=raw / "yahoo",
            tiingo=raw / "tiingo",
            fred=raw / "fred",
            cboe=raw / "cboe",
            finra=raw / "finra",
            french=raw / "french",
            build_db=data / "sentinel.duckdb",
            serving_db=data / "serving.duckdb",
            exports=data / "exports",
            mlflow_db=data / "mlflow.db",
            reports=root / "reports",
            sources_file=root / "config" / "sources.yaml",
            risk_params_file=root / "config" / "risk_params.yaml",
            tracker_file=root / "config" / "tracker.yaml",
            env_file=root / ".env",
        )


def paths() -> Paths:
    return Paths.from_root(repo_root())


def _yaml(path: Path) -> dict:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"settings file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name} is not valid YAML: {e}") from e
    if not isinstance(doc, dict):
        raise ConfigError(f"{path.name} must be a mapping")
    return doc


def sources(p: Paths) -> dict:
    """`config/sources.yaml`, checked for the sections every fetcher relies on."""
    doc = _yaml(p.sources_file)
    missing = [s for s in ("http", "sec", "prices", "tiingo") if not isinstance(doc.get(s), dict)]
    if missing:
        raise ConfigError(f"sources.yaml lacks section(s): {', '.join(missing)}")
    if doc["sec"]["max_requests_per_second"] > 10:
        raise ConfigError("sec.max_requests_per_second must be at most 10 (SEC fair access)")
    return doc


def risk_params(p: Paths) -> dict:
    return _yaml(p.risk_params_file)


def tracker(p: Paths) -> dict:
    """`config/tracker.yaml`: the insider tracker's rules."""
    doc = _yaml(p.tracker_file)
    missing = [s for s in ("purchase", "cluster", "patterns") if not isinstance(doc.get(s), dict)]
    if missing:
        raise ConfigError(f"tracker.yaml lacks section(s): {', '.join(missing)}")
    return doc


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Secrets:
    sec_user_agent: str | None
    fred_api_key: str | None
    tiingo_api: str | None


def secrets(p: Paths) -> Secrets:
    """`.env` values, read without touching the process environment."""
    values = dotenv_values(p.env_file) if p.env_file.exists() else {}

    def get(name: str) -> str | None:
        return (values.get(name) or "").strip() or None

    return Secrets(get("SEC_USER_AGENT"), get("FRED_API_KEY"), get("TIINGO_API"))


def in_tiingo_window(settings: dict, today: date | None = None) -> bool:
    """Whether new Tiingo files may be written today (the paid month only)."""
    t = settings["tiingo"]
    day = today or date.today()
    return t["paid_from"] <= day < t["paid_until"]
