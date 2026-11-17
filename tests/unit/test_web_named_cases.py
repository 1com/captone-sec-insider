"""The app's named cases (026, T019): the reasons a page gives when it has no dilution forecast,
and the check's own rules (typed-in dates, the reason expected, equal values)."""

from datetime import date

import numpy as np

from sentinel import config
from sentinel.web import named_cases
from sentinel.web.forecast import Forecasts

RULES = config.risk_params(config.paths())["panel"]
# a latest row that meets every rule every question applies (V2-73)
IN_RULES = {"as_of": "2026-11-11", "close": 5.0, "addv20": 50_000.0, "sessions_listed": 900,
            "active_filer": True, "shares_outstanding": 2_000_000.0}  # fmt: skip


def _reason(facts: dict, listed: bool = True, card: dict | None = None, current=()) -> str:
    f = Forecasts.__new__(Forecasts)  # no model loaded: only the reasons are tested
    f.by_cik, f.current, f._rules = {}, set(current), RULES
    return f.for_company("1", card or {}, listed, facts)["reason"]


def test_each_missing_forecast_states_its_own_reason():
    assert "V2-27" in _reason({"filer_type": "foreign", "has_prices": True})
    assert "blank-check" in _reason({"is_blank_check": True, "has_prices": False})
    assert "V2-66" in _reason({"is_blank_check": True, "has_prices": False}, listed=False)
    assert "no longer trade" in _reason({"has_prices": True}, listed=False)
    assert "no share prices" in _reason({"has_prices": False})
    assert "no recent price" in _reason({"has_prices": True})
    assert "funds" in _reason({"has_prices": True, "is_fund": True}, current={"1"})
    assert "below $1.00" in _reason({"has_prices": True}, card={**IN_RULES, "close": 0.4},
                                    current={"1"})  # fmt: skip
    assert "not complete" in _reason({"has_prices": True}, card=IN_RULES, current={"1"})


def test_the_check_expects_the_same_reasons():
    def expect(facts: dict, card: dict, row: dict | None = None) -> str:
        return named_cases.expected_reason(facts, card, RULES, row)

    assert expect({"filer_type": "foreign"}, {}) == "foreign"
    assert expect({"is_blank_check": True, "listed": True}, {}) == "blank-check"
    assert expect({"listed": False, "has_prices": True}, {}) == "no longer trade"
    assert expect({"listed": True, "has_prices": False}, {}) == "no share prices"
    assert expect({"listed": True, "has_prices": True}, {}) == "no recent price"
    assert expect({"listed": True, "has_prices": True}, IN_RULES) == "not complete"
    # the rules are checked on the build database's own row when there is one (numpy values)
    row = {**IN_RULES, "close": np.float64(0.4), "active_filer": np.bool_(False)}
    assert expect({"listed": True, "has_prices": True}, IN_RULES, row) == (
        "the share price is below $1.00")  # fmt: skip
    ok = {"has_prices": True, "listed": True}
    quiet = {**IN_RULES, "active_filer": np.bool_(False)}
    assert expect(ok, IN_RULES, quiet) == "filed nothing with the SEC"
    for facts, card, listed, current in (
        ({"filer_type": "foreign", "has_prices": True, "listed": True}, {}, True, ()),
        ({"is_blank_check": True, "has_prices": False, "listed": True}, {}, True, ()),
        ({"has_prices": True, "listed": False}, {}, False, ()),
        ({"has_prices": False, "listed": True}, {}, True, ()),
        ({"has_prices": True, "listed": True}, {}, True, ()),
        (ok, {**IN_RULES, "close": 0.4}, True, {"1"}),
        (ok, {**IN_RULES, "addv20": 900.0}, True, {"1"}),
        (ok, {**IN_RULES, "addv20": None}, True, {"1"}),
        (ok, {**IN_RULES, "sessions_listed": 30}, True, {"1"}),
        (ok, {**IN_RULES, "active_filer": False}, True, {"1"}),
        (ok, {**IN_RULES, "close": 0.4, "addv20": 900.0}, True, {"1"}),
        (ok, {**IN_RULES, "eligible_dilution": True}, True, {"1"}),
        (ok, {**IN_RULES, "eligible_dilution": True, "shares_outstanding": None}, True, {"1"}),
        (
            ok,
            {
                **IN_RULES,
                "eligible_dilution": True,
                "shares_outstanding": np.nan,
                "filer_type": "non_reporting",
            },
            True,
            {"1"},
        ),  # fmt: skip
        (
            ok,
            {
                **IN_RULES,
                "eligible_dilution": True,
                "market_cap": 1_000_000.0,
                "addv20": 50_000_000.0,
            },
            True,
            {"1"},
        ),  # fmt: skip
        (ok, IN_RULES, True, {"1"}),
    ):
        assert expect(facts, card) in _reason(facts, listed, card, current), card
    # V2-74: in the question but no share count: the check reads the build database's row
    missing = {**IN_RULES, "shares_outstanding": np.float64("nan")}
    assert expect(ok, {**IN_RULES, "eligible_dilution": True}, missing) == "share count"
    # V2-75: the trading rules out the share count, on the build database's row too
    thousands = {**IN_RULES, "market_cap": np.float64(1e6), "addv20": np.float64(5e7)}
    assert expect(ok, {**IN_RULES, "eligible_dilution": True}, thousands) == (
        "more than 10 times the company's market value")  # fmt: skip
    ten = {**thousands, "addv20": np.float64(1e7)}
    assert expect(ok, {**IN_RULES, "eligible_dilution": True}, ten) == "No forecast yet"


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
