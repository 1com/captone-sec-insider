"""Plain-English labels (feature 005, research R6; rule P7)."""

import pytest

from sentinel.api import glossary

FORM4_CODES = list("PSVADFIMCEHOXGLWZJKU")  # SEC Form 4 General Instructions, item 8


@pytest.mark.parametrize("code", FORM4_CODES)
def test_every_form4_code_has_a_plain_label_and_an_explanation(code):
    short, long = glossary.CODES[code]
    assert short and long and short != code
    assert glossary.describe_code(code) == short


def test_the_table_holds_exactly_the_form4_codes():
    assert sorted(glossary.CODES) == sorted(FORM4_CODES)


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_a_blank_code_is_described(blank):
    assert glossary.describe_code(blank) == "No code reported"


def test_an_unknown_code_is_never_shown_bare():
    assert glossary.describe_code("Q") != "Q" and "Q" in glossary.describe_code("Q")


def test_forms_roles_holdings_and_event_kinds_are_covered():
    assert set(glossary.FORMS) == {"3", "4", "5", "3/A", "4/A", "5/A"}
    assert set(glossary.ROLES) == {"ceo_cfo", "officer", "director", "ten_pct", "other"}
    assert set(glossary.HOLDINGS) == {"D", "I"} and set(glossary.ACQ_DISP) == {"A", "D"}
    assert set(glossary.EVENT_KINDS) == {"A", "B1", "B2"}
    assert glossary.label(glossary.ROLES, "director") == "Director"
    assert glossary.label(glossary.FORMS, None) == "Not reported"
