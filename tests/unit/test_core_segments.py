"""Price histories as chains of segments (027): joins across ticker changes, cuts only where
another company held the ticker, one ticker-day one company, holes, blank-check days, the common
stock first, adjusted prices continuous at a switch, and no drift when a ticker changes later."""

from datetime import date

import pandas as pd
import pytest

from sentinel import db
from sentinel.core import prices

QUIET = {"echo": lambda s: None}
SESSIONS = [d.date() for d in pd.bdate_range("2014-01-02", "2016-12-30")]
LIST_DAY = date(2016, 12, 30)
SWITCH = date(2016, 1, 4)  # the first session of 2016
END = SESSIONS[-1]


def _frame(con, table: str, rows: list[dict]) -> None:
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


def _series(ticker, start, end, close=10.0, adj=None, src="yahoo", gap=None):
    out = []
    for d in SESSIONS:
        if not start <= d <= end or (gap and gap[0] <= d <= gap[1]):
            continue
        row = {"ticker": ticker, "session": d, "open": close, "high": close, "low": close,
               "close": close, "volume": 100.0, "adj_close": close * (adj or 1.0),
               "dividend": 0.0, "raw_file": f"{src}/{ticker}"}  # fmt: skip
        row["split_ratio" if src == "yahoo" else "split_factor"] = 0.0 if src == "yahoo" else 1.0
        out.append(row)
    return out


# cik: name, filer_type, SEC-list tickers, first and last Form 4 (None: none)
COMPANIES = {
    "20": ("Renamed Corp", "us", ["NEWR"], date(2014, 1, 6), date(2016, 10, 3)),
    "21": ("Gapped Corp", "us", ["NEWG"], date(2014, 1, 6), date(2016, 10, 3)),
    "22": ("Jumpy Corp", "us", ["NEWJ"], date(2014, 1, 6), date(2016, 10, 3)),
    "23": ("Typo Corp", "us", ["NEWT"], date(2014, 1, 6), date(2016, 10, 3)),
    "24": ("Forward Inc", "us", None, date(2014, 1, 6), date(2016, 10, 3)),
    "25": ("Merged Co", "us", ["MRGD"], None, None),
    "26": ("Oyo Geospace Corp", "us", ["GEOS"], None, None),
    "27": ("Parkway Bankshares", "us", ["PKWY"], None, None),
    "28": ("Parent Realty Inc", "us", ["SIS"], date(2014, 1, 6), date(2016, 6, 1)),
    "29": ("Parent Realty LP", "us", None, date(2015, 1, 5), date(2016, 6, 1)),
    "30": ("Glued Corp", "us", ["HOLY"], date(2016, 3, 1), date(2016, 10, 3)),
    "31": ("Halted Corp", "us", ["HALT"], date(2014, 2, 3), date(2016, 10, 3)),
    "32": ("Telco Systems", "us", ["TDZPRV", "TDZ", "TDZ-PU"], None, None),
    "33": ("Lodging Trust", "us", ["CLD-PA", "CLD"], None, None),
    "34": ("Foreign Holdings Plc", "foreign", ["ADRY", "ORDF"], None, None),
    "35": ("Crashed Inc", "us", None, date(2014, 1, 6), date(2016, 10, 3)),
    "36": ("Gen Like Corp", "us", ["GENL"], date(2014, 1, 6), date(2016, 10, 3)),
    "37": ("Old Holder Inc", "us", None, date(2014, 1, 6), date(2015, 3, 2)),  # no prices
    "38": ("Brand New Inc", "us", ["NEWB"], date(2016, 6, 1), date(2016, 10, 3)),
    "39": ("Previous Owner Inc", "us", None, date(2014, 1, 6), date(2015, 3, 2)),  # no prices
}
FORMER = {  # cik: (former name, from, to)
    "25": ("Blue Acquisition Corp", "2014-03-03", "2015-06-30"),
    "26": ("OYO GEOSPACE CORP", "2010-01-04", "2015-12-31"),
    "27": ("Parkway Acquisition Corp.", "2010-01-04", "2016-06-30"),
}
FORM4 = [  # cik, ticker, from, to
    ("20", "OLDR", date(2014, 1, 6), date(2015, 12, 28)),
    ("21", "OLDG", date(2014, 1, 6), date(2015, 6, 15)),
    ("22", "OLDJ", date(2014, 1, 6), date(2015, 12, 28)),
    ("23", "OLDT", date(2014, 1, 6), date(2015, 12, 28)),
    ("24", "FWA", date(2014, 1, 6), date(2015, 6, 29)),
    ("24", "FWB", date(2015, 7, 6), date(2016, 10, 3)),
    ("28", "SIS", date(2014, 1, 6), date(2016, 6, 1)),
    ("29", "SIS", date(2015, 1, 5), date(2016, 6, 1)),  # a sister company, the same last day
    ("30", "HOLY", date(2016, 3, 1), date(2016, 10, 3)),
    ("31", "HALT", date(2014, 2, 3), date(2016, 10, 3)),
    ("35", "CRA", date(2014, 1, 6), date(2015, 6, 29)),
    ("35", "CRB", date(2016, 3, 1), date(2016, 10, 3)),  # its own filings under CRB come later
    ("36", "NLKX", date(2014, 1, 6), date(2016, 6, 1)),  # trading under another ticker then
    ("36", "GENL", date(2016, 6, 2), date(2016, 10, 3)),
    ("37", "GENL", date(2014, 1, 6), date(2015, 3, 2)),  # the earlier holder of GENL
    ("39", "NEWB", date(2014, 1, 6), date(2015, 3, 2)),  # the earlier holder of NEWB
]


