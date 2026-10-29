import io
import socket
import zipfile
from datetime import date
from pathlib import Path

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
    for name in ("sources.yaml", "risk_params.yaml"):
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


STEPS = ("stage", "entities", "gates", "prelim", "symbols")


@pytest.fixture
def pipeline(tmp_data, params):
    """run(until=step) builds the warehouse from the recorded archives; returns the connection."""
    from sentinel import warehouse

    cons = []

    def run(until="prelim", snapshot=None, cutoff=None, issuers=None):
        from sentinel.core import stage

        con = warehouse.connect(tmp_data)
        cons.append(con)
        stage.stage_all(con, stage.stored_archives(tmp_data))
        steps = STEPS[1 : STEPS.index(until) + 1]
        # Imported per step, so a story's tests run before the later steps exist.
        if "entities" in steps:
            from sentinel.core import entities

            entities.build(con, params, cutoff=cutoff, issuers=issuers)
        if "gates" in steps:
            from sentinel.core import gates

            gates.build(con, params, cutoff=cutoff, issuers=issuers)
        if "prelim" in steps:
            from sentinel.events import prelim

            prelim.detect_prelim(con, params, cutoff=cutoff, issuers=issuers)
        if "symbols" in steps:
            from sentinel.core import symbols

            symbols.build_symbol_map(con, snapshot, params, cutoff=cutoff)
        return con

    yield run
    for con in cons:
        con.close()


# --- Feature 004: synthetic market and company data ---------------------------------------------
# Synthetic only: no real Tiingo data is ever committed (constitution VI).

YAHOO_FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
TIINGO_COLUMNS = [
    "date", "close", "high", "low", "open", "volume",
    "adjClose", "adjHigh", "adjLow", "adjOpen", "adjVolume", "divCash", "splitFactor",
]  # fmt: skip


def weekdays(start, n: int, holidays=()) -> list:
    """`n` weekdays from `start` (a date), skipping `holidays`."""
    from datetime import timedelta

    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5 and d not in holidays:
            days.append(d)
        d += timedelta(days=1)
    return days


def _bar(r: dict) -> dict:
    close = r["close"]
    return {
        "open": r.get("open", close),
        "high": r.get("high", close),
        "low": r.get("low", close),
        "close": close,
        "volume": r.get("volume", 100_000),
        "adj_close": r.get("adj_close", close),
        "dividend": r.get("dividend", 0.0),
        "split": r.get("split", 1.0),
    }


def yahoo_frame(data: dict[str, list[dict]]):
    """Shaped like `yf.download(tickers, auto_adjust=False, actions=True, group_by="ticker")`:
    columns (ticker, field). Rows: `session`, `close` and optional `open`, `high`, `low`,
    `adj_close`, `volume`, `dividend`, `split` (Yahoo's ratio: 2.0 for 2-for-1, 0.1 for 1-for-10;
    written as 0 on days without a split, as Yahoo does)."""
    import pandas as pd

    frames = {}
    for ticker, rows in data.items():
        bars = [_bar(r) for r in rows]
        frames[ticker] = pd.DataFrame(
            {
                "Open": [b["open"] for b in bars],
                "High": [b["high"] for b in bars],
                "Low": [b["low"] for b in bars],
                "Close": [b["close"] for b in bars],
                "Adj Close": [b["adj_close"] for b in bars],
                "Volume": [b["volume"] for b in bars],
                "Dividends": [b["dividend"] for b in bars],
                "Stock Splits": [0.0 if b["split"] == 1.0 else b["split"] for b in bars],
            },
            index=pd.DatetimeIndex([pd.Timestamp(r["session"]) for r in rows], name="Date"),
        )
    return pd.concat(frames, axis=1)


def tiingo_csv(rows: list[dict]) -> str:
    """Synthetic text in Tiingo's daily CSV layout (raw prices unprefixed). Rows as in
    `yahoo_frame`, with `split` as Tiingo's `splitFactor` (1.0 on days without a split)."""
    lines = [",".join(TIINGO_COLUMNS)]
    for r in rows:
        b = _bar(r)
        adj = b["adj_close"] / b["close"]
        lines.append(
            ",".join(
                str(v)
                for v in (
                    r["session"].isoformat(), b["close"], b["high"], b["low"], b["open"],
                    b["volume"], b["adj_close"], b["high"] * adj, b["low"] * adj, b["open"] * adj,
                    b["volume"], b["dividend"], b["split"],
                )
            )
        )  # fmt: skip
    return "\n".join(lines) + "\n"


