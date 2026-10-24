"""The stock lookup app (feature 005, contracts/http.md; rules P6 and P7)."""

import re

import pytest

from sentinel.api import glossary

HX = {"HX-Request": "true"}
AS_OF = {"date": "2019-03-25", "dataset": "2019q1"}


def ciks(response) -> list[str]:
    return re.findall(r'href="/company/(\d+)"', response.text)


# --- User story 1: search ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "first"), [("ABC", "100"), ("abcd", "100"), ("corp hold", "300"), ("100", "100"),
                     ("0000000100", "100"), ("Empty", "200")],
)  # fmt: skip
def test_search_by_ticker_old_ticker_name_and_cik(lookup_client, q, first):
    response = lookup_client.get("/search", params={"q": q})
    assert response.status_code == 200
    assert ciks(response)[0] == first


def test_an_exact_ticker_comes_before_name_matches(lookup_client):
    assert ciks(lookup_client.get("/search", params={"q": "ABC"})) == ["100", "300"]


def test_a_short_query_gives_a_hint_not_a_search(lookup_client):
    response = lookup_client.get("/search", params={"q": "a"})
    assert response.status_code == 200 and "at least 2 characters" in response.text
    assert ciks(response) == []
    api = lookup_client.get("/api/issuers/search", params={"q": "a"})
    assert api.status_code == 400 and api.json() == {"detail": "query too short"}


def test_no_match_is_said_in_plain_words(lookup_client):
    assert "No company matches" in lookup_client.get("/search", params={"q": "zzzz"}).text


def test_htmx_gets_a_fragment_and_a_plain_request_a_page(lookup_client):
    fragment = lookup_client.get("/search", params={"q": "ABC"}, headers=HX).text
    page = lookup_client.get("/search", params={"q": "ABC"}).text
    assert "<html" not in fragment and "<html" in page


# --- User story 1: the company page and its transactions ---------------------------------------


def test_the_company_page_lists_transactions_newest_filing_first(lookup_client):
    text = lookup_client.get("/company/100").text
    assert "Abc Corp" in text and "CIK 100" in text and "ABCD (2018)" in text
    order = re.findall(r'data-accession="(\w+)"', text)
    assert order[0] == "f9" and order[-1] == "f8"
    assert order.index("f7") < order.index("f6") < order.index("f4") < order.index("f2")


def test_a_trust_line_shows_every_field(lookup_client):
    row = re.search(r'<tr data-accession="f2" data-line="21">(.*?)</tr>',
                    lookup_client.get("/company/100").text, re.S).group(1)  # fmt: skip
    for expected in (
        "15 Mar 2019",
        "JONES MARY",
        "Director",
        "495",
        "$20.00",
        "$9,900.00",
        "Held indirectly",
        "Trust 1",
        glossary.CODES["P"][0],
        "https://www.sec.gov/Archives/edgar/data/100/f2/",
    ):
        assert expected in row, expected


def test_prices_are_labelled_as_reported(lookup_client):
    assert "as reported by the filer" in lookup_client.get("/company/100").text


def test_paging_past_the_end_says_so(lookup_client):
    response = lookup_client.get("/company/100/transactions", params={"page": 2})
    assert response.status_code == 200 and "No more transactions" in response.text


def test_an_unknown_company_is_a_plain_404(lookup_client):
    page = lookup_client.get("/company/999")
    assert page.status_code == 404 and "No company with CIK 999" in page.text
    api = lookup_client.get("/api/issuers/999/transactions")
    assert api.status_code == 404 and "999" in api.json()["detail"]


def test_a_company_without_transactions_says_so(lookup_client):
    assert "No insider transactions" in lookup_client.get("/company/200").text


def test_footnotes_open_from_their_row(lookup_client):
    text = lookup_client.get("/company/100").text
    assert "/filing/f1/footnotes?ids=F1" in text
    note = lookup_client.get("/filing/f1/footnotes", params={"ids": "F1,F9"}, headers=HX).text
    assert "Weighted average price" in note and "F9" not in note


# --- User story 1: JSON ------------------------------------------------------------------------


def test_search_json(lookup_client):
    body = lookup_client.get("/api/issuers/search", params={"q": "abc"}).json()
    assert body["query"] == "abc" and body["data_as_of"] == AS_OF
    first = body["results"][0]
    assert first["cik"] == "100" and first["name"] == "Abc Corp"
    assert first["tickers"][0] == {"ticker": "ABC", "first_year": 2019, "last_year": 2019}
    assert set(first) == {"cik", "name", "tickers", "n_transactions", "first_filing",
                          "last_filing"}  # fmt: skip


