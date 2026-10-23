"""Constitution, Prototype Exception: pilot-only outcomes, containment, labels (spec FR-022)."""

import math

import numpy as np
import pandas as pd
import pytest

from mvp.checks import mvp_imports_in_production, run_checks
from mvp.config import SITE, WORK, load_settings
from mvp.pipeline.study import block_bootstrap
from mvp.pipeline.universe import choose_ticker
from mvp.util import json_safe

S = load_settings()


def test_production_code_never_imports_the_mvp():
    assert mvp_imports_in_production() == []


@pytest.mark.skipif(not (WORK / "pilot_returns.parquet").exists(), reason="MVP not built")
def test_stored_outcomes_are_pilot_only():
    dates = pd.to_datetime(pd.read_parquet(WORK / "pilot_returns.parquet")["signal_date"])
    assert dates.max().date() <= S.pilot_end
    assert dates.min().date() >= S.pilot_start


@pytest.mark.skipif(not (SITE / "index.html").exists(), reason="MVP not built")
def test_built_site_passes_every_guard():
    assert run_checks() == []


def test_label_text_is_the_constitution_wording():
    assert S.label == "Pilot sample (2006–2011), survivors only — prototype, not research results"


def test_json_safe_removes_nan():
    out = json_safe({"a": [1.0, math.nan], "b": np.float64("inf"), "c": "x"})
    assert out == {"a": [1.0, None], "b": None, "c": "x"}


def test_choose_ticker_prefers_common_stock():
    assert choose_ticker([("CDR-PB", "NYSE"), ("CDR-PC", "NYSE")], "CDR") is None
    assert choose_ticker([("TAP-A", "NYSE"), ("TAP", "NYSE")], "TAP") == ("TAP", "NYSE")
    assert choose_ticker([("BRK-A", "NYSE"), ("BRK-B", "NYSE")], "BRK.B") == ("BRK-B", "NYSE")
    assert choose_ticker([("ABCW", "Nasdaq"), ("ABC", "Nasdaq")], None) == ("ABC", "Nasdaq")


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    rng = np.random.default_rng(0)
    values = rng.normal(0.02, 0.1, size=600)
    months = pd.Series(pd.period_range("2006-01", periods=60, freq="M").astype(str).repeat(10))
    lo1, hi1 = block_bootstrap(values, months, 3, 500, np.random.default_rng(7))
    lo2, hi2 = block_bootstrap(values, months, 3, 500, np.random.default_rng(7))
    assert (lo1, hi1) == (lo2, hi2)
    assert lo1[0] < values.mean() < hi1[0]
