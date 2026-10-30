import io
import socket
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from sentinel.config import Paths, repo_root, sources

REPO = repo_root(Path(__file__).parent)

# Real column headers of the SEC Form 3/4/5 data sets.
HEADERS = {
    "SUBMISSION": [
        "ACCESSION_NUMBER",
        "FILING_DATE",
        "PERIOD_OF_REPORT",
        "DATE_OF_ORIG_SUB",
        "NO_SECURITIES_OWNED",
        "NOT_SUBJECT_SEC16",
        "FORM3_HOLDINGS_REPORTED",
        "FORM4_TRANS_REPORTED",
        "DOCUMENT_TYPE",
        "ISSUERCIK",
        "ISSUERNAME",
        "ISSUERTRADINGSYMBOL",
        "REMARKS",
    ],
    "REPORTINGOWNER": [
        "ACCESSION_NUMBER",
        "RPTOWNERCIK",
        "RPTOWNERNAME",
        "RPTOWNER_RELATIONSHIP",
        "RPTOWNER_TITLE",
        "RPTOWNER_TXT",
        "RPTOWNER_STREET1",
        "RPTOWNER_STREET2",
        "RPTOWNER_CITY",
        "RPTOWNER_STATE",
        "RPTOWNER_ZIPCODE",
        "RPTOWNER_STATE_DESC",
        "FILE_NUMBER",
    ],
    "NONDERIV_TRANS": [
        "ACCESSION_NUMBER",
        "NONDERIV_TRANS_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "TRANS_DATE",
        "TRANS_DATE_FN",
        "DEEMED_EXECUTION_DATE",
        "DEEMED_EXECUTION_DATE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_CODE",
        "EQUITY_SWAP_INVOLVED",
        "EQUITY_SWAP_TRANS_CD_FN",
        "TRANS_TIMELINESS",
        "TRANS_TIMELINESS_FN",
        "TRANS_SHARES",
        "TRANS_SHARES_FN",
        "TRANS_PRICEPERSHARE",
        "TRANS_PRICEPERSHARE_FN",
        "TRANS_ACQUIRED_DISP_CD",
        "TRANS_ACQUIRED_DISP_CD_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "FOOTNOTES": ["ACCESSION_NUMBER", "FOOTNOTE_ID", "FOOTNOTE_TXT"],
    "NONDERIV_HOLDING": [
        "ACCESSION_NUMBER",
        "NONDERIV_HOLDING_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_FORM_TYPE_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "DERIV_TRANS": [
        "ACCESSION_NUMBER",
        "DERIV_TRANS_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "CONV_EXERCISE_PRICE",
        "CONV_EXERCISE_PRICE_FN",
        "TRANS_DATE",
        "TRANS_DATE_FN",
        "DEEMED_EXECUTION_DATE",
        "DEEMED_EXECUTION_DATE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_CODE",
        "EQUITY_SWAP_INVOLVED",
        "EQUITY_SWAP_TRANS_CD_FN",
        "TRANS_TIMELINESS",
        "TRANS_TIMELINESS_FN",
        "TRANS_SHARES",
        "TRANS_SHARES_FN",
        "TRANS_TOTAL_VALUE",
        "TRANS_TOTAL_VALUE_FN",
        "TRANS_PRICEPERSHARE",
        "TRANS_PRICEPERSHARE_FN",
        "TRANS_ACQUIRED_DISP_CD",
        "TRANS_ACQUIRED_DISP_CD_FN",
        "EXCERCISE_DATE",
        "EXCERCISE_DATE_FN",
        "EXPIRATION_DATE",
        "EXPIRATION_DATE_FN",
        "UNDLYNG_SEC_TITLE",
        "UNDLYNG_SEC_TITLE_FN",
        "UNDLYNG_SEC_SHARES",
        "UNDLYNG_SEC_SHARES_FN",
        "UNDLYNG_SEC_VALUE",
        "UNDLYNG_SEC_VALUE_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "DERIV_HOLDING": [
        "ACCESSION_NUMBER",
        "DERIV_HOLDING_SK",
        "SECURITY_TITLE",
        "SECURITY_TITLE_FN",
        "CONV_EXERCISE_PRICE",
        "CONV_EXERCISE_PRICE_FN",
        "TRANS_FORM_TYPE",
        "TRANS_FORM_TYPE_FN",
        "EXERCISE_DATE",
        "EXERCISE_DATE_FN",
        "EXPIRATION_DATE",
        "EXPIRATION_DATE_FN",
        "UNDLYNG_SEC_TITLE",
        "UNDLYNG_SEC_TITLE_FN",
        "UNDLYNG_SEC_SHARES",
        "UNDLYNG_SEC_SHARES_FN",
        "UNDLYNG_SEC_VALUE",
        "UNDLYNG_SEC_VALUE_FN",
        "SHRS_OWND_FOLWNG_TRANS",
        "SHRS_OWND_FOLWNG_TRANS_FN",
        "VALU_OWND_FOLWNG_TRANS",
        "VALU_OWND_FOLWNG_TRANS_FN",
        "DIRECT_INDIRECT_OWNERSHIP",
        "DIRECT_INDIRECT_OWNERSHIP_FN",
        "NATURE_OF_OWNERSHIP",
        "NATURE_OF_OWNERSHIP_FN",
    ],
    "OWNER_SIGNATURE": ["ACCESSION_NUMBER", "OWNERSIGNATURENAME", "OWNERSIGNATUREDATE"],
}


def build_quarter_zip(
    tables: dict[str, list[dict]] | None = None, omit=(), checkbox=False
) -> bytes:
    """A synthetic quarterly archive with the real headers. Rows are dicts; missing cells are blank.

    `checkbox=True` adds the 2023-onward AFF10B5ONE column to SUBMISSION.
    """
    tables = tables or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, header in HEADERS.items():
            if name in omit:
                continue
            cols = header + (["AFF10B5ONE"] if checkbox and name == "SUBMISSION" else [])
            lines = ["\t".join(cols)]
            for row in tables.get(name, []):
                lines.append("\t".join(str(row.get(c, "")) for c in cols))
            zf.writestr(f"{name}.tsv", "\n".join(lines) + "\n")
    return buf.getvalue()


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", help="run tests marked 'network'")


def pytest_collection_modifyitems(config, items):
    if not Paths.from_root(REPO).build_db.exists():
        skip_slow = pytest.mark.skip(reason="needs the real data/sentinel.duckdb")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="needs --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Tests run offline unless marked `network`."""
    if "network" in request.keywords:
        return

    def blocked(*args, **kwargs):
        raise RuntimeError("network blocked in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def settings():
    return sources(Paths.from_root(REPO))


@pytest.fixture
def fake_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text('SEC_USER_AGENT="Test User test@example.com"\nTIINGO_API=tiingo-secret-123\n')
    return env


@pytest.fixture
def tmp_data(tmp_path) -> Paths:
    """A project root in a temporary folder, with copies of the real settings files."""
    (tmp_path / "config").mkdir()
    for name in ("sources.yaml", "risk_params.yaml", "tracker.yaml"):
        (tmp_path / "config" / name).write_bytes((REPO / "config" / name).read_bytes())
    return Paths.from_root(tmp_path)


@pytest.fixture
def quarter_zip():
    return build_quarter_zip


# --- Synthetic Form 4 archives ---------------------------------------------------------------


def sub(acc, date="15-MAR-2019", doc="4", cik="100", symbol="ABC", aff="", name="Abc Corp"):
    return {
        "ACCESSION_NUMBER": acc,
        "FILING_DATE": date,
        "DOCUMENT_TYPE": doc,
        "ISSUERCIK": cik,
        "ISSUERNAME": name,
        "ISSUERTRADINGSYMBOL": symbol,
        "AFF10B5ONE": aff,
    }


def owner(acc, ocik="9001", rel="Director", title="", name=None):
    return {
        "ACCESSION_NUMBER": acc,
        "RPTOWNERCIK": ocik,
        "RPTOWNERNAME": name or f"Owner {ocik}",
        "RPTOWNER_RELATIONSHIP": rel,
        "RPTOWNER_TITLE": title,
    }


def line(
    acc,
    sk,
    title="Common Stock",
    code="P",
    ad="A",
    tdate="13-MAR-2019",
    shares="1000",
    price="50",  # with 1,000 shares, $50,000: above the G6 minimum
    after="",
    di="D",
    nature="",
    **fn,
):
    row = {
        "ACCESSION_NUMBER": acc,
        "NONDERIV_TRANS_SK": sk,
        "SECURITY_TITLE": title,
        "TRANS_DATE": tdate,
        "TRANS_CODE": code,
        "TRANS_SHARES": shares,
        "TRANS_PRICEPERSHARE": price,
        "TRANS_ACQUIRED_DISP_CD": ad,
        "SHRS_OWND_FOLWNG_TRANS": after,
        "DIRECT_INDIRECT_OWNERSHIP": di,
        "NATURE_OF_OWNERSHIP": nature,
    }
    row.update(fn)
    return row


def holding(acc, sk, title="Common Stock", shares="500", di="I", nature="By Trust"):
    return {
        "ACCESSION_NUMBER": acc,
        "NONDERIV_HOLDING_SK": sk,
        "SECURITY_TITLE": title,
        "SHRS_OWND_FOLWNG_TRANS": shares,
        "DIRECT_INDIRECT_OWNERSHIP": di,
        "NATURE_OF_OWNERSHIP": nature,
    }


def note(acc, fid, txt):
    return {"ACCESSION_NUMBER": acc, "FOOTNOTE_ID": fid, "FOOTNOTE_TXT": txt}


@pytest.fixture
def archives(tmp_data):
    """make({quarter: {TABLE: [rows]}}) writes one zip per quarter and records it as an original."""
    from sentinel.raw.manifest import Manifest, ManifestEntry, sha256_file
    from sentinel.staging.sec_form4 import SOURCE

    def make(quarters: dict[str, dict[str, list[dict]]], checkbox_from: str = "2023q1"):
        tmp_data.sec_insider.mkdir(parents=True, exist_ok=True)
        manifest = Manifest(tmp_data.manifest)
        out = []
        for quarter, tables in sorted(quarters.items()):
            path = tmp_data.sec_insider / f"{quarter}_form345.zip"
            path.write_bytes(build_quarter_zip(tables, checkbox=quarter >= checkbox_from))
            manifest.add(
                ManifestEntry(
                    path=path.relative_to(tmp_data.raw).as_posix(),
                    source=SOURCE,
                    key=quarter,
                    role="original",
                    url=f"https://example.test/{quarter}_form345.zip",
                    fetched_at="2026-10-22T00:00:00Z",
                    bytes=path.stat().st_size,
                    sha256=sha256_file(path),
                    http_last_modified=None,
                    http_etag=None,
                    tool="sentinel test",
                )
            )
            out.append((quarter, path))
        return out

    return make


# --- A synthetic market for layers 4–6 -----------------------------------------------------------

WORLD_SESSIONS = [d.date() for d in pd.bdate_range("2019-01-02", "2021-12-31")]
SPLIT_DAY = date(2020, 7, 1)  # company 1 splits 2-for-1


def frame(con, table: str, rows: list[dict]) -> None:
    """Replace `table` with `rows`."""
    con.register("_t", pd.DataFrame(rows))
    con.execute(f"create or replace table {table} as select * from _t")
    con.unregister("_t")


def next_session(d: date) -> date:
    return next(s for s in WORLD_SESSIONS if s > d)


# fmt: off
def build_world(con) -> None:
    """The core tables of two companies over 2019–2021, as layers 4–6 read them.

    "1" Alpha Corp, a US filer: adjusted close up 0.1% a day, a 2-for-1 split on `SPLIT_DAY`,
    quarterly reports with results released five days before each, a share count up 30% in 2019,
    a 424B5 on its own and one after a term sheet (FWP), a director's purchase (filed 29 June
    2021) and the CFO's planned sale (filed 30 June), FINRA short volume 40% of the total.
    "2" Beta Plc, a foreign filer (20-F only): adjusted close alternating 10 and 10.1. SPY grows
    0.05% a day."""
    prices, spy = [], []
    for i, d in enumerate(WORLD_SESSIONS):
        for cik, ticker in (("1", "AAA"), ("2", "BBB")):
            adj = 10.0 * 1.001**i if cik == "1" else 10.0 * (1.01 if i % 2 else 1.0)
            cum = 2.0 if cik == "1" and d < SPLIT_DAY else 1.0
            close = adj * cum
            prices.append({
                "cik": cik, "session": d, "source": "yahoo", "ticker": ticker, "open": close,
                "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 100_000.0,
                "adj_close": adj, "cum_split_after": cum,
                "split_ratio": 2.0 if cik == "1" and d == SPLIT_DAY else 0.0, "dividend": 0.0,
                "dollar_volume": close * 100_000.0, "glitch": False,
            })
        spy.append({"ticker": "SPY", "session": d, "close": 300 * 1.0005**i,
                    "adj_close": 300 * 1.0005**i})
    frame(con, "ref.calendar", [{"session": d, "session_no": i}
                                for i, d in enumerate(WORLD_SESSIONS)])
    frame(con, "core.price_daily", prices)
    frame(con, "stg_yahoo.price", spy)
    company = {"former_names": None, "sic_description": None, "first_periodic": date(2019, 5, 1),
               "last_periodic": date(2021, 11, 1), "last_filing": date(2021, 11, 1),
               "is_fund": False, "is_blank_check": False, "first_form4": None,
               "last_form4": None}
    frame(con, "ref.company", [
        company | {"cik": "1", "name": "Alpha Corp", "filer_type": "us", "sic": "3674",
                   "tickers": ["AAA"], "exchanges": ["Nasdaq"], "is_form4_issuer": True},
        company | {"cik": "2", "name": "Beta Plc", "filer_type": "foreign", "sic": "2834",
                   "tickers": ["BBB"], "exchanges": ["NYSE"], "is_form4_issuer": False},
    ])
    frame(con, "ref.sector", [{"cik": "1", "sic": "3674", "sector": "BusEq"},
                              {"cik": "2", "sic": "2834", "sector": "Hlth"}])
    frame(con, "ref.security", [
        {"security_id": c, "cik": c, "ticker": t, "source": "yahoo", "listed": True,
         "first_session": WORLD_SESSIONS[0], "last_session": WORLD_SESSIONS[-1],
         "n_sessions": len(WORLD_SESSIONS), "coverage": cov, "market_value_known": c == "1"}
        for c, t, cov in (("1", "AAA", "full"), ("2", "BBB", "foreign"))
    ])
    reports = [date(2019, 5, 1), date(2019, 8, 1), date(2019, 11, 1), date(2020, 2, 3),
               date(2020, 5, 1), date(2020, 8, 3), date(2020, 11, 2), date(2021, 2, 1),
               date(2021, 5, 3), date(2021, 8, 2), date(2021, 11, 1)]
    filings = []
    for k, filed in enumerate(reports):
        released = filed - timedelta(days=6)
        while released.weekday() > 4:
            released -= timedelta(days=1)
        filings += [("1", f"q{k}", "10-K" if filed.month == 2 else "10-Q", filed, None),
                    ("1", f"r{k}", "8-K", released, "2.02,9.01")]
    filings += [("1", "o1", "424B5", date(2021, 3, 15), None),
                ("1", "w2", "FWP", date(2021, 4, 19), None),
                ("1", "o2", "424B5", date(2021, 4, 20), None)]
    filings += [("2", f"f{y}", "20-F", date(y, 4, 30), None) for y in (2019, 2020, 2021)]
    frame(con, "core.filing", [
        {"cik": c, "accession": a, "form": f, "filing_date": d, "report_date": d, "items": it,
         "accepted_at_et": None, "known_at": next_session(d)} for c, a, f, d, it in filings
    ])
    frame(con, "core.results_release", [
        {"cik": "1", "filing_date": d, "report_date": d, "report_filed": reports[int(a[1:])],
         "confirmed": reports[int(a[1:])]} for c, a, f, d, it in filings if f == "8-K"
    ])
    facts = []
    for filed in reports:
        q_end = {2: date(filed.year - 1, 12, 31), 5: date(filed.year, 3, 31),
                 8: date(filed.year, 6, 30), 11: date(filed.year, 9, 30)}[filed.month]
        for item, value in (("equity", 5000.0), ("assets", 10000.0), ("cash", 2000.0)):
            facts.append(("1", item, None, q_end, value, filed))
        facts.append(("1", "net_income", q_end - timedelta(days=90), q_end, -10.0, filed))
    facts += [("1", "revenue", date(2019, 1, 1), date(2019, 12, 31), 1000.0, date(2020, 2, 3)),
              ("1", "revenue", date(2020, 1, 1), date(2020, 12, 31), 1200.0, date(2021, 2, 1)),
              ("1", "operating_cash_flow", date(2020, 1, 1), date(2020, 12, 31), -500.0,
               date(2021, 2, 1))]
    frame(con, "core.financial_fact", [
        {"cik": c, "item": it, "period_start": a, "period_end": b,
         "period_days": (b - a).days if a else None, "value": v, "unit": "USD", "filed": f,
         "accession": "x", "form": "10-Q", "fp": "Q1", "taxonomy": "us-gaap", "tag": it,
         "first_filed": True, "known_at": next_session(f)} for c, it, a, b, v, f in facts
    ])
    counts = [(date(2019, 4, 25), 1000.0, reports[0])] + [
        (f - timedelta(days=7), 1300.0 if f < SPLIT_DAY else 2600.0, f) for f in reports[1:]
    ]
    counts_2 = [(date(y - 1, 12, 31), 5000.0, date(y, 4, 30)) for y in (2019, 2020, 2021)]
    frame(con, "core.shares_outstanding", [
        {"cik": c, "as_of": a, "shares": s, "filed": f, "known_at": next_session(f),
         "source": "cover_page"} for c, rows in (("1", counts), ("2", counts_2))
        for a, s, f in rows
    ])  # "2" files ordinary-share counts on its 20-F
    trade = {"issuer_cik": "1", "quarter": "2021q2", "g1_form4": True, "g3_common": True,
             "g4a_no_checkbox": True, "g5_no_offering_fn": True}
    frame(con, "core.insider_trade", [
        trade | {"accession": "b1", "filing_date": date(2021, 6, 29),
                 "known_at": date(2021, 6, 30), "trans_code": "P", "acq_disp": "A",
                 "value_usd": 50_000.0, "g4b_no_plan_fn": True},
        trade | {"accession": "s1", "filing_date": date(2021, 6, 30),
                 "known_at": date(2021, 7, 1), "trans_code": "S", "acq_disp": "D",
                 "value_usd": 30_000.0, "g4b_no_plan_fn": False},
    ])
    frame(con, "stg_sec_form4.reportingowner", [
        {"accession_number": "b1", "quarter": "2021q2", "rptownercik": "9001"},
        {"accession_number": "s1", "quarter": "2021q2", "rptownercik": "9002"},
    ])
    frame(con, "core.insider_owner_role", [
        {"issuer_cik": "1", "owner_cik": "9001", "valid_from": date(2019, 1, 2),
         "role": "director", "seniority": 2},
        {"issuer_cik": "1", "owner_cik": "9002", "valid_from": date(2019, 1, 2),
         "role": "ceo_cfo", "seniority": 4},
    ])
    activity = {"issuer_cik": "1", "quarter": "2021q2", "n_lines": 1, "offering": False,
                "shares_before": 1000.0, "opens_position": False, "closes_position": False}
    frame(con, "core.insider_activity", [
        activity | {"accession": "b1", "side": "buy", "filing_date": date(2021, 6, 29),
                    "known_at": date(2021, 6, 30), "entity_id": "1:9001", "entity_role": "director",
                    "entity_seniority": 2, "owner_ciks": ["9001"], "owner_names": ["SMITH A"],
                    "value_usd": 50_000.0, "shares": 1000.0, "avg_price": 50.0,
                    "min_trade_date": date(2021, 6, 25), "max_trade_date": date(2021, 6, 25),
                    "planned": False, "clean_value_usd": 50_000.0, "clean": True,
                    "shares_after": 2000.0},
        activity | {"accession": "s1", "side": "sell", "filing_date": date(2021, 6, 30),
                    "known_at": date(2021, 7, 1), "entity_id": "1:9002", "entity_role": "ceo_cfo",
                    "entity_seniority": 4, "owner_ciks": ["9002"], "owner_names": ["JONES B"],
                    "value_usd": 30_000.0, "shares": 600.0, "avg_price": 50.0,
                    "min_trade_date": date(2021, 6, 28), "max_trade_date": date(2021, 6, 28),
                    "planned": True, "clean_value_usd": None, "clean": False,
                    "shares_after": 400.0},
    ])
    frame(con, "core.insider_filing", [
        {"accession": a, "issuer_cik": "1", "filing_date": d, "known_at": next_session(d)}
        for a, d in (("b1", date(2021, 6, 29)), ("s1", date(2021, 6, 30)))
    ])
    frame(con, "core.insider_cluster", [
        {"issuer_cik": "1", "cluster_date": date(2021, 6, 29), "grp": "B2",
         "known_at": date(2021, 6, 30), "n_entities": 1, "total_value_usd": 150_000.0,
         "max_seniority": 2, "top_role": "director", "accessions": ["b1"],
         "entity_ids": ["1:9001"], "starts_event": True},
    ])
    frame(con, "core.short_volume", [
        {"cik": "1", "session": d, "short_volume": 40.0, "total_volume": 100.0, "n_symbols": 1}
        for d in WORLD_SESSIONS
    ])
    macro = [("VIX", "market", d, 20.0, d) for d in WORLD_SESSIONS]
    macro += [(s, "market", d, 2.0, d) for s in ("DGS2", "DGS10", "T10Y2Y", "DFF", "BAA10Y")
              for d in WORLD_SESSIONS]
    months = pd.date_range("2018-01-01", "2021-12-01", freq="MS").date
    macro += [("CPIAUCSL", "first", m, 100.0 * 1.002**k, m + timedelta(days=45))
              for k, m in enumerate(months)]
    macro += [("UNRATE", "first", m, 4.0, m + timedelta(days=35)) for m in months]
    frame(con, "core.macro_observation", [
        {"series": s, "mode": mode, "period": per, "value": v, "available": av,
         "known_at": av if av in set(WORLD_SESSIONS) else next_session(av)}
        for s, mode, per, v, av in macro
        if av <= WORLD_SESSIONS[-1]
    ])
# fmt: on