def build(con, tmp_data, renamed: bool = True) -> None:
    """The world; with `renamed=False`, company 20 has not yet changed OLDR to NEWR."""
    days = SESSIONS if renamed else [d for d in SESSIONS if d < SWITCH]
    _frame(con, "ref.calendar", [{"session": d, "session_no": i} for i, d in enumerate(days)])
    companies = dict(COMPANIES)
    if not renamed:
        companies["20"] = ("Renamed Corp", "us", ["OLDR"], date(2014, 1, 6), date(2015, 12, 28))
    _frame(con, "ref.company", [
        {"cik": c, "name": n, "filer_type": ft, "tickers": t, "exchanges": None,
         "first_form4": a, "last_form4": b, "first_periodic": None, "last_filing": None,
         "is_fund": False, "is_blank_check": False}
        for c, (n, ft, t, a, b) in companies.items()])  # fmt: skip
    for col in ("first_form4", "last_form4", "first_periodic", "last_filing"):
        con.execute(f"alter table ref.company alter {col} type DATE")
    con.execute("alter table ref.company alter exchanges type VARCHAR[]")
    con.execute("alter table ref.company add column former_names "
                "STRUCT(name VARCHAR, valid_from VARCHAR, valid_to VARCHAR)[]")  # fmt: skip
    for cik, (name, a, b) in FORMER.items():
        con.execute("update ref.company set former_names = [{'name': ?, 'valid_from': ?, "
                    "'valid_to': ?}] where cik = ?", [name, a, b, cik])  # fmt: skip
    list_day = LIST_DAY if renamed else days[-1]
    history = [{"cik": c, "ticker": t, "exchange": None, "valid_from": a,
                "valid_to": b if (renamed or b < SWITCH) else days[-1], "evidence": "form4"}
               for c, t, a, b in FORM4 if renamed or a < SWITCH]  # fmt: skip
    history += [{"cik": c, "ticker": t, "exchange": None, "valid_from": list_day,
                 "valid_to": None, "evidence": "sec_list"}
                for c, (_, _, ts, _, _) in companies.items() for t in ts or []]  # fmt: skip
    _frame(con, "ref.ticker_history", history)
    _frame(con, "stg_sec_tickers.snapshot", [
        {"snapshot_date": list_day, "cik": c, "ticker": t, "rank": r}
        for c, (_, _, ts, _, _) in companies.items() for r, t in enumerate(ts or [])])  # fmt: skip
    _frame(con, "stg_sec_form4.submission", [
        {"issuercik": c, "issuername": companies[c][0].upper(), "issuertradingsymbol": t,
         "filing_date": a, "accession_number": f"{c}-{t}-{i}"}
        for c, t, a, b in FORM4 for i in range(1 + 5 * (c == "28"))])  # fmt: skip
    yahoo = (
        _series("NEWR", SWITCH, END, adj=0.9)  # later dividends: adjusted 10% below as traded
        + _series("NEWG", SWITCH, END)
        + _series("NEWJ", SWITCH, END)
        + _series("NEWT", SWITCH, END)
        + _series("MRGD", SESSIONS[0], END)
        + _series("GEOS", SESSIONS[0], END)
        + _series("PKWY", SESSIONS[0], END, close=20.0)
        + _series("SIS", SESSIONS[0], END)
        + _series("HOLY", SESSIONS[0], END, gap=(date(2014, 7, 1), date(2015, 12, 31)))
        + _series("HALT", SESSIONS[0], END, gap=(date(2014, 7, 1), date(2015, 12, 31)))
        + _series("TDZ", SESSIONS[0], END)
        + _series("CLD-PA", SESSIONS[0], END, close=25.0)
        + _series("CLD", SESSIONS[0], END)
        + _series("ORDF", SESSIONS[0], END)
        + _series("GENL", SESSIONS[0], END)  # the provider filed the old history under GENL
        + _series("NEWB", SESSIONS[0], END)
    )
    if not renamed:
        yahoo = [r for r in yahoo if r["session"] < SWITCH]
    _frame(con, "stg_yahoo.price", yahoo)
    tiingo = (
        _series("OLDR", SESSIONS[0], date(2015, 12, 31), src="t")
        + _series("OLDG", SESSIONS[0], date(2015, 6, 30), src="t")
        + _series("OLDJ", SESSIONS[0], date(2015, 12, 31), close=30.0, src="t")
        + _series("OLDT", SESSIONS[0], date(2015, 12, 31), src="t")
        + _series("FWA", SESSIONS[0], date(2015, 6, 30), close=5.0, src="t")
        + _series("FWB", date(2015, 7, 1), END, close=5.0, src="t")
        + _series("SIS", SESSIONS[0], END, src="t")
        + _series("CRA", SESSIONS[0], date(2015, 6, 30), close=12.0, src="t")
        + _series("CRB", date(2015, 5, 1), date(2015, 6, 30), close=12.0, src="t")
        + _series("CRB", date(2015, 7, 1), END, close=4.0, src="t")  # moved and crashed
    )
    _frame(con, "stg_tiingo.price", [r for r in tiingo if r["session"] in set(days)])
    _frame(con, "stg_tiingo.meta", [
        {"ticker": t, "name": n, "start_date": SESSIONS[0], "end_date": END}
        for t, n in (("OLDR", "Renamed Corp"), ("OLDG", "Gapped Corp"), ("OLDJ", "Jumpy Corp"),
                     ("OLDT", "Totally Different Inc"), ("FWA", "Forward Inc"),
                     ("FWB", "Forward Inc"), ("SIS", "Parent Realty"), ("CRA", "Crashed Inc"),
                     ("CRB", "Crashed Inc"))])  # fmt: skip
    _frame(con, "stg_tiingo.listing", [
        {"ticker": t, "exchange": "NYSE", "asset_type": "Stock", "currency": "USD",
         "start_date": a, "end_date": b}
        for t, a, b in (("FWA", SESSIONS[0], date(2015, 6, 30)), ("FWB", date(2015, 7, 1), None),
                        ("CRA", SESSIONS[0], date(2015, 6, 30)),
                        ("SIS", SESSIONS[0], None),
                        ("OLDR", SESSIONS[0], date(2015, 12, 31)))])  # fmt: skip
    _frame(con, "stg_tiingo.search", [{"query": "x", "hit_rank": 0, "ticker": "x",
                                       "asset_type": "Stock"}])  # fmt: skip
    for step in (prices.build_candidates, prices.build_choice, prices.build_daily):
        step(con, tmp_data, **QUIET)


