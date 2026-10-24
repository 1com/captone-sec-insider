"""`sentinel lookup`: the lookup file built from SEC tables (feature 005, data-model.md)."""

from datetime import date, datetime

import pytest

from sentinel.api import lookup, queries


def rows(paths, sql: str, args=None) -> list[tuple]:
    con = queries.open_lookup(paths)
    try:
        return con.execute(sql, args or []).fetchall()
    finally:
        con.close()


def test_meta_states_the_data_as_of_date(lookup_paths):
    [(as_of, dataset, built, warehouse_built)] = rows(lookup_paths, "select * from lookup.meta")
    assert (as_of, dataset) == (date(2019, 3, 25), "2019q1")
    assert warehouse_built == datetime(2026, 10, 24, 10, 1) and built is not None


def test_a_failed_build_keeps_the_previous_file(lookup_paths, params, monkeypatch):
    before = lookup_paths.lookup.read_bytes()

    def broken(con):
        raise RuntimeError("disk full")

    monkeypatch.setattr(lookup, "TABLES", [*lookup.TABLES, broken])
    with pytest.raises(RuntimeError):
        lookup.build(lookup_paths, params)
    assert lookup_paths.lookup.read_bytes() == before
    assert not lookup_paths.lookup.with_name("lookup.duckdb.part").exists()


def test_two_builds_give_identical_tables(lookup_paths, params):
    def snapshot():
        tables = [
            t
            for (t,) in rows(
                lookup_paths,
                "select table_name from information_schema."
                "tables where table_schema = 'lookup' order by 1",
            )
        ]
        return {t: rows(lookup_paths, f"select * exclude (built_at) from lookup.{t} order by all")
                if t == "meta" else rows(lookup_paths, f"select * from lookup.{t} order by all")
                for t in tables}  # fmt: skip

    first = snapshot()
    lookup.build(lookup_paths, params)
    assert snapshot() == first


def test_missing_inputs_name_the_step_to_run(tmp_data, params, pipeline, archives):
    from sentinel.warehouse import MissingInput

    archives({"2019q1": {"SUBMISSION": []}})
    pipeline(until="entities").close()
    with pytest.raises(MissingInput, match="sentinel gates"):
        lookup.build(tmp_data, params)


# --- User story 1: companies, owners, transactions, footnotes ---------------------------------


def test_issuer_search_lists_every_company_with_names_and_tickers(lookup_paths):
    found = {r[0]: r[1:] for r in rows(
        lookup_paths, "select issuer_cik, name, names, tickers, n_transactions, first_filing, "
                      "last_filing from lookup.issuer_search")}  # fmt: skip
    assert set(found) == {"100", "200", "300"}
    name, names, tickers, n, first, last = found["100"]
    assert (name, names, n) == ("Abc Corp", ["Abc Corp"], 12)
    assert [(t["ticker"], t["first_year"], t["last_year"]) for t in tickers] == [
        ("ABC", 2019, 2019), ("ABCD", 2018, 2018)]  # fmt: skip
    assert (first, last) == (date(2018, 12, 10), date(2019, 3, 25))
    assert found["200"][3] == 0  # a Form 3 and no transactions


def test_every_transaction_is_copied_once_and_shown_with_its_owners(lookup_paths):
    [(n, distinct)] = rows(lookup_paths, "select count(*), count(distinct (accession, line_sk)) "
                                         "from lookup.transaction")  # fmt: skip
    assert n == distinct == 13
    con = queries.open_lookup(lookup_paths)
    try:
        page, _ = queries.transactions_page(queries.cursor(con), "100")
    finally:
        con.close()
    owners = {r["accession"]: r["owners"] for r in page if r["line_sk"] in ("71", "11")}
    assert [o["name"] for o in owners["f7"]] == ["FUND LP", "FUND GP LLC"]
    assert {o["role"] for o in owners["f7"]} == {"ten_pct"}
    assert owners["f1"] == [{"cik": "9001", "name": "SMITH JOHN", "role": "director",
                             "title": None}]  # fmt: skip