def market_sessions(con, start=None, n: int = 300, holidays=()) -> list:
    """`core.session` of `n` weekdays from `start` (default 2019-01-02), numbered from 1."""
    from datetime import date

    from sentinel.core import prices

    prices.create_price_tables(con)
    days = weekdays(start or date(2019, 1, 2), n, holidays)
    con.execute("delete from core.session")
    numbered = [(d, i + 1) for i, d in enumerate(days)]
    con.executemany("insert into core.session values (?, ?)", numbered)
    return days


def market_prices(con, issuer: str, rows: list[dict], source="yahoo", ticker=None) -> None:
    """One chosen primary series for `issuer` in `core.price_series`, and its rows in
    `core.price_daily` (as-traded values; `cum_split_after` defaults to 1)."""
    from sentinel.core import prices

    prices.create_price_tables(con)
    ticker = ticker or f"T{issuer}"
    con.executemany(
        "insert into core.price_daily values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                issuer, r["session"], source, ticker, b["open"], b["high"], b["low"], b["close"],
                b["volume"], b["adj_close"], r.get("cum_split_after", 1.0), b["split"],
                b["dividend"], b["close"] * b["volume"],
            )
            for r in rows
            for b in [_bar(r)]
        ],
    )  # fmt: skip
    sessions = [r["session"] for r in rows]
    con.execute(
        "insert into core.price_series values (?, ?, ?, 'primary', ?, ?, ?, 'ok', true, ?)",
        [issuer, source, ticker, min(sessions), max(sessions), len(rows), f"{source}_primary"],
    )


def _cik10(cik) -> str:
    return f"CIK{int(cik):010d}"


def submissions_zip(companies: dict, recent_size: int = 1000) -> bytes:
    """SEC `submissions.zip` layout. `companies[cik]` = {name, sic, sic_label, exchanges, tickers,
    filings: [(accession, form, filing_date, report_date, items)]}, newest first. Filings beyond
    `recent_size` go to an extra page `CIK…-submissions-001.json`, as the SEC splits long
    histories."""
    import json

    keys = ["accessionNumber", "form", "filingDate", "reportDate", "items"]

    def arrays(filings):
        return {
            k: [str(f[i]) if f[i] is not None else "" for f in filings] for i, k in enumerate(keys)
        }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cik, c in companies.items():
            filings = c.get("filings", [])
            recent, older = filings[:recent_size], filings[recent_size:]
            files = []
            if older:
                page = f"{_cik10(cik)}-submissions-001.json"
                zf.writestr(page, json.dumps(arrays(older)))
                files.append({"name": page, "filingCount": len(older)})
            doc = {
                "cik": str(cik),
                "name": c.get("name", f"Company {cik}"),
                "sic": str(c.get("sic", "")),
                "sicDescription": c.get("sic_label", ""),
                "exchanges": c.get("exchanges", []),
                "tickers": c.get("tickers", []),
                "filings": {"recent": arrays(recent), "files": files},
            }
            zf.writestr(f"{_cik10(cik)}.json", json.dumps(doc))
    return buf.getvalue()


def companyfacts_zip(companies: dict) -> bytes:
    """SEC `companyfacts.zip` layout. `companies[cik]` = {"dei:EntityCommonStockSharesOutstanding":
    {"shares": [fact, …]}, "us-gaap:Assets": {"USD": [fact, …]}, …}; a fact is a dict with
    `end`, `val`, `accn`, `filed`, `form`, `fp` and, for durations, `start`."""
    import json

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cik, tags in companies.items():
            facts: dict = {}
            for qualified, units in tags.items():
                taxonomy, tag = qualified.split(":")
                facts.setdefault(taxonomy, {})[tag] = {"label": tag, "units": units}
            doc = {"cik": int(cik), "entityName": f"Company {cik}", "facts": facts}
            zf.writestr(f"{_cik10(cik)}.json", json.dumps(doc))
    return buf.getvalue()


# Synthetic universe and raw files, written the way the fetchers write them (feature 004).

PAID_DAY = date(2026, 11, 2)  # inside the test paid window [2026-10-29, 2026-11-28)


def universe_tables(con) -> None:
    """The feature 002 tables the price steps read, with only the columns they use."""
    con.execute(
        "create table if not exists core.symbol_map (issuer_cik VARCHAR, ticker VARCHAR, "
        "valid_from DATE, valid_to DATE, price_source VARCHAR, match_quality VARCHAR)"
    )
    con.execute(
        "create table if not exists evt.prelim_event (issuer_cik VARCHAR, signal_date DATE)"
    )
    con.execute(
        "create table if not exists core.filing (accession VARCHAR, issuer_cik VARCHAR, "
        "filing_date DATE, symbol_raw VARCHAR, issuer_name VARCHAR)"
    )