@pytest.fixture
def world(tmp_data):
    con = db.connect(tmp_data)
    build(con, tmp_data)
    yield con
    con.close()


def _span(con, cik):
    return con.execute("select min(session), max(session), list(distinct ticker order by ticker) "
                       "from core.price_daily where cik = ?", [cik]).fetchone()  # fmt: skip


def _decisions(con, cik):
    return {k for (k,) in con.execute("select kind from core.price_decision where cik = ?",
                                      [cik]).fetchall()}  # fmt: skip


def test_a_ticker_change_is_joined_when_names_and_the_switch_agree(world):
    assert _span(world, "20") == (SESSIONS[0], END, ["NEWR", "OLDR"])
    assert "joined" in _decisions(world, "20")
    segs = world.execute("select seq, ticker, main from core.price_choice where cik = '20' "
                         "order by seq").fetchall()  # fmt: skip
    assert segs == [(1, "OLDR", False), (2, "NEWR", True)]


def test_a_join_fails_on_a_gap_a_level_jump_or_another_company(world):
    for cik, reason in (("21", "gap"), ("22", "level"), ("23", "identity")):
        assert _span(world, cik)[0] == SWITCH, cik  # the history still starts at the new ticker
        detail = world.execute("select detail from core.price_decision where cik = ? "
                               "and kind = 'join_failed'", [cik]).fetchone()[0]  # fmt: skip
        assert detail.startswith(reason), (cik, detail)


def test_a_disappeared_company_is_joined_forward_across_its_tickers(world):
    first, last, tickers = _span(world, "24")
    assert tickers == ["FWA", "FWB"] and first == SESSIONS[0]
    assert last == date(2016, 12, 30)  # up to 90 days after its last Form 4 (3 Oct 2016)
    main = world.execute(
        "select ticker from core.price_choice where cik = '24' and main"
    ).fetchone()
    assert main == ("FWB",)


