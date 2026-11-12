"""The app's named cases (026, T019): the reasons a page gives when it has no dilution forecast,
and the check's own rules (typed-in dates, the reason expected, equal values)."""

from datetime import date

import numpy as np

from sentinel.web import named_cases
from sentinel.web.forecast import Forecasts


def _reason(facts: dict, listed: bool = True, card: dict | None = None, current=()) -> str:
    f = Forecasts.__new__(Forecasts)  # no model loaded: only the reasons are tested
    f.by_cik, f.current = {}, set(current)
    return f.for_company("1", card or {}, listed, facts)["reason"]


def test_each_missing_forecast_states_its_own_reason():
    assert "V2-27" in _reason({"filer_type": "foreign", "has_prices": True})
    assert "blank-check" in _reason({"is_blank_check": True, "has_prices": False})
    assert "V2-66" in _reason({"is_blank_check": True, "has_prices": False}, listed=False)
    assert "no longer trade" in _reason({"has_prices": True}, listed=False)
    assert "no share prices" in _reason({"has_prices": False})
    assert "no recent price" in _reason({"has_prices": True})
    assert "funds" in _reason({"has_prices": True, "is_fund": True}, current={"1"})
    assert "not complete" in _reason({"has_prices": True}, current={"1"})


def test_the_check_expects_the_same_reasons():
    expect = named_cases.expected_reason
    assert expect({"filer_type": "foreign"}, {}) == "foreign"
    assert expect({"is_blank_check": True, "listed": True}, {}) == "blank-check"
    assert expect({"listed": False, "has_prices": True}, {}) == "no longer trade"
    assert expect({"listed": True, "has_prices": False}, {}) == "no share prices"
    assert expect({"listed": True, "has_prices": True}, {}) == "no recent price"
    assert expect({"listed": True, "has_prices": True}, {"as_of": "2026-11-11"}) == "not complete"
    for facts, card, listed in (
        ({"filer_type": "foreign", "has_prices": True, "listed": True}, {}, True),
        ({"is_blank_check": True, "has_prices": False, "listed": True}, {}, True),
        ({"has_prices": True, "listed": False}, {}, False),
        ({"has_prices": False, "listed": True}, {}, True),
        ({"has_prices": True, "listed": True}, {}, True),
    ):
        assert expect(facts, card) in _reason(facts, listed, card)


def test_typed_in_dates_are_found_outside_the_chart_library(tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "static").mkdir()
    (tmp_path / "templates" / "index.html").write_text("<p>Data as of Oct 30, 2026</p>")
    (tmp_path / "static" / "app.js").write_text("const d = row.date; // no literal date")
    (tmp_path / "static" / "lightweight-charts.js").write_text("/* 2021-01-01 */")
    assert named_cases.typed_dates(tmp_path) == ["index.html: Oct 30, 2026"]


def test_equal_values():
    same = named_cases._same
    assert same(1.0, np.float64(1.0 + 1e-12))
    assert same(5, np.int64(5)) and same(5.0, np.int64(5))
    assert same("2021-05-02", date(2021, 5, 2))
    assert same(None, float("nan")) and not same(1.0, None)
    assert not same(1.0, 1.01) and same(True, np.bool_(True))
