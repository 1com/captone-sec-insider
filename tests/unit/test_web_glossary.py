"""Tests for the plain-English glossary of SEC form types and 8-K items (feature 026, FR-011)."""

import pytest

from sentinel.web.glossary import (
    KINDS,
    UNKNOWN_FORM_DESCRIPTION,
    UNKNOWN_ITEM_DESCRIPTION,
    UNKNOWN_ITEM_NAME,
    describe_form,
    describe_items,
)

# Every form type with at least 100 filings in the data (10 Nov 2026), most frequent first.
FORM_CODES = (
    "4",
    "8-K",
    "424B2",
    "10-Q",
    "6-K",
    "SC 13G/A",
    "3",
    "SC 13G",
    "FWP",
    "424B3",
    "10-K",
    "UPLOAD",
    "CORRESP",
    "DEF 14A",
    "144",
    "SC 13D/A",
    "4/A",
    "10-D",
    "425",
    "DEFA14A",
    "5",
    "S-8",
    "10QSB",
    "8-K/A",
    "EFFECT",
    "424B5",
    "NT 10-Q",
    "ABS-EE",
    "SC 13D",
    "S-1/A",
    "NPORT-P",
    "11-K",
    "ARS",
    "S-8 POS",
    "SCHEDULE 13G/A",
    "10-K/A",
    "NT 10-K",
    "10-Q/A",
    "PRE 14A",
    "S-3",
    "POS AM",
    "D",
    "N-Q",
    "10KSB",
    "497K",
    "S-3/A",
    "40-17G",
    "497",
    "SCHEDULE 13G",
    "S-1",
    "3/A",
    "N-CSR",
    "8-A12B",
    "N-CSRS",
    "N-PX",
    "20-F",
    "S-4/A",
    "SC TO-I/A",
    "DFAN14A",
    "CT ORDER",
    "NSAR-B",
    "NSAR-A",
    "SC TO-T/A",
    "SD",
    "13F-HR",
    "25-NSE",
    "S-4",
    "424B4",
    "S-3ASR",
    "REGDEX",
    "SC TO-I",
    "10QSB/A",
    "SB-2/A",
    "10-K405",
    "DEF 14C",
    "SCHEDULE 13D/A",
    "PRER14A",
    "10KSB/A",
    "PRE 14C",
    "15-12G",
    "N-30D",
    "RW",
    "CERT",
    "NO ACT",
    "8-A12G",
    "SC TO-C",
    "SC 14D9/A",
    "F-1/A",
    "ABS-15G/A",
    "6-K/A",
    "DRS/A",
    "N-2/A",
    "N-CEN",
    "DRSLTR",
    "D/A",
    "DRS",
    "485BXT",
    "DEFR14A",
    "DEFM14A",
    "424B7",
    "SC 13E3/A",
    "497AD",
    "SB-2",
    "485BPOS",
    "SUPPL",
    "POS EX",
    "40-APP/A",
    "CERTNYS",
    "10-12G/A",
    "IRANNOTICE",
    "424B1",
    "40-17G/A",
    "N-23C3A",
    "5/A",
    "15-12B",
    "PREM14A",
    "N-2",
    "8-A12B/A",
    "497J",
    "PX14A6G",
    "20-F/A",
    "ABS-15G",
    "SC TO-T",
    "13F-NT",
    "25",
    "POSASR",
    "40-F",
    "15-15D",
    "REVOKED",
    "35-CERT",
    "24F-2NT",
    "PREC14A",
    "10SB12G/A",
    "SC 14D1/A",
    "S-11/A",
    "40-17F2",
    "F-3",
    "F-1",
    "CERTNAS",
    "40-APP",
    "SC 14D9",
    "10-12G",
    "N-23C-2",
    "SCHEDULE 13D",
    "SC14D9C",
    "424B8",
    "REGDEX/A",
    "424H",
    "S-1MEF",
    "DEFC14A",
    "PRER14C",
    "POS 8C",
    "N-30B-2",
    "F-X",
    "13F-HR/A",
    "NT 20-F",
    "PRRN14A",
    "SC 14F1",
    "485APOS",
    "10-D/A",
    "305B2",
    "10SB12G",
    "F-3/A",
    "144/A",
    "F-4/A",
    "SEC STAFF LETTER",
    "AW",
    "486BPOS",
    "8-A12G/A",
    "10-12B/A",
    "10KSB40",
    "SC 13E3",
    "10-K405/A",
    "U-1/A",
    "NT 11-K",
    "U-12-IB",
    "NTN 10Q",
    "1-A/A",
    "F-6EF",
    "N-8A",
    "POS AMI",
    "CERTAMX",
    "S-3MEF",
    "F-10",
    "NPORT-EX",
    "DEFS14A",
    "F-10/A",
    "F-6 POS",
    "F-3ASR",
    "NTN 10K",
    "NSAR-B/A",
    "N-CSR/A",
    "11-K/A",
    "S-2/A",
    "S-11",
    "PRES14A",
    "N-8F",
    "S-3D",
    "F-4",
    "F-6",
    "DEL AM",
    "N-23C-1",
    "QUALIF",
    "POS AMC",
    "N-8F ORDR",
    "U-6B-2",
    "253G2",
    "N-8F NTC",
    "1-U",
    "S-3DPOS",
    "1-A",
    "SEC STAFF ACTION",
    "SC 13E4/A",
    "S-2",
    "SC 14D1",
    "U-1",
    "NPORT-P/A",
    "10-C",
    "U-3A-2",
    "APP NTC",
    "424A",
    "10-12B",
    "1-A POS",
    "APP ORDR",
    "NT 10-Q/A",
    "NSAR-A/A",
    "10-KT",
    "NT 10-K/A",
    "40-F/A",
    "CB/A",
    "PREM14C",
    "SE",
    "N-CEN/A",
    "N-14 8C/A",
    "U-9C-3",
    "NT-NSAR",
    "N-MFP2",
    "8-K12G3",
    "F-N",
    "CB",
    "ABS-EE/A",
    "N-14 8C",
    "497K3B",
    "8-K12B",
    "40-6C",
    "SC 13E4",
    "DEFA14C",
    "N-PX/A",
    "DEFM14C",
    "N-54A",
    "486APOS",
    "DFRN14A",
    "T-3",
    "N-CSRS/A",
    "DEFR14C",
    "PREN14A",
    "CERTPAC",
    "20FR12G/A",
    "N-MFP",
    "T-3/A",
    "424I",
    "40-6C/A",
    "F-X/A",
    "U-57",
    "N-8F/A",
    "APP WD",
    "40-33",
    "F-1MEF",
    "DEFN14A",
    "10KSB40/A",
    "N-2MEF",
    "RW WD",
    "25-NSE/A",
    "1-SA",
    "1-K",
    "15-12G/A",
    "N-23C3B",
    "SF-3/A",
    "NT-NCSR",
    "497VPU",
    "S-4 POS",
    "10-QT",
    "C/A",
    "SC 14F1/A",
    "CERTARCA",
    "N-8A/A",
    "20FR12G",
    "U5S",
    "20FR12B/A",
    "N-Q/A",
    "40FR12B",
    "SF-3",
    "15F-12B",
    "N-MFP3",
    "SB-1/A",
    "20FR12B",
    "N-54C",
    "486BXT",
    "S-4MEF",
    "13F-E",
    "SF-1/A",
    "C-AR",
    "N-14",
    "1-A-W",
    "N-2ASR",
    "253G1",
    "F-6/A",
    "POS462B",
    "10-KT/A",
    "N-14/A",
    "C",
    "N-6F",
    "15F-12G",
    "SC14D1F/A",
    "U-3A-2/A",
    "F-10POS",
    "NSAR-BT",
    "1-E",
    "40FR12B/A",
    "13FCONP",
    "13F-NT/A",
    "1-Z",
    "SBSE-A/A",
    "424H/A",
)

