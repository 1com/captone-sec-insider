"""The hand-in's number sheet (feature 019).

Every number the slides, the demo path and the README quote, each with an id, its source and its
meaning: the one-time test of the three approved models and the dilution model's test years (the
model card that `sentinel report` writes), the dilution answer's catching-up effect (V2-70) and the
price repair's audit (027) from their generated reports, and three counts of the app today from
the serving copy, read-only. The slides take numbers by id only, so each one can be checked here
(`specs/019-hand-in`, SC-002).

    uv run python -m sentinel.presentation      # seconds; writes docs/presentation/numbers.md

Every number is an aggregate over many companies; none is a price or a value of one company.
Identical inputs give an identical file. A missing input, level, year or table stops the command
before anything is written.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from sentinel import config, db
from sentinel.scoring.daily import CURRENT_DAYS, QUESTION

OUT = Path("docs") / "presentation" / "numbers.md"
CARD = Path("docs") / "report" / "model_card.json"
CATCHING_UP = Path("docs") / "report" / "dilution_catching_up.md"
AUDIT = Path("docs") / "report" / "data_audit.md"

# the levels quoted, simplest first, as the model card names them (" (chosen)" dropped)
LEVELS = {
    "dilution": ("base_rate", "rule", "logistic", "lightgbm"),
    "results_move": ("base_rate", "baseline", "rule", "ridge", "lightgbm"),
    "volatility": ("baseline", "rule", "ridge", "lightgbm"),
}
CHOSEN = "lightgbm"
NAMES = {
    "base_rate": "the base rate",
    "baseline": "the baseline",
    "rule": "the rule",
    "logistic": "the logistic regression",
    "ridge": "the ridge regression",
    "lightgbm": "LightGBM, the approved model",
}
# id prefix and title of each group of the sheet; the first matching prefix wins
GROUPS = (
    ("dil.test_", "Dilution: the test years 2019-2022 (the levels were compared on these)"),
    ("dil.", "Dilution: the one-time test (answers from 2023 on, never seen while building)"),
    ("mov.", "Results-day move: the one-time test"),
    ("vol.", "Volatility: the one-time test"),
    ("cu.", "Dilution: forecasts that catch up with an announced sale (V2-70)"),
    ("audit.", "Price histories: the repair's audit (027)"),
    ("app.", "The app today"),
)
# the audit's measures quoted: id stem, the measure's text in the audit's table, meaning
AUDIT_ROWS = (
    (
        "cut",
        "Cut although stored prices reach further back",
        "companies whose price history was cut short although older prices were stored",
    ),
    (
        "months",
        "company-months of 2012-2022 they lack",
        "company-months of 2012-2022 those cut histories lacked",
    ),
    (
        "twice",
        "Ticker-days given to two companies (one provider)",
        "days on which one provider's price for a ticker was given to two companies",
    ),
)
TERMS = """\
- **Dilution**: the company issues new shares, so each existing share owns a smaller part of it.
  The question: will the shares outstanding rise by 10% or more within six months? (Fixed before
  any model was built: `config/risk_params.yaml`, tag `prereg-risk-v5`.)
- **Chance and band**: the model's forecast that the company dilutes, calibrated so that, of the
  companies given a 30% chance, about 30 in 100 diluted; five bands group the chances, 1 lowest to
  5 highest, each shown with how often its companies diluted.
- **Log loss**: the penalty for each forecast, larger the more confidently wrong it was, averaged
  over all forecasts; lower is better. It judges both the ranking and the size of the chances.
- **AUC**: take one company that diluted and one that did not; the AUC is how often the model gave
  the first the higher chance (0.5 is a coin toss, 1 is perfect).
- **Lift in the top tenth**: how many times as often the tenth with the highest chances diluted as
  all companies did.
- **The levels**: the base rate (every company gets the same chance, the past share that
  diluted); the offering rule (two chances: companies with a share offering filed in the last 12
  months get that group's past rate, the others the others'); a logistic regression; LightGBM
  (many small decision trees, each correcting the ones before). For the other two questions: a
  baseline from the company's own past, a simple rule, a ridge regression (a straight-line model
  kept from leaning too hard on any input) and LightGBM. The simplest level within one standard
  error of the best is chosen.