def test_roles_are_those_at_each_filing_date(lookup_paths):
    roles = dict(rows(lookup_paths, "select accession, role from lookup.filing_owner "
                                    "where owner_cik = '9003'"))  # fmt: skip
    assert roles == {"f8": "officer", "f3": "officer", "f9": "ceo_cfo"}


def test_only_cited_footnotes_are_kept(lookup_paths):
    assert rows(lookup_paths, "select accession, footnote_id, text from lookup.footnote") == [
        ("f1", "F1", "Weighted average price; bought at $49.80 to $50.20.")]  # fmt: skip


# --- User story 2: holdings -------------------------------------------------------------------


def test_holdings_are_the_last_line_per_holding_plus_untraded_rows(lookup_paths):
    found = rows(
        lookup_paths,
        "select direct_indirect, nature_of_ownership, shares_after, source "
        "from lookup.holding where accession = 'f2' order by all",
    )
    trusts = enumerate([495.0, 605.0, 150.0, 72.0, 225.0], start=1)
    assert found == [
        ("D", "", 44890.0, "holding"),
        *[("I", f"Trust {i}", n, "trade") for i, n in trusts],
    ]
    [(n,)] = rows(lookup_paths, "select count(*) from lookup.holding where issuer_cik = '100'")
    assert n == 13  # six on f2, one on each of the other seven filings


def test_a_trade_line_wins_over_a_holding_row_and_the_last_line_counts(
    tmp_data, params, pipeline, archives
):
    from conftest import holding, line, lookup_filings

    filings = lookup_filings()
    q1 = filings["2019q1"]
    q1["NONDERIV_TRANS"].append(line("f3", "32", code="S", ad="D", tdate="18-MAR-2019",
                                     shares="100", price="55", after="8400"))  # fmt: skip
    q1["NONDERIV_HOLDING"] += [holding("f3", "h31", shares="1", di="D", nature=""),
                               holding("f3", "h32", shares="7", di="I", nature="")]  # fmt: skip
    archives(filings)
    pipeline(until="prelim").close()
    lookup.build(tmp_data, params)
    found = rows(tmp_data, "select direct_indirect, nature_of_ownership, shares_after, source "
                           "from lookup.holding where accession = 'f3' order by all")  # fmt: skip
    assert found == [("D", "", 8400.0, "trade"), ("I", "", 7.0, "holding")]


# --- User story 3: events ---------------------------------------------------------------------


def test_events_are_copied_from_the_preliminary_tables(lookup_paths):
    assert rows(lookup_paths, 'select event_id, issuer_cik, "group", signal_date, '
                              "signal_accession, n_entities, total_value_usd, max_seniority "
                              "from lookup.event order by all") == [
        ("100:A:2019-03-15", "100", "A", date(2019, 3, 15), "f2", 2, 130940.0, 2),
        ("100:B2:2019-03-11", "100", "B2", date(2019, 3, 11), "f1", 1, 100000.0, 2),
    ]  # fmt: skip
    assert rows(lookup_paths, "select event_id, accession, filing_date, value_usd, "
                              "entity_role_at_t, owner_names from lookup.event_member "
                              "order by all") == [
        ("100:A:2019-03-15", "f1", date(2019, 3, 11), 100000.0, "director", ["SMITH JOHN"]),
        ("100:A:2019-03-15", "f2", date(2019, 3, 15), 30940.0, "director", ["JONES MARY"]),
        ("100:B2:2019-03-11", "f1", date(2019, 3, 11), 100000.0, "director", ["SMITH JOHN"]),
    ]  # fmt: skip


def test_events_carry_only_the_data_model_fields(lookup_paths):
    columns = rows(lookup_paths, "select table_name, list(column_name order by column_name) "
                                 "from information_schema.columns where table_schema = 'lookup' "
                                 "and table_name like 'event%' group by 1 order by 1")  # fmt: skip
    assert columns == [
        ("event", sorted(["event_id", "issuer_cik", "group", "signal_date", "signal_accession",
                          "n_entities", "total_value_usd", "max_seniority"])),
        ("event_member", sorted(["event_id", "accession", "filing_date", "value_usd",
                                 "entity_role_at_t", "owner_names"])),
    ]  # fmt: skip
