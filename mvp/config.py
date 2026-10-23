"""Paths, parameters and the pilot-sample guard for the MVP.

Everything the MVP writes lives under data/mvp/ (constitution, Prototype Exception).
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from sentinel.config import Paths, load_params, registered_value, repo_root

ROOT = repo_root(Path(__file__).resolve().parent)
SENTINEL = Paths.from_root(ROOT)
MVP_DIR = ROOT / "mvp"
DATA = ROOT / "data" / "mvp"
RAW = DATA / "raw"
YAHOO = RAW / "yahoo"
MANIFEST = RAW / "manifest.jsonl"
WORK = DATA / "work"
SITE = DATA / "site"
ARTIFACT = DATA / "artifact"


class PilotViolation(Exception):
    """An outcome was requested for an event outside the pre-2012 pilot sample."""


@dataclass(frozen=True)
class Settings:
    research: dict  # config/params.yaml
    mvp: dict  # mvp/params.yaml

    @property
    def pilot_start(self) -> date:
        return _date(self.mvp["pilot"]["start"])

    @property
    def pilot_end(self) -> date:
        return _date(self.mvp["pilot"]["end"])

    @property
    def recent_start(self) -> date:
        return _date(self.mvp["recent"]["start"])

    @property
    def recent_end(self) -> date:
        return _date(self.mvp["recent"]["end"])

    @property
    def label(self) -> str:
        return self.mvp["label"]

    @property
    def horizons(self) -> list[int]:
        return list(registered_value(self.research, "horizons"))

    @property
    def primary_horizon(self) -> int:
        return int(registered_value(self.research, "primary_horizon"))

    @property
    def price_floor(self) -> float:
        return float(registered_value(self.research, "price_floor"))

    @property
    def min_addv(self) -> float:
        return float(registered_value(self.research, "liquidity_floor")["min_addv_usd"])

    @property
    def activity(self) -> tuple[int, int]:
        a = registered_value(self.research, "activity_floor")
        return int(a["min_active_sessions"]), int(a["window_sessions"])

    @property
    def addv_window(self) -> int:
        return int(registered_value(self.research, "spread_addv_window"))

    @property
    def vol_window(self) -> int:
        return int(registered_value(self.research, "volatility_window"))


def _date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def load_settings() -> Settings:
    research = load_params(SENTINEL.params_file)
    mvp = yaml.safe_load((MVP_DIR / "params.yaml").read_text(encoding="utf-8"))
    return Settings(research=research, mvp=mvp)


def assert_pilot(dates, settings: Settings) -> None:
    """Raise unless every date is inside the pilot sample (constitution, Prototype Exception)."""
    for d in dates:
        d = _date(d)
        if not (settings.pilot_start <= d <= settings.pilot_end):
            raise PilotViolation(
                f"outcome requested for {d}; "
                f"only {settings.pilot_start}–{settings.pilot_end} allowed"
            )


def ensure_dirs() -> None:
    for folder in (YAHOO, WORK, SITE, ARTIFACT):
        folder.mkdir(parents=True, exist_ok=True)