- **Test years**: 2019-2022; each year's forecasts come from a model trained only on earlier years.
- **The one-time test (holdout)**: the answers from 2023 on were sealed, never computed while the
  models were built, and scored once, on 12 Nov 2026, by a command that refuses a second run.
- **Look-ahead**: using a fact before it was public. Every fact here carries the first day it may
  be used; a quarterly report's share count, for example, only from the day it was filed.
- **Mean absolute log error** (volatility): the typical size of the miss on a log scale; 0.25 means
  a forecast typically off by a factor of about 1.3.
- **80% range**: a range that should hold the outcome 8 times in 10.
"""


class Refused(Exception):
    """An input the sheet needs is missing or incomplete; nothing is written."""


@dataclass(frozen=True)
class Number:
    id: str
    value: float | int | str
    shown: str
    source: str
    meaning: str


# ---------- how numbers are shown (contracts/number-sheet.md) ----------


def dec(x: float, places: int) -> str:
    return f"{x:.{places}f}"


def pct(x: float) -> str:
    """A share as a percentage: one decimal below 1%, else a whole number."""
    return f"{x:.1%}" if x < 0.01 else f"{x:.0%}"


def count(n: int) -> str:
    return f"{n:,}"


def ratio(x: float) -> str:
    return f"{x:.1f}×"


def day(value: str) -> str:
    d = date.fromisoformat(str(value)[:10])
    return f"{d.day} {d:%b %Y}"


def years_shown(chosen: list[str], years: list[str]) -> str:
    return f"{len(chosen)} of {len(years)}" + (f" ({', '.join(chosen)})" if chosen else "")


# ---------- the model card ----------


def _rows(block: dict | None, what: str) -> list[dict]:
    if not block or not block.get("columns") or block.get("data") is None:
        raise Refused(f"the model card has no {what}")
    return [dict(zip(block["columns"], row, strict=True)) for row in block["data"]]


def _results(card: dict, question: str) -> tuple[dict, list[str]]:
    """The one-time test's rows by (level, year), every quoted level and year checked present."""
    test = (card.get(question) or {}).get("holdout")
    if not test:
        raise Refused(f"the model card has no one-time test for {question}")
    rows = _rows(test.get("results"), f"one-time test results for {question}")
    out = {(str(r["level"]).removesuffix(" (chosen)"), str(r["year"])): r for r in rows}
    years = sorted({year for _, year in out if year != "all"})
    if not years:
        raise Refused(f"the one-time test for {question} has no years")
    for level in LEVELS[question]:
        for year in [*years, "all"]:
            if (level, year) not in out:
                raise Refused(f"the one-time test for {question} has no row for {level}, {year}")
    return out, years