# Every 8-K item number in the data, modern ("2.02") and before August 2004 ("7").
ITEM_NUMBERS = (
    "9.01",
    "2.02",
    "8.01",
    "7.01",
    "5.02",
    "1.01",
    "7",
    "2.03",
    "5",
    "5.07",
    "3.02",
    "5.03",
    "2.01",
    "9",
    "4.01",
    "1.02",
    "3.01",
    "3.03",
    "12",
    "2",
    "5.01",
    "4",
    "4.02",
    "2.05",
    "1",
    "2.04",
    "2.06",
    "5.06",
    "5.05",
    "1.03",
    "6.02",
    "5.08",
    "5.04",
    "6",
    "8",
    "3",
    "1.04",
    "6.05",
    "6.04",
    "11",
    "1.05",
    "10",
    "6.01",
    "6.03",
    "13",
    "6.06",
)


def test_embedded_lists_are_complete():
    assert len(FORM_CODES) == len(set(FORM_CODES)) == 324
    assert len(ITEM_NUMBERS) == len(set(ITEM_NUMBERS)) == 46


def test_every_common_form_has_its_own_description():
    unknown = [
        code
        for code in FORM_CODES
        if describe_form(code)["description"] == UNKNOWN_FORM_DESCRIPTION
        or "SEC form" in describe_form(code)["name"]
    ]
    assert unknown == []


def test_every_item_has_its_own_description():
    unknown = [
        item
        for item in ITEM_NUMBERS
        if describe_items(item)[0]["description"] == UNKNOWN_ITEM_DESCRIPTION
        or describe_items(item)[0]["name"] == UNKNOWN_ITEM_NAME
    ]
    assert unknown == []


def test_amendment_reads_as_amendment_of_its_base_form():
    base, amended = describe_form("10-K"), describe_form("10-K/A")
    assert amended["amendment"] is True and base["amendment"] is False
    assert amended["code"] == "10-K/A"
    assert amended["name"] == f"Amendment: {base['name']}" == "Amendment: Annual report"
    assert amended["description"] == base["description"]
    assert amended["kind"] == base["kind"] == "reports"
    assert describe_form("SC 13G/A")["kind"] == "insiders"
    assert describe_form("S-1/A")["dilution_signal"] is True
    assert describe_form("4/A")["name"] == "Amendment: Insider trade"
    assert all(describe_form(c)["amendment"] == c.endswith("/A") for c in FORM_CODES)


