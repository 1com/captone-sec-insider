"""Paths, the parameter file and secrets.

Secrets come only from the git-ignored `.env` (constitution Principle VI) and are never exported
into the process environment. Any secret value is masked by `redact()` and `RedactingFilter`.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import dotenv_values

SECTIONS = ("registered", "ops", "rules", "provisional")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
SEC_RPS_CEILING = 10  # SEC fair-access policy

_secret_values: set[str] = set()


class ConfigError(Exception):
    """The environment or the parameter file is unusable (CLI exit code 3)."""


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").is_file():
            return folder
    raise ConfigError("cannot find the repository root (no pyproject.toml above this folder)")


@dataclass(frozen=True)
class Paths:
    root: Path
    data_raw: Path
    sec_insider: Path
    sec_reference: Path
    manifest: Path
    lock: Path
    provisional: Path
    warehouse: Path
    sec_headers: Path
    audits: Path
    params_file: Path
    env_file: Path
    plan_file: Path

    @classmethod
    def from_root(cls, root: Path) -> Paths:
        raw = root / "data" / "raw"
        return cls(
            root=root,
            data_raw=raw,
            sec_insider=raw / "sec" / "insider",
            sec_reference=raw / "sec" / "reference",
            manifest=raw / "manifest.jsonl",
            lock=raw / ".lock",
            provisional=root / "data" / "provisional",
            warehouse=root / "data" / "warehouse.duckdb",
            sec_headers=raw / "sec" / "headers",
            audits=root / "specs" / "002-insider-warehouse" / "audits",
            params_file=root / "config" / "params.yaml",
            env_file=root / ".env",
            plan_file=root / "docs" / "initialplan.md",
        )


def load_params(path: Path) -> dict:
    try:
        params = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"parameter file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"parameter file is not valid YAML: {e}") from e
    if not isinstance(params, dict):
        raise ConfigError("parameter file must be a mapping")

    missing = [s for s in SECTIONS if not isinstance(params.get(s), dict)]
    if missing:
        raise ConfigError(f"parameter file lacks section(s): {', '.join(missing)}")
    seen: dict[str, str] = {}
    for section in SECTIONS:
        for key in params[section]:
            if key in seen:
                raise ConfigError(
                    f"parameter '{key}' appears in both '{seen[key]}' and '{section}'"
                )
            seen[key] = section

    ops = params["ops"]
    ceiling = ops.get("sec_max_requests_per_second", 0)
    if ceiling > SEC_RPS_CEILING:
        raise ConfigError(f"ops.sec_max_requests_per_second must be <= {SEC_RPS_CEILING}")
    if ops.get("sec_header_target_requests_per_second", 0) > ceiling:
        raise ConfigError(
            "ops.sec_header_target_requests_per_second must be <= ops.sec_max_requests_per_second"
        )
    for section in ("rules", "provisional"):
        for key, pattern in params[section].items():
            if key.endswith("_regex"):
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    raise ConfigError(f"{section}.{key} does not compile: {e}") from e
    return params


def parse_appendix_e(plan_path: Path) -> list[tuple[str, str, str]]:
    """(Parameter, Value, Sensitivity) cells of the Appendix E table, in order."""
    lines = plan_path.read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("## Appendix E"))
    table = []
    for line in lines[start + 1 :]:
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    rows = []
    for line in table[2:]:  # header and |---| separator
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append((cells[0], cells[1], cells[3]))
    return rows


def check_register(params: dict, plan_path: Path) -> list[str]:
    """Problems between `registered` and Appendix E (contracts/params-schema.md rules 1–4)."""
    problems = []
    by_name: dict[str, list[tuple[str, dict]]] = {}
    for key, entry in params["registered"].items():
        name = (entry.get("register") or {}).get("parameter")
        if name is None:
            problems.append(f"registered.{key} has no register block")
            continue
        by_name.setdefault(name, []).append((key, entry["register"]))
    plan_names = set()
    for parameter, value, sensitivity in parse_appendix_e(plan_path):
        plan_names.add(parameter)
        matches = by_name.get(parameter, [])
        if len(matches) != 1:
            problems.append(f"Appendix E row '{parameter}' has {len(matches)} entries in params")
            continue
        key, reg = matches[0]
        for field_name, expected in (("value", value), ("sensitivity", sensitivity)):
            if str(reg.get(field_name, "")).strip() != expected:
                problems.append(
                    f"registered.{key}.register.{field_name} differs from Appendix E row "
                    f"'{parameter}': {reg.get(field_name)!r} != {expected!r}"
                )
    for name in sorted(set(by_name) - plan_names):
        problems.append(f"registered entry '{name}' has no Appendix E row")
    for section in ("ops", "rules", "provisional"):
        for key, value in params[section].items():
            if isinstance(value, dict) and "register" in value:
                problems.append(f"{section}.{key} must not carry a register block")
    return problems


def registered_value(params: dict, key: str):
    return params["registered"][key]["value"]


def params_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Secrets:
    sec_user_agent: str
    tiingo_api: str | None
    warnings: list[str] = field(default_factory=list)


def load_secrets(env_path: Path) -> Secrets:
    if not env_path.is_file():
        raise ConfigError(f".env not found at {env_path}")
    values = dotenv_values(env_path)

    tiingo = (values.get("TIINGO_API") or "").strip() or None
    if tiingo:
        register_secret(tiingo)

    agent = (values.get("SEC_USER_AGENT") or "").strip()
    if not agent:
        raise ConfigError('SEC_USER_AGENT is not set in .env (use "Your Name your@email")')
    if not EMAIL_RE.search(agent):
        raise ConfigError("SEC_USER_AGENT must contain an e-mail address (SEC fair-access policy)")
    warnings = []
    if EMAIL_RE.fullmatch(agent):
        warnings.append('SEC_USER_AGENT has no name; the SEC asks for "Your Name your@email"')
    return Secrets(sec_user_agent=agent, tiingo_api=tiingo, warnings=warnings)


def register_secret(value: str) -> None:
    if len(value) >= 4:
        _secret_values.add(value)


def redact(text: str) -> str:
    for value in _secret_values:
        text = text.replace(value, "***")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True