def _dilution(card: dict) -> list[Number]:
    res, years = _results(card, "dilution")
    test = card["dilution"]["holdout"]
    src = "model_card.json → dilution.holdout"
    span = f"{years[0]}-{years[-1]}"
    out = [
        Number(
            "dil.rows",
            test["rows"],
            count(test["rows"]),
            f"{src}.rows",
            "company-months scored: a forecast at a month-end, answered six months later",
        ),
        Number(
            "dil.first",
            test["first_row"],
            day(test["first_row"]),
            f"{src}.first_row",
            "the first month-end with a forecast in the test",
        ),
        Number(
            "dil.last",
            test["last_row"],
            day(test["last_row"]),
            f"{src}.last_row",
            "the last month-end with a forecast whose six months had passed",
        ),
    ]
    for level in LEVELS["dilution"]:
        v = res[(level, "all")]["log_loss"]
        meaning = f"log loss of {NAMES[level]}, {span} (lower is better)"
        out.append(
            Number(f"dil.ll.{level}", v, dec(v, 3), f"{src}.results ({level}, all)", meaning)
        )
    for level in LEVELS["dilution"]:
        v = res[(level, "all")]["auc"]
        meaning = f"AUC of {NAMES[level]}, {span} (0.5 a coin toss, 1 perfect)"
        out.append(
            Number(f"dil.auc.{level}", v, dec(v, 2), f"{src}.results ({level}, all)", meaning)
        )
    lift = res[(CHOSEN, "all")]["lift_top10"]
    out.append(
        Number(
            "dil.lift10.lightgbm",
            lift,
            ratio(lift),
            f"{src}.results (lightgbm, all)",
            "the tenth with the highest chances diluted this many times as often as all",
        )
    )
    best = [
        y
        for y in years
        if min(LEVELS["dilution"], key=lambda lv, y=y: res[(lv, y)]["log_loss"]) == CHOSEN
    ]
    out.append(
        Number(
            "dil.best_years",
            ", ".join(best),
            years_shown(best, years),
            f"{src}.results (per year)",
            "the years in which LightGBM had the lowest log loss of the four levels",
        )
    )
    bands = [
        r
        for r in _rows(test.get("bands"), "one-time test bands for dilution")
        if str(r["year"]) == "all"
    ]
    by_band = {int(r["band"]): r for r in bands}
    if sorted(by_band) != [1, 2, 3, 4, 5]:
        raise Refused("the one-time test for dilution lacks a band's row over all years")
    rate = sum(r["rows"] * r["real_rate"] for r in bands) / sum(r["rows"] for r in bands)
    out.append(
        Number(
            "dil.rate",
            rate,
            pct(rate),
            f"{src}.bands (all, weighted by rows)",
            "the share of the test's company-months followed by a 10%+ rise in shares within "
            "six months",
        )
    )
    for band in range(1, 6):
        r = by_band[band]
        where = f"{src}.bands ({band}, all)"
        out.append(
            Number(
                f"dil.band{band}.forecast",
                r["forecast"],
                pct(r["forecast"]),
                where,
                f"band {band}: the mean chance forecast",
            )
        )
        out.append(
            Number(
                f"dil.band{band}.real",
                r["real_rate"],
                pct(r["real_rate"]),
                where,
                f"band {band}: the share that diluted",
            )
        )
    test_years = card["dilution"].get("test_years")
    if not test_years:
        raise Refused("the model card has no test years for dilution")
    ty = sorted(test_years)
    for level in LEVELS["dilution"]:
        # the notebook named its LightGBM level "boosting"
        name = level if level in test_years[ty[0]] else card["dilution"].get("chosen")
        try:
            values = [test_years[y][name] for y in ty]
        except KeyError, TypeError:
            raise Refused(f"the dilution test years lack the level {level}") from None
        mean = sum(values) / len(values)
        out.append(
            Number(
                f"dil.test_ll.{level}",
                mean,
                dec(mean, 3),
                f"model_card.json → dilution.test_years ({name}, mean of {ty[0]}-{ty[-1]})",
                f"log loss of {NAMES[level]}, mean of the test years",
            )
        )
    return out


def _results_move(card: dict) -> list[Number]:
    res, years = _results(card, "results_move")
    test = card["results_move"]["holdout"]
    src = "model_card.json → results_move.holdout"
    out = [
        Number(
            "mov.rows",
            test["rows"],
            count(test["rows"]),
            f"{src}.rows",
            "results releases scored (each forecast made the evening before)",
        )
    ]
    for level in LEVELS["results_move"]:
        v = res[(level, "all")]["log_loss_mean"]
        meaning = (
            f"mean log loss of the three chances (a move above 5%, 10%, 20%) of "
            f"{NAMES[level]} (lower is better)"
        )
        out.append(
            Number(f"mov.ll.{level}", v, dec(v, 3), f"{src}.results ({level}, all)", meaning)
        )
    ridge = [
        y for y in years if res[("ridge", y)]["log_loss_mean"] < res[(CHOSEN, y)]["log_loss_mean"]
    ]
    out.append(
        Number(
            "mov.ridge_better_years",
            ", ".join(ridge),
            years_shown(ridge, years),
            f"{src}.results (per year)",
            "the years in which the simpler ridge beat the approved LightGBM",
        )
    )
    return out