def test_adjusted_prices_stay_continuous_across_a_switch(world):
    rows = world.execute("select session, close, adj_close from core.price_daily where cik = '20' "
                         "and session between '2015-12-30' and '2016-01-05' "
                         "order by session").fetchall()  # fmt: skip
    closes = {c for _, c, _ in rows}
    adjusted = {round(a, 6) for _, _, a in rows}
    assert closes == {10.0} and adjusted == {9.0}  # OLDR's adjusted prices scaled by 0.9


def test_a_later_ticker_change_leaves_earlier_rows_unchanged(tmp_data, tmp_path):
    from sentinel.config import Paths

    before_root = tmp_path / "before"
    (before_root / "config").mkdir(parents=True)
    for f in ("sources.yaml", "risk_params.yaml", "tracker.yaml"):
        (before_root / "config" / f).write_bytes((tmp_data.root / "config" / f).read_bytes())
    p0 = Paths.from_root(before_root)
    c0 = db.connect(p0)
    build(c0, p0, renamed=False)
    c1 = db.connect(tmp_data)
    build(c1, tmp_data, renamed=True)
    q = (
        "select session, close, adj_close / max(adj_close) over () from core.price_daily "
        "where cik = '20' and session < '2015-12-01' order by session"
    )
    early0, early1 = c0.execute(q).fetchall(), c1.execute(q).fetchall()
    assert early0 and early0 == early1  # adjusted prices may be rescaled, never reshaped


def test_blank_check_days_are_cut_but_not_for_lookalike_or_long_lived_names(world):
    assert _span(world, "25")[0] == date(2015, 7, 1)  # Blue Acquisition Corp until 30 Jun 2015
    assert "cut_blank_check" in _decisions(world, "25")
    assert _span(world, "26")[0] == SESSIONS[0]  # "GEOSPACE" is not "SPAC"
    assert _span(world, "27")[0] == SESSIONS[0]  # 6.5 years, never near $10: a bank, not a SPAC
    periods = world.execute("select cik, counted from core.blank_check_period "
                            "order by cik").fetchall()  # fmt: skip
    assert periods == [("25", True), ("27", False)]


def test_a_sister_company_neither_cuts_the_listed_holder_nor_takes_its_prices(world):
    assert _span(world, "28")[0] == SESSIONS[0]  # a use ending the same day does not cut (V2-63+)
    assert "kept_overlap" in _decisions(world, "28")
    assert _span(world, "29")[0] is None  # the listed holder keeps the ticker's days
    assert "lost_to" in _decisions(world, "29")
    twice = world.execute("select count(*) from (select source, ticker, session "
                          "from core.price_daily group by all having count(distinct cik) > 1)"
                          ).fetchone()[0]  # fmt: skip
    assert twice == 0


def test_a_hole_of_over_a_year_ends_the_earlier_part_unless_own_evidence_covers_it(world):
    after = min(d for d in SESSIONS if d > date(2015, 12, 31))
    assert _span(world, "30")[0] == after  # the 2014 block: no own evidence then
    assert "cut_hole" in _decisions(world, "30")
    assert _span(world, "31")[0] == SESSIONS[0]  # its own Form 4s from Feb 2014: a halt, kept


def test_the_common_stock_is_chosen_and_adrs_are_left_alone(world):
    main = dict(world.execute("select cik, ticker from core.price_choice where main").fetchall())
    assert main["32"] == "TDZ"  # TDZPRV, its first SEC ticker, has no data
    assert main["33"] == "CLD"  # not its preferred CLD-PA
    assert main["34"] is None  # a foreign company's ordinary share is not its ADR


def test_overlapping_series_that_move_alike_are_joined_even_across_a_crash(world):
    # Hanger: HNGR repeats HGR's last NYSE weeks, then falls to a third: the same shares
    first, last, tickers = _span(world, "35")
    assert tickers == ["CRA", "CRB"] and first == SESSIONS[0]
    assert "joined" in _decisions(world, "35")


def test_a_series_trading_on_across_an_unpriced_earlier_holder_is_kept_for_a_company_there(world):
    # Gen Digital: Genesis Healthcare used GEN until 2021 and has no prices to compare with; GEN
    # trades on across that day while Gen Digital filed under NLOK: its own history, kept
    assert _span(world, "36")[0] == SESSIONS[0]
    assert "kept_continuous" in _decisions(world, "36")
    # a company with no filings of its own then is still cut after the earlier holder
    assert _span(world, "38")[0] == date(2015, 3, 3)
    assert "cut_reuse" in _decisions(world, "38")