def test_transactions_json_follows_the_contract(lookup_client):
    body = lookup_client.get("/api/issuers/100/transactions",
                             params={"page": 3, "page_size": 5}).json()  # fmt: skip
    assert body["data_as_of"] == AS_OF and body["issuer"] == {"cik": "100", "name": "Abc Corp"}
    assert (body["page"], body["page_size"], body["total"]) == (3, 5, 12)
    assert [t["accession"] for t in body["transactions"]] == ["f1", "f8"]
    row = body["transactions"][0]
    assert set(row) == {"accession", "line_sk", "filing_date", "trade_date", "form",
                        "form_description", "code", "code_description", "acquired_disposed",
                        "security_title", "shares", "price", "value_usd", "shares_after",
                        "holding", "holder", "owners", "footnote_ids", "edgar_url"}  # fmt: skip
    assert (row["code"], row["code_description"]) == ("P", glossary.CODES["P"][0])
    assert row["footnote_ids"] == ["F1"] and row["holding"] == "direct"


@pytest.mark.parametrize("size", [0, 501])
def test_a_bad_page_size_is_a_400(lookup_client, size):
    response = lookup_client.get("/api/issuers/100/transactions", params={"page_size": size})
    assert response.status_code == 400


# --- Presentation rules ------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["/", "/search?q=ABC", "/company/100",
                                 "/company/100/transactions?page=1"])  # fmt: skip
def test_p6_every_page_states_the_data_as_of_date(lookup_client, url):
    text = lookup_client.get(url).text
    assert "Data as of 25 Mar 2019" in text and "SEC data set 2019 Q1" in text


@pytest.mark.parametrize("url", ["/api/issuers/search?q=abc", "/api/issuers/100/transactions"])
def test_p6_every_json_body_states_the_data_as_of_date(lookup_client, url):
    assert lookup_client.get(url).json()["data_as_of"] == AS_OF


def test_p7_no_code_is_shown_without_its_description(lookup_client):
    text = lookup_client.get("/company/100").text
    cells = re.findall(r'<td class="code">(.*?)</td>', text, re.S)
    assert len(cells) == 12
    for cell in cells:
        code = re.search(r"<b>(\w*)</b>", cell).group(1)
        assert glossary.describe_code(code) in cell
    for row in lookup_client.get("/api/issuers/100/transactions").json()["transactions"]:
        assert row["code_description"]


# --- User story 2: insiders and their holdings ---------------------------------------------------


def holding_rows(text: str) -> dict[str, str]:
    return dict(
        re.findall(r'<tr data-date="([\d-]+)" data-security="[^"]*">(.*?)</tr>', text, re.S)
    )


def test_the_company_page_lists_its_insiders_with_their_latest_role(lookup_client):
    text = lookup_client.get("/company/100").text
    section = text[text.index('id="insiders"') : text.index('id="transactions-heading"')]
    for owner in ("9001", "9002", "9003", "9004", "9005", "9006"):
        assert f'href="/company/100/insider/{owner}"' in section
    lee = re.search(r'href="/company/100/insider/9003"(.*?)</tr>', section, re.S).group(1)
    assert "LEE ANN" in lee and "CEO or CFO" in lee and "Chief Executive Officer" in lee


def test_holdings_sum_direct_and_indirect_per_filing_date(lookup_client):
    text = lookup_client.get("/company/100/insider/9002").text
    assert "JONES MARY" in text and "Data as of 25 Mar 2019" in text
    row = holding_rows(text)["2019-03-15"]
    for expected in ("15 Mar 2019", "Common Stock", "44,890", "1,547", "46,437", "Trust 5"):
        assert expected in row, expected


def test_holdings_are_newest_first_with_one_row_per_date(lookup_client):
    text = lookup_client.get("/company/100/insider/9003").text
    assert list(holding_rows(text)) == ["2019-03-25", "2019-03-20", "2018-12-10"]
    assert "10,500" in holding_rows(text)["2019-03-25"]


def test_joint_filers_see_the_same_holdings_and_each_other(lookup_client):
    lp = lookup_client.get("/company/100/insider/9005", headers=HX).text
    gp = lookup_client.get("/company/100/insider/9006", headers=HX).text
    assert "<html" not in lp
    assert holding_rows(lp)["2019-03-22"] == holding_rows(gp)["2019-03-22"]
    assert "50,000" in holding_rows(lp)["2019-03-22"]
    assert "filed jointly with FUND GP LLC" in lp and "filed jointly with FUND LP" in gp


@pytest.mark.parametrize("url", ["/company/100/insider/9999", "/company/300/insider/9002"])
def test_an_unknown_insider_is_a_plain_404(lookup_client, url):
    response = lookup_client.get(url)
    assert response.status_code == 404 and "No insider with CIK" in response.text


# --- User story 3: insider-buying events ---------------------------------------------------------