def issuer(con, cik, ticker, source, name, first_event=date(2012, 1, 5),
           valid=(date(2010, 1, 4), None)):  # fmt: skip
    """An issuer of the price universe: one symbol-map row, one preliminary event, one filing."""
    con.execute("insert into core.symbol_map values (?, ?, ?, ?, ?, 'x')",
                [cik, ticker, valid[0], valid[1], source])  # fmt: skip
    con.execute("insert into evt.prelim_event values (?, ?)", [cik, first_event])
    con.execute("insert into core.filing values (?, ?, ?, ?, ?)",
                [f"{cik}-1", cik, valid[0], ticker, name])  # fmt: skip


def store_yahoo(paths, params, data: dict) -> None:
    """Yahoo files for `{ticker: rows}` through the real downloader (a stand-in for yfinance)."""
    from sentinel.ingest import yahoo

    def fetch(tickers, **kwargs):
        return yahoo_frame({t: data[t] for t in tickers if t in data})

    yahoo.download(
        paths, params, list(data), fetch=fetch, sleep=lambda s: None, echo=lambda *a: None
    )


def store_tiingo(paths, params, listing_rows, series: dict, metas: dict, today=PAID_DAY) -> None:
    """Synthetic Tiingo files: the ticker list, meta answers and price CSVs (paid window only)."""
    import gzip
    import json

    from sentinel.ingest import manifest, tiingo

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        lines = ["ticker,exchange,assetType,priceCurrency,startDate,endDate"]
        zf.writestr("t.csv", "\n".join(lines + [",".join(r) for r in listing_rows]) + "\n")
    tiingo.store_list(paths, params, buf.getvalue(), "u", today)
    book = manifest.Manifest(paths.manifest)
    for t, meta in metas.items():
        data = gzip.compress(json.dumps(meta).encode())
        tiingo._write(paths, book, f"tiingo/meta/{t}.json.gz", f"meta/{t}", data, "u")
    for t, rows in series.items():
        data = gzip.compress(tiingo_csv(rows).encode())
        tiingo._write(paths, book, f"tiingo/prices/{t}.csv.gz", f"prices/{t}", data, "u")


def headers_table(con) -> None:
    con.execute(
        "create table if not exists core.filing_header (accession VARCHAR, issuer_cik VARCHAR, "
        "form_type VARCHAR, filed_as_of DATE, accepted_at_et TIMESTAMP_S, sic VARCHAR, "
        "sic_label VARCHAR, raw_path VARCHAR)"
    )


@pytest.fixture
def market_events(archives, pipeline):
    """run(*filings, prices=…, headers=…) → a warehouse built through the gates (feature 002) from
    synthetic filings, plus a market calendar, chosen price series and signal-filing headers.

    `filings` are (submissions, owners, lines) triples; `prices[cik]` are `market_prices` rows;
    every Form 4 gets a header with SIC 3674 unless `headers[accession]` gives another SIC, None
    (a header without SIC) or "missing" (no header)."""

    def run(*filings, prices=None, headers=None, sessions=None, quarter="2019q1"):
        tables = {"SUBMISSION": [], "REPORTINGOWNER": [], "NONDERIV_TRANS": []}
        for subs, owners, lines in filings:
            tables["SUBMISSION"] += subs
            tables["REPORTINGOWNER"] += owners
            tables["NONDERIV_TRANS"] += lines
        archives({quarter: tables})
        con = pipeline(until="gates")
        market_sessions(con, **(sessions or {"start": date(2018, 10, 1), "n": 260}))
        for cik, rows in (prices or {}).items():
            market_prices(con, cik, rows)
        headers_table(con)
        headers = headers or {}
        for acc, cik, filed in con.execute(
            "select accession, issuer_cik, filing_date from core.filing where document_type = '4'"
        ).fetchall():
            sic = headers.get(acc, "3674")
            if sic != "missing":
                con.execute(
                    "insert into core.filing_header values (?, ?, '4', ?, null, ?, null, null)",
                    [acc, cik, filed, sic],
                )
        return con

    return run


def flat(sessions, close=10.0, volume=50_000, **extra) -> list[dict]:
    """A flat price path over `sessions` (dollar volume close × volume each day)."""
    return [{"session": d, "close": close, "volume": volume, **extra} for d in sessions]


# --- Feature 005: stock lookup -------------------------------------------------------------------


