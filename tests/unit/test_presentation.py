"""The hand-in's number sheet (019): every number equals its source, rounded as the contract says;
a missing input is refused before anything is written; identical inputs give an identical file."""

import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from sentinel import config
from sentinel import presentation as pres

ROOT = Path(__file__).resolve().parents[2]
CARD = json.loads((ROOT / pres.CARD).read_text(encoding="utf-8"))

CATCHING_UP = """\
# Dilution: forecasts that catch up with an announced sale

## 1. How often an answer of 1 was already announced (2012 to 2022-06-30)

| year | answers of 1 | of them announced | answers of 0 with a filing |
|---|---|---|---|
| 2012 | 2,473 | 0.406 | 0.063 |
| all | 40,475 | 0.411 | 0.069 |

Strict:

| year | answers of 1 | of them announced | answers of 0 with a filing |
|---|---|---|---|
| all | 40,475 | 0.342 | 0.043 |

## 2. The approved model with and without them (test years 2019-2022)

| test rows | rows | answers of 1 | rate | AUC | band 5 rows | band 5 rate |
|---|---|---|---|---|---|---|
| all test rows | 149,302 | 16,517 | 0.111 | 0.892 | 30,141 | 0.410 |
| announced | 17,263 | 6,934 | 0.402 | 0.810 | 11,545 | 0.544 |
| nothing announced | 132,039 | 9,583 | 0.073 | 0.872 | 18,596 | 0.327 |
"""

AUDIT = """\
# Price coverage audit

| Measure | Before | After |
|---|---:|---:|
| Listed companies (in today's SEC list or their last one) | 7,351 | 7,351 |
| Cut although stored prices reach further back (companies) | 1,162 | 335 |
| ... company-months of 2012-2022 they lack | 51,441 | 11,973 |
| Ticker-days given to two companies (one provider) | 83,024 | 0 |

Named cases: 18 of 18 pass.
"""


def _by_id(numbers: list[pres.Number]) -> dict[str, pres.Number]:
    return {n.id: n for n in numbers}


def _card_row(question: str, level: str, year: str) -> dict:
    block = CARD[question]["holdout"]["results"]
    for row in block["data"]:
        r = dict(zip(block["columns"], row, strict=True))
        if r["level"].removesuffix(" (chosen)") == level and str(r["year"]) == year:
            return r
    raise KeyError((question, level, year))


def _years(question: str) -> list[str]:
    return sorted({str(r[1]) for r in CARD[question]["holdout"]["results"]["data"]} - {"all"})


def test_the_rounding_of_the_contract():
    assert pres.dec(0.22918, 3) == "0.229"
    assert pres.dec(0.9075, 2) == "0.91"
    assert pres.pct(0.0031) == "0.3%"
    assert pres.pct(0.4228) == "42%"
    assert pres.pct(0.1197) == "12%"
    assert pres.count(148067) == "148,067"
    assert pres.ratio(5.055) == "5.1×"
    assert pres.day("2023-01-31") == "31 Jan 2023"
    assert pres.years_shown(["2023"], ["2023", "2024"]) == "1 of 2 (2023)"
    assert pres.years_shown([], ["2023"]) == "0 of 1"


def test_the_card_numbers_equal_the_model_card():
    got = _by_id(pres.from_card(CARD))
    for level in pres.LEVELS["dilution"]:
        row = _card_row("dilution", level, "all")
        assert got[f"dil.ll.{level}"].value == row["log_loss"]
        assert got[f"dil.ll.{level}"].shown == pres.dec(row["log_loss"], 3)
        assert got[f"dil.auc.{level}"].value == row["auc"]
    for level in pres.LEVELS["results_move"]:
        assert (
            got[f"mov.ll.{level}"].value == _card_row("results_move", level, "all")["log_loss_mean"]
        )
    for level in pres.LEVELS["volatility"]:
        assert got[f"vol.mae.{level}"].value == _card_row("volatility", level, "all")["mae_log"]
    assert (
        got["vol.cov80.lightgbm"].value == _card_row("volatility", "lightgbm", "all")["coverage_80"]
    )
    assert (
        got["dil.lift10.lightgbm"].value == _card_row("dilution", "lightgbm", "all")["lift_top10"]
    )
    assert got["dil.rows"].value == CARD["dilution"]["holdout"]["rows"]

    # the per-year verdicts and the weighted rate, computed here a second way
    years = _years("dilution")
    best = [
        y
        for y in years
        if min(
            pres.LEVELS["dilution"], key=lambda lv, y=y: _card_row("dilution", lv, y)["log_loss"]
        )
        == "lightgbm"
    ]
    assert got["dil.best_years"].value == ", ".join(best)
    ridge = [
        y
        for y in _years("results_move")
        if _card_row("results_move", "ridge", y)["log_loss_mean"]
        < _card_row("results_move", "lightgbm", y)["log_loss_mean"]
    ]
    assert got["mov.ridge_better_years"].value == ", ".join(ridge)
    bands = CARD["dilution"]["holdout"]["bands"]
    rows = [dict(zip(bands["columns"], r, strict=True)) for r in bands["data"]]
    every = [r for r in rows if r["year"] == "all"]
    rate = sum(r["rows"] * r["real_rate"] for r in every) / sum(r["rows"] for r in every)
    assert got["dil.rate"].value == pytest.approx(rate)
    assert sum(r["rows"] for r in every) == CARD["dilution"]["holdout"]["rows"]
    boosting = [
        CARD["dilution"]["test_years"][y]["boosting"]
        for y in sorted(CARD["dilution"]["test_years"])
    ]
    assert got["dil.test_ll.lightgbm"].value == pytest.approx(sum(boosting) / len(boosting))