def test_other_spellings_and_family_members():
    assert describe_form("SCHEDULE 13G")["name"] == describe_form("SC 13G")["name"]
    assert describe_form("SCHEDULE 13D/A")["kind"] == "insiders"
    for code, kind in [
        ("424B6", "offerings"),
        ("DEFC14C", "proxy"),
        ("NT 10-D", "reports"),
        ("N-1A", "other"),
        ("13F-CTR", "insiders"),
        ("CERTBATS", "other"),
        ("U-13-60", "other"),
        ("F-3MEF", "offerings"),
    ]:
        described = describe_form(code)
        assert described["description"] != UNKNOWN_FORM_DESCRIPTION, code
        assert described["kind"] == kind, code
    assert describe_form("F-3MEF")["dilution_signal"] is True


def test_unknown_codes_never_raise():
    unknown = describe_form("XYZ-99")
    assert unknown == {
        "code": "XYZ-99",
        "name": "SEC form XYZ-99",
        "description": UNKNOWN_FORM_DESCRIPTION,
        "kind": "other",
        "amendment": False,
        "dilution_signal": False,
    }
    assert describe_form("XYZ-99/A")["name"] == "Amendment: SEC form XYZ-99"
    assert describe_form("UNKNOWNFORM")["kind"] == "other"
    for empty in ("", "   ", None):
        described = describe_form(empty)
        assert described["kind"] == "other"
        assert described["description"] == UNKNOWN_FORM_DESCRIPTION


def test_form_codes_are_cleaned():
    assert describe_form("  10-q ")["code"] == "10-Q"
    assert describe_form("  10-q ")["name"] == "Quarterly report"
    assert describe_form("SC  13G")["code"] == "SC 13G"
    assert describe_form("sc 13d/a")["name"] == describe_form("SC 13D/A")["name"]


def test_items_are_parsed_in_order():
    assert describe_items(None) == []
    assert describe_items("") == []
    assert describe_items(" , ,") == []
    assert [i["item"] for i in describe_items(" 2.02, 9.01 ,,")] == ["2.02", "9.01"]
    assert [i["item"] for i in describe_items("9.01,2.02")] == ["9.01", "2.02"]
    assert [i["item"] for i in describe_items("Item 2.02, ITEM 9.01")] == ["2.02", "9.01"]
    assert [i["item"] for i in describe_items("5.02,5.02")] == ["5.02"]
    assert [i["item"] for i in describe_items(["7.01", "9.01"])] == ["7.01", "9.01"]
    first = describe_items("2.02")[0]
    assert set(first) == {"item", "name", "description", "dilution_signal"}
    assert first["name"] == "Results announced"


def test_unknown_items_never_raise():
    assert describe_items("99.99") == [
        {
            "item": "99.99",
            "name": UNKNOWN_ITEM_NAME,
            "description": UNKNOWN_ITEM_DESCRIPTION,
            "dilution_signal": False,
        }
    ]


@pytest.mark.parametrize(
    ("code", "signal"),
    [
        ("S-1", True),
        ("S-3", True),
        ("S-3ASR", True),
        ("S-8", True),
        ("F-1", True),
        ("424B4", True),
        ("424B5", True),
        ("D", True),
        ("424B2", False),
        ("424B3", False),
        ("424B7", False),
        ("FWP", False),
        ("POS AM", False),
        ("S-8 POS", False),
        ("10-Q", False),
        ("4", False),
        ("8-K", False),
    ],
)
def test_form_dilution_signal(code, signal):
    assert describe_form(code)["dilution_signal"] is signal


@pytest.mark.parametrize(
    ("item", "signal"),
    [("3.02", True), ("2.02", False), ("1.01", False), ("3.03", False), ("9.01", False)],
)
def test_item_dilution_signal(item, signal):
    assert describe_items(item)[0]["dilution_signal"] is signal


def test_names_and_descriptions_are_short_sentences():
    described = [describe_form(code) for code in FORM_CODES]
    described += [entry for item in ITEM_NUMBERS for entry in describe_items(item)]
    for entry in described:
        assert 0 < len(entry["name"]) <= 45, entry["name"]
        assert len(entry["description"]) <= 240, entry["description"]
        assert entry["description"][0].isupper(), entry["description"]
        assert entry["description"].endswith("."), entry["description"]
        assert not entry["name"].endswith("."), entry["name"]


def test_every_kind_is_a_filter_kind():
    assert list(KINDS) == ["reports", "current", "offerings", "insiders", "proxy", "other"]
    codes = (*FORM_CODES, "XYZ-99", "", "424B6", "N-1A", "DEFC14C")
    assert {describe_form(code)["kind"] for code in codes} <= set(KINDS)
    assert {describe_form(code)["kind"] for code in FORM_CODES} == set(KINDS)
