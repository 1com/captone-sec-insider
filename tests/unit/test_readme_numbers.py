"""The README's front page quotes the one-time test as the model card gives it (019 T015, R6).

The results table and the sentences under it are compared with `docs/report/model_card.json`
(written by `sentinel report`), rounded as the number sheet rounds them
(`sentinel.presentation.from_card`), so the hand-written page cannot drift from the generated
report. The model card is in git, so this runs without the data, in CI as well. Since 17 Nov the
front page presents the dilution model only: the volatility and results-day models are the
researcher's later extensions (V2-78). Since 18 Nov it opens with the product and the data it
gathers, whose counts are the number sheet's (V2-80)."""

import json
import re
from pathlib import Path

from sentinel import presentation

ROOT = Path(__file__).resolve().parents[2]
SECTION = "## How well it forecasts"
LEVELS = {  # the table's first column starts with the level's name
    "Base rate": "base_rate",
    "Offering rule": "rule",
    "Logistic regression": "logistic",
    "LightGBM": "lightgbm",
}


def _shown() -> dict[str, str]:
    card = json.loads((ROOT / presentation.CARD).read_text(encoding="utf-8"))
    return {number.id: number.shown for number in presentation.from_card(card)}


def _section() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index(SECTION)
    return readme[start : readme.index("\n## ", start + 1)]


def _cells(line: str) -> list[str]:
    return [cell.strip().strip("*").strip() for cell in line.strip().strip("|").split("|")]


def test_the_section_is_on_the_first_screen():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first_screen = "\n".join(readme.splitlines()[:40])  # SC-005: about 40 lines
    assert SECTION in first_screen
    assert "serves the dilution forecast" in first_screen
    assert "| **LightGBM, the approved model** |" in first_screen


def test_the_results_table_equals_the_model_card():
    shown = _shown()
    rows = [line for line in _section().splitlines() if line.startswith("|")]
    assert _cells(rows[0])[1:] == [
        "Log loss, test years 2019–2022",
        "Log loss, one-time test",
        "AUC, one-time test",
    ]
    levels = []
    for line in rows[2:]:
        name, *numbers = _cells(line)
        level = next(key for start, key in LEVELS.items() if name.startswith(start))
        expected = [shown[f"dil.{kind}.{level}"] for kind in ("test_ll", "ll", "auc")]
        assert numbers == expected, level
        levels.append(level)
    assert levels == list(LEVELS.values())  # every level once, simplest first


def test_the_sentences_under_it_quote_the_model_card():
    shown = _shown()
    section = " ".join(_section().split())  # the sentences wrap across lines
    for number_id in (
        "dil.rows",
        "dil.first",
        "dil.last",
        "dil.rate",
        "dil.band5.real",
        "dil.band5.forecast",
    ):
        assert shown[number_id] in section, number_id
    assert f"{shown['dil.lift10.lightgbm'].removesuffix('×')} times as often" in section
    # "best in each of the four years" and "in every year": true only while all four years hold
    assert shown["dil.best_years"].startswith("4 of 4")
    assert "in each of the four years 2023–2026" in section


def test_the_front_page_presents_the_dilution_model_only():
    """V2-78 (the researcher, 17 Nov): the volatility and results-day models are not part of the
    course project. The front page gives none of their results and names them once, in the map
    of the repository, to say what they are."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    front = readme[: readme.index("\n## Working notes")]
    others = {
        number_id: value
        for number_id, value in _shown().items()
        if number_id.startswith(("vol.", "mov.")) and not value.startswith("4 of 4")
    }
    assert [number_id for number_id, value in others.items() if value in front] == []
    pattern = re.compile(r"volatility|results-day", re.IGNORECASE)
    named = [line for line in front.splitlines() if pattern.search(line)]
    assert len(named) == 1 and named[0].startswith("| `src/sentinel/models/` |")
    assert "not part of the course project and not served" in named[0]


def test_the_opening_and_the_app_section_quote_the_number_sheet():
    """V2-80 (the researcher, 18 Nov): the front page opens with the research app and the data it
    gathers, then the dilution forecast made from part of it. Its counts and those of "The app"
    are the generated number sheet's (`docs/presentation/numbers.md`, `sentinel.presentation`)."""
    sheet = (ROOT / presentation.OUT).read_text(encoding="utf-8")
    shown = dict(re.findall(r"^\| `([\w.]+)` \| [^|]* \| ([^|]*?) \|", sheet, re.MULTILINE))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    opening = " ".join(readme[: readme.index(SECTION)].split())
    assert opening.startswith("# EDGAR-SENTINEL **Research any US stock from public data.**")
    assert opening.index("research app") < opening.index("dilution")
    for number_id in ("app.date", "data.companies", "data.filings", "data.financials",
                      "data.insider", "data.prices"):  # fmt: skip
        assert shown[number_id] in opening, number_id
    app = " ".join(readme[readme.index("## The app") : readme.index("## How it works")].split())
    for number_id in ("app.date", "app.companies", "app.forecasts"):
        assert shown[number_id] in app, number_id