def test_the_one_time_test_as_it_came_out():
    """The holdout ran once (12 Nov 2026, V2-69): these numbers never change."""
    got = {n.id: n.shown for n in pres.from_card(CARD)}
    assert got["dil.rows"] == "148,067"
    assert (got["dil.first"], got["dil.last"]) == ("31 Jan 2023", "30 Apr 2026")
    assert (got["dil.ll.lightgbm"], got["dil.ll.logistic"]) == ("0.229", "0.256")
    assert (got["dil.ll.rule"], got["dil.ll.base_rate"]) == ("0.311", "0.369")
    assert got["dil.auc.lightgbm"] == "0.91"
    assert got["dil.best_years"] == "4 of 4 (2023, 2024, 2025, 2026)"
    assert got["dil.test_ll.lightgbm"] == "0.226"
    assert (got["mov.ll.lightgbm"], got["mov.ll.ridge"]) == ("0.467", "0.452")
    assert (got["vol.mae.lightgbm"], got["vol.mae.ridge"]) == ("0.252", "0.253")


def test_a_card_without_a_test_or_a_level_is_refused():
    no_test = json.loads(json.dumps(CARD))
    del no_test["volatility"]["holdout"]
    with pytest.raises(pres.Refused, match="no one-time test for volatility"):
        pres.from_card(no_test)
    no_level = json.loads(json.dumps(CARD))
    block = no_level["dilution"]["holdout"]["results"]
    block["data"] = [r for r in block["data"] if not r[0].startswith("logistic")]
    with pytest.raises(pres.Refused, match="no row for logistic"):
        pres.from_card(no_level)


def test_the_reports_tables_are_read_by_their_columns():
    cu = _by_id(pres.from_catching_up(CATCHING_UP))
    assert cu["cu.announced"].value == 0.411  # the first table of section 1, not the strict one
    assert (cu["cu.auc_all"].shown, cu["cu.auc_none"].shown) == ("0.89", "0.87")
    assert (cu["cu.band5_all"].shown, cu["cu.band5_none"].shown) == ("41%", "33%")
    au = _by_id(pres.from_audit(AUDIT))
    assert (au["audit.months_before"].value, au["audit.months_after"].value) == (51441, 11973)
    assert (au["audit.twice_before"].shown, au["audit.twice_after"].shown) == ("83,024", "0")
    assert (au["audit.cut_before"].value, au["audit.cut_after"].value) == (1162, 335)
    assert au["audit.named"].shown == "18 of 18"
    # the committed reports read without a refusal
    pres.from_catching_up((ROOT / pres.CATCHING_UP).read_text(encoding="utf-8"))
    pres.from_audit((ROOT / pres.AUDIT).read_text(encoding="utf-8"))


def test_a_report_without_its_table_is_refused():
    with pytest.raises(pres.Refused, match="no section '## 2.'"):
        pres.from_catching_up(CATCHING_UP.split("## 2.")[0])
    with pytest.raises(pres.Refused, match="named-case line"):
        pres.from_audit(AUDIT.replace("Named cases: 18 of 18 pass.", ""))


def _serving(path: Path, scores: bool = True) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute("create schema app")
        con.execute("create table app.company_card (cik varchar, as_of date)")
        con.execute("create table app.daily_score (cik varchar, as_of date, question varchar)")
        con.execute(
            "insert into app.company_card values ('1', '2026-11-13'), ('2', '2026-11-10'), "
            "('3', '2026-10-01')"
        )
        if scores:
            con.execute(
                "insert into app.daily_score values ('1', '2026-11-13', 'dilution'), "
                "('2', '2026-11-12', 'dilution'), ('9', '2026-11-13', 'volatility')"
            )


def test_the_app_counts_come_from_the_serving_copy(tmp_path):
    _serving(tmp_path / "serving.duckdb")
    with duckdb.connect(str(tmp_path / "serving.duckdb"), read_only=True) as con:
        got = _by_id(pres.from_serving(con))
    assert got["app.date"].value == date(2026, 11, 13).isoformat()
    assert got["app.date"].shown == "13 Nov 2026"
    assert got["app.companies"].value == 2  # the one of 1 Oct is not still trading
    assert got["app.forecasts"].value == 2  # the dilution forecasts only
    _serving(tmp_path / "empty.duckdb", scores=False)
    with (
        duckdb.connect(str(tmp_path / "empty.duckdb"), read_only=True) as con,
        pytest.raises(pres.Refused, match="no dilution forecast"),
    ):
        pres.from_serving(con)


def test_the_sheet_is_identical_on_identical_inputs_and_refused_without_one(tmp_path):
    reports = tmp_path / "docs" / "report"
    reports.mkdir(parents=True)
    for rel in (pres.CARD, pres.CATCHING_UP, pres.AUDIT):
        shutil.copy(ROOT / rel, tmp_path / rel)
    (tmp_path / "data").mkdir()
    p = config.Paths.from_root(tmp_path)
    _serving(p.serving_db)
    out = pres.main(p, echo=lambda *_: None)
    first = out.read_text(encoding="utf-8")
    assert pres.main(p, echo=lambda *_: None).read_text(encoding="utf-8") == first
    assert "| `dil.ll.lightgbm` |" in first and "## Terms" in first
    assert "serving copy of 13 Nov 2026" in first

    (tmp_path / pres.CARD).unlink()
    with pytest.raises(pres.Refused, match="model card is missing"):
        pres.main(p, echo=lambda *_: None)
    assert out.read_text(encoding="utf-8") == first  # the earlier sheet is untouched