def _volatility(card: dict) -> list[Number]:
    res, _ = _results(card, "volatility")
    test = card["volatility"]["holdout"]
    src = "model_card.json → volatility.holdout"
    out = [
        Number(
            "vol.rows",
            test["rows"],
            count(test["rows"]),
            f"{src}.rows",
            "company-months scored (volatility over the next three months)",
        )
    ]
    for level in LEVELS["volatility"]:
        v = res[(level, "all")]["mae_log"]
        meaning = f"mean absolute log error of {NAMES[level]} (lower is better)"
        out.append(
            Number(f"vol.mae.{level}", v, dec(v, 3), f"{src}.results ({level}, all)", meaning)
        )
    cover = res[(CHOSEN, "all")]["coverage_80"]
    out.append(
        Number(
            "vol.cov80.lightgbm",
            cover,
            pct(cover),
            f"{src}.results (lightgbm, all)",
            "the share of outcomes inside LightGBM's 80% range (80% is right)",
        )
    )
    return out


def from_card(card: dict) -> list[Number]:
    """The numbers of the three models' one-time test and the dilution model's test years."""
    return _dilution(card) + _results_move(card) + _volatility(card)


# ---------- the generated reports ----------


def _num(cell: str) -> float | int:
    text = cell.replace(",", "").strip()
    return float(text) if "." in text else int(text)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table(lines: list[str], what: str) -> list[dict]:
    """The first table in `lines`: its header row, then one dict per row."""
    start = next((i for i, line in enumerate(lines) if line.startswith("|")), None)
    if start is None:
        raise Refused(f"{what} has no table")
    block = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        block.append(line)
    if len(block) < 3:
        raise Refused(f"{what} has an empty table")
    head = _cells(block[0])
    return [dict(zip(head, _cells(line), strict=True)) for line in block[2:]]


def _section_table(text: str, heading: str, what: str) -> list[dict]:
    """The first table under the heading that starts with `heading`."""
    lines = text.splitlines()
    at = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    if at is None:
        raise Refused(f"{what} has no section '{heading}'")
    section = []
    for line in lines[at + 1 :]:
        if line.startswith("#"):
            break
        section.append(line)
    return _table(section, f"{what}, section '{heading}'")


def _row(table: list[dict], column: str, value: str, what: str) -> dict:
    for row in table:
        if row.get(column) == value:
            return row
    raise Refused(f"{what} has no row '{value}'")


def from_catching_up(text: str) -> list[Number]:
    what, src = "the catching-up report", "dilution_catching_up.md"
    first = _section_table(text, "## 1.", what)
    announced = _num(_row(first, "year", "all", what)["of them announced"])
    second = _section_table(text, "## 2.", what)
    every = _row(second, "test rows", "all test rows", what)
    none = _row(second, "test rows", "nothing announced", what)
    auc_all, auc_none = _num(every["AUC"]), _num(none["AUC"])
    band5_all, band5_none = _num(every["band 5 rate"]), _num(none["band 5 rate"])
    return [
        Number(
            "cu.announced",
            announced,
            pct(announced),
            f"{src}, section 1 (all)",
            "of the answers of 1 (2012 to mid-2022), the share with a share sale already "
            "announced by the forecast date",
        ),
        Number(
            "cu.auc_all",
            auc_all,
            dec(auc_all, 2),
            f"{src}, section 2 (all test rows)",
            "the approved model's AUC on the test years 2019-2022",
        ),
        Number(
            "cu.auc_none",
            auc_none,
            dec(auc_none, 2),
            f"{src}, section 2 (nothing announced)",
            "the same, on the rows with nothing announced",
        ),
        Number(
            "cu.band5_all",
            band5_all,
            pct(band5_all),
            f"{src}, section 2 (all test rows)",
            "the share of band 5 that diluted, test years 2019-2022",
        ),
        Number(
            "cu.band5_none",
            band5_none,
            pct(band5_none),
            f"{src}, section 2 (nothing announced)",
            "the same, on the rows with nothing announced",
        ),
    ]


def from_audit(text: str) -> list[Number]:
    what, src = "the data audit", "data_audit.md"
    table = _table(text.splitlines(), what)
    out = []
    for stem, measure, meaning in AUDIT_ROWS:
        row = next((r for r in table if measure in r.get("Measure", "")), None)
        if row is None:
            raise Refused(f"{what} has no row '{measure}'")
        for when, column in (("before", "Before"), ("after", "After")):
            v = _num(row[column])
            out.append(
                Number(
                    f"audit.{stem}_{when}",
                    v,
                    count(v),
                    f"{src} ({column})",
                    f"{meaning}, {when} the repair",
                )
            )
    named = re.search(r"Named cases: (\d+) of (\d+) pass", text)
    if not named:
        raise Refused(f"{what} has no named-case line")
    shown = f"{named[1]} of {named[2]}"
    out.append(
        Number(
            "audit.named",
            shown,
            shown,
            src,
            "named companies whose histories were checked against the SEC and the price files: "
            "passing",
        )
    )
    return out


