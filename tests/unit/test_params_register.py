"""config/params.yaml must mirror docs/initialplan.md Appendix E (contracts/params-schema.md)."""

import re
from datetime import date

from conftest import REPO

from sentinel.config import check_register, parse_appendix_e
from sentinel.ingest.sec_bulk import quarters_in_range

PLAN = REPO / "docs" / "initialplan.md"


def test_appendix_e_has_34_rows():
    rows = parse_appendix_e(PLAN)
    assert len(rows) == 34
    assert rows[0] == ("Insider data period", "2006 Q1 – 2026 Q3", "—")
    assert rows[-1][0] == "Model grids"


def test_params_mirror_the_register_verbatim(params):
    assert check_register(params, PLAN) == []


def test_drift_is_detected(params):
    params["registered"]["g6_min_value"]["register"]["value"] = "$20,000 per entity per filing"
    del params["registered"]["model_grids"]
    params["registered"]["invented"] = {"value": 1, "register": {"parameter": "Invented"}}
    problems = check_register(params, PLAN)
    assert any("G6 minimum value" in p for p in problems)
    assert any("Model grids" in p for p in problems)
    assert any("Invented" in p for p in problems)


def test_unregistered_sections_carry_no_register_block(params):
    for section in ("ops", "provisional"):
        for key, value in params[section].items():
            assert not (isinstance(value, dict) and "register" in value), f"{section}.{key}"


def test_values_this_feature_uses(params):
    reg = params["registered"]
    assert reg["g6_min_value"]["value"] == 10000
    assert reg["g6_timeliness"]["value"] == 30
    assert reg["cluster_window"]["value"] == 14
    assert reg["cluster_min_value"]["value"] == 100000
    assert date.fromisoformat(str(reg["labelled_window_start"]["value"])) == date(2012, 1, 1)
    period = reg["insider_data_period"]["value"]
    assert len(quarters_in_range(str(period["start"]), str(period["end"]))) == 83
    assert params["ops"]["sec_max_requests_per_second"] <= 10


def test_provisional_regexes_compile(params):
    for key, pattern in params["provisional"].items():
        if key.endswith("_regex"):
            re.compile(pattern, re.IGNORECASE)