def lookup_filings() -> dict[str, dict[str, list[dict]]]:
    """A PayPal-like company (CIK 100, ticker ABC, earlier ABCD) with every lookup case: a
    director's $100k purchase with a price footnote (a B2 event on 11 Mar), a second director
    buying through five trusts with an untraded direct holding (a cluster on 15 Mar), a sale, an
    award, an option exercise, a 4/A amendment, a joint fund filing, and an officer promoted to CEO
    (COO in 2018 and on 20 Mar, CEO on 25 Mar). CIK 200 has a Form 3 and no transactions; CIK 300's
    name contains CIK 100's."""
    trusts = [("21", "495"), ("22", "605"), ("23", "150"), ("24", "72"), ("25", "225")]
    return {
        "2018q4": {
            "SUBMISSION": [sub("f8", date="10-DEC-2018", symbol="ABCD")],
            "REPORTINGOWNER": [owner("f8", ocik="9003", rel="Officer",
                                     title="Chief Operating Officer", name="LEE ANN")],
            "NONDERIV_TRANS": [line("f8", "81", code="A", tdate="07-DEC-2018", shares="1000",
                                    price="0", after="9000")],
        },
        "2019q1": {
            "SUBMISSION": [
                sub("f1", date="11-MAR-2019"), sub("f2", date="15-MAR-2019"),
                sub("f3", date="20-MAR-2019"), sub("f4", date="20-MAR-2019"),
                sub("f6", date="22-MAR-2019", doc="4/A"), sub("f7", date="22-MAR-2019"),
                sub("f9", date="25-MAR-2019"),
                sub("g1", date="12-MAR-2019", doc="3", cik="200", symbol="EMPT", name="Empty Co"),
                sub("h1", date="13-MAR-2019", cik="300", symbol="ABCH", name="Abc Corp Holdings"),
            ],
            "REPORTINGOWNER": [
                owner("f1", ocik="9001", name="SMITH JOHN"),
                owner("f2", ocik="9002", name="JONES MARY"),
                owner("f3", ocik="9003", rel="Officer", title="Chief Operating Officer",
                      name="LEE ANN"),
                owner("f4", ocik="9004", rel="Officer", title="VP Finance", name="KIM DAN"),
                owner("f6", ocik="9001", name="SMITH JOHN"),
                owner("f7", ocik="9005", rel="TenPercentOwner", name="FUND LP"),
                owner("f7", ocik="9006", rel="TenPercentOwner", name="FUND GP LLC"),
                owner("f9", ocik="9003", rel="Officer", title="Chief Executive Officer",
                      name="LEE ANN"),
                owner("g1", ocik="9100", name="NEW DIRECTOR"),
                owner("h1", ocik="9200", name="OTHER PERSON"),
            ],
            "NONDERIV_TRANS": [
                line("f1", "11", tdate="08-MAR-2019", shares="2000", price="50", after="11000",
                     TRANS_PRICEPERSHARE_FN="F1"),
                *[line("f2", sk, tdate="15-MAR-2019", shares=n, price="20", after=n, di="I",
                       nature=f"Trust {i}") for i, (sk, n) in enumerate(trusts, start=1)],
                line("f3", "31", code="S", ad="D", tdate="18-MAR-2019", shares="500", price="55",
                     after="8500"),
                line("f4", "41", code="M", tdate="19-MAR-2019", shares="1000", price="10",
                     after="1000"),
                line("f6", "61", tdate="08-MAR-2019", shares="2000", price="50", after="11000"),
                line("f7", "71", shares="100", price="30", after="50000", di="I", nature="By Fund"),
                line("f9", "91", code="A", tdate="25-MAR-2019", shares="2000", price="0",
                     after="10500"),
                line("h1", "101", code="S", ad="D", shares="100", price="12", after="900"),
            ],
            "NONDERIV_HOLDING": [holding("f2", "h21", shares="44890", di="D", nature="")],
            "FOOTNOTES": [note("f1", "F1", "Weighted average price; bought at $49.80 to $50.20.")],
        },
    }  # fmt: skip


@pytest.fixture
def lookup_paths(archives, pipeline, tmp_data, params) -> Paths:
    """`data/lookup.duckdb` built from `lookup_filings()`; returns the paths."""
    from sentinel.api import lookup

    archives(lookup_filings())
    con = pipeline(until="prelim")
    con.execute(
        "insert into core.build_log values ('prelim', TIMESTAMP '2026-10-24 10:00:00', "
        "TIMESTAMP '2026-10-24 10:01:00', 'test', 1)"
    )
    con.close()  # the build attaches the warehouse read-only
    lookup.build(tmp_data, params)
    return tmp_data


@pytest.fixture
def lookup_client(lookup_paths):
    from fastapi.testclient import TestClient
    from sentinel.api.app import create_app

    with TestClient(create_app(lookup_paths)) as client:
        yield client