# ---------- the serving copy ----------


def from_serving(con: duckdb.DuckDBPyConnection) -> list[Number]:
    newest, forecasts = con.execute(
        "select max(as_of), count(*) from app.daily_score where question = ?", [QUESTION]
    ).fetchone()
    if newest is None:
        raise Refused("the serving copy holds no dilution forecast")
    companies = con.execute(
        "select count(distinct cik) from app.company_card "
        "where as_of >= (select max(as_of) from app.company_card) - ?::integer",
        [CURRENT_DAYS],
    ).fetchone()[0]
    src = "serving.duckdb"
    return [
        Number(
            "app.date",
            newest.isoformat(),
            day(newest.isoformat()),
            f"{src} → app.daily_score",
            "the day of the newest forecasts",
        ),
        Number(
            "app.companies",
            companies,
            count(companies),
            f"{src} → app.company_card",
            f"companies still trading (data within {CURRENT_DAYS} days of the newest)",
        ),
        Number(
            "app.forecasts",
            forecasts,
            count(forecasts),
            f"{src} → app.daily_score",
            "of them, companies with a dilution forecast (each of the others is told on its "
            "page why it has none: a rule fixed before any model, or no share count, V2-74)",
        ),
    ]


# ---------- the sheet ----------


def _group(number_id: str) -> str:
    prefix = next((p for p, _ in GROUPS if number_id.startswith(p)), None)
    if prefix is None:
        raise Refused(f"the id {number_id} belongs to no group")
    return prefix


def render(numbers: list[Number]) -> str:
    ids = [n.id for n in numbers]
    if len(ids) != len(set(ids)):
        raise Refused("two numbers share an id")
    groups = {n.id: _group(n.id) for n in numbers}
    date_ = next((n.shown for n in numbers if n.id == "app.date"), "–")
    parts = [
        "# The hand-in's numbers\n",
        "*Generated by `python -m sentinel.presentation` (feature 019) from "
        "`docs/report/model_card.json` (written by `sentinel report`), "
        "`docs/report/dilution_catching_up.md`, `docs/report/data_audit.md` and the serving copy "
        f"of {date_}; never edited by hand. Every number is an aggregate over many companies. The "
        "slides, the demo path and the README take numbers from here by id.*\n",
    ]
    for prefix, title in GROUPS:
        group = [n for n in numbers if groups[n.id] == prefix]
        if not group:
            continue
        parts.append(f"## {title}\n")
        parts.append("| id | number | as shown | source | meaning |\n|---|---|---|---|---|")
        parts += [f"| `{n.id}` | {n.value} | {n.shown} | {n.source} | {n.meaning} |" for n in group]
        parts.append("")
    parts += ["## Terms\n", TERMS]
    return "\n".join(parts)


def _read(path: Path, what: str) -> str:
    if not path.exists():
        raise Refused(f"{what} is missing: {path}")
    return path.read_text(encoding="utf-8")


def main(p: config.Paths | None = None, out: Path | None = None, echo=print) -> Path:
    p = p or config.paths()
    out = Path(out) if out else p.root / OUT
    card = json.loads(_read(p.root / CARD, "the model card"))
    catching_up = _read(p.root / CATCHING_UP, "the catching-up report")
    audit = _read(p.root / AUDIT, "the data audit")
    if not p.serving_db.exists():
        raise Refused(f"the serving copy is missing: {p.serving_db}")
    with duckdb.connect(
        str(p.serving_db), read_only=True, config={"memory_limit": db.MEMORY_LIMIT}
    ) as con:
        app = from_serving(con)
    text = render(from_card(card) + from_catching_up(catching_up) + from_audit(audit) + app)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    echo(f"written: {out}")
    return out


if __name__ == "__main__":
    try:
        main()
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        sys.exit(1)