def events_section(text: str) -> str:
    return text[text.index('id="events"') : text.index('id="insiders"')]


def test_the_company_page_lists_its_events_newest_first(lookup_client):
    section = events_section(lookup_client.get("/company/100").text)
    cards = re.findall(r'<article class="card event" data-event="([^"]+)">(.*?)</article>',
                       section, re.S)  # fmt: skip
    assert [c[0] for c in cards] == ["100:A:2019-03-15", "100:B2:2019-03-11"]
    cluster = cards[0][1]
    for expected in (glossary.EVENT_KINDS["A"][0], "15 Mar 2019", "2 buyers", "$130,940.00",
                     "SMITH JOHN", "JONES MARY", "Director",
                     "https://www.sec.gov/Archives/edgar/data/100/f1/",
                     "https://www.sec.gov/Archives/edgar/data/100/f2/"):  # fmt: skip
        assert expected in cluster, expected
    assert glossary.EVENT_KINDS["B2"][0] in cards[1][1]
    assert "further checks (prices, company type)" in section


def test_events_show_no_outcome(lookup_client):
    section = events_section(lookup_client.get("/company/100").text).lower()
    for word in ("return", "outcome", "score", "profit", "gain", "alpha"):
        assert word not in section, word


def test_a_company_without_events_says_so(lookup_client):
    assert "No insider-buying events in the filings" in lookup_client.get("/company/200").text


# --- User story 4: the glossary ----------------------------------------------------------------


def test_the_glossary_lists_every_term_and_the_data_as_of_date(lookup_client):
    from markupsafe import escape

    text = lookup_client.get("/glossary").text
    assert "Data as of 25 Mar 2019" in text and "SEC data set 2019 Q1" in text
    tables = {"code": glossary.CODES, "form": glossary.FORMS, "role": glossary.ROLES,
              "holding": glossary.HOLDINGS, "event": glossary.EVENT_KINDS}  # fmt: skip
    for prefix, table in tables.items():
        for key, (short, long) in table.items():
            assert f'id="{prefix}-{key}"' in text, (prefix, key)
            assert escape(short) in text and escape(long) in text, (prefix, key)
    for term, meaning in glossary.TERMS.items():
        assert escape(term) in text and escape(meaning) in text, term
    assert escape(glossary.BLANK_CODE) in text and escape(glossary.EVENT_RULES) in text


def test_every_code_and_form_on_a_company_page_links_to_its_entry(lookup_client):
    page = lookup_client.get("/company/100").text
    glossary_page = lookup_client.get("/glossary").text
    links = re.findall(r'href="/glossary#((?:code|form)-[^"]+)"', page)
    assert {"code-P", "code-S", "code-A", "code-M", "form-4", "form-4/A"} <= set(links)
    for anchor in set(links):
        assert f'id="{anchor}"' in glossary_page, anchor


# --- User story 5: the same data as JSON -------------------------------------------------------


def test_the_json_rows_are_the_page_rows(lookup_client):
    from sentinel.api.app import _fmt_money, _fmt_number

    page = lookup_client.get("/company/100/transactions", params={"page": 1}).text
    found = re.findall(r'<tr data-accession="(\w+)" data-line="(\w+)">(.*?)</tr>', page, re.S)
    body = lookup_client.get("/api/issuers/100/transactions", params={"page": 1}).json()
    assert [(a, line) for a, line, _ in found] == [
        (t["accession"], t["line_sk"]) for t in body["transactions"]]  # fmt: skip
    for (_, _, cell), t in zip(found, body["transactions"], strict=True):
        assert f"<b>{t['code']}</b>" in cell and t["code_description"] in cell
        assert t["form_description"] in cell and t["edgar_url"] in cell
        assert all(o["name"] in cell for o in t["owners"])
        assert _fmt_number(t["shares"]) in cell and _fmt_money(t["value_usd"]) in cell
        assert (t["holder"] or "") in cell


def test_the_search_json_finds_what_the_page_finds(lookup_client):
    for q in ("abc", "corp", "200"):
        page = ciks(lookup_client.get("/search", params={"q": q}))
        body = lookup_client.get("/api/issuers/search", params={"q": q}).json()
        assert page == [r["cik"] for r in body["results"]], q


def test_openapi_lists_the_two_endpoints_and_docs_are_not_served(lookup_client):
    paths = lookup_client.get("/openapi.json").json()["paths"]
    assert set(paths) == {"/api/issuers/search", "/api/issuers/{cik}/transactions"}
    assert "transactions" in paths["/api/issuers/{cik}/transactions"]["get"]["description"]
    assert lookup_client.get("/docs").status_code == 404
    assert lookup_client.get("/redoc").status_code == 404
