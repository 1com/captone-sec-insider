"""Layer 2: the SEC company files, prices and market sources staged completely and typed."""

import gzip
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from sentinel import db
from sentinel.raw.manifest import Manifest, ManifestEntry, sha256_file
from sentinel.staging import market, prices, sec_filings, sec_xbrl

QUIET = {"echo": lambda s: None}


def _zip(entries: dict[str, object]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, doc in entries.items():
            z.writestr(name, doc if isinstance(doc, str) else json.dumps(doc))
    return buf.getvalue()


def _record(paths, rel: str, key: str, source: str, url: str = "https://example.test",
            fetched_at: str = "2026-10-29T00:00:00Z") -> None:  # fmt: skip
    file = paths.raw / rel
    Manifest(paths.manifest).add(ManifestEntry(
        path=rel, source=source, key=key, role="original", url=url,
        fetched_at=fetched_at, bytes=file.stat().st_size, sha256=sha256_file(file),
        http_last_modified=None, http_etag=None, tool="test"))  # fmt: skip


def _filings(forms, dates, items=None):
    n = len(forms)
    return {"accessionNumber": [f"0000000001-20-{i:06d}" for i in range(n)], "form": forms,
            "filingDate": dates, "reportDate": dates, "items": items or [""] * n,
            "acceptanceDateTime": ["2020-01-01T00:00:00.000Z"] * n}  # fmt: skip


def test_filers_are_all_kept_but_only_companies_have_their_filings_staged(tmp_data):
    company = {"cik": "0000000042", "name": "Acme Corp", "entityType": "operating", "sic": "3571",
               "tickers": ["ACME"], "exchanges": ["Nasdaq"],
               "formerNames": [{"name": "Old Acme", "from": "2001-01-01T00:00:00.000Z",
                                "to": "2015-06-30T00:00:00.000Z"}],
               "filings": {"recent": _filings(["10-K", "8-K"], ["2020-03-01", "2020-04-01"],
                                              ["", "2.02,9.01"]),
                           "files": [{"name": "CIK0000000042-submissions-001.json"}]}}  # fmt: skip
    person = {"cik": "0000009001", "name": "DOE JANE", "entityType": "other", "sic": "",
              "insiderTransactionForOwnerExists": 1,
              "filings": {"recent": _filings(["4", "4"],
                                             ["2020-03-02", "2020-05-02"])}}  # fmt: skip
    page = _filings(["10-Q"], ["2012-05-01"])
    tmp_data.sec_company.mkdir(parents=True)
    (tmp_data.sec_company / "submissions.zip").write_bytes(_zip({
        "CIK0000000042.json": company, "CIK0000000042-submissions-001.json": page,
        "CIK0000009001.json": person}))  # fmt: skip
    con = db.connect(tmp_data)
    assert sec_filings.stage(con, tmp_data, **QUIET) == {"filer": 2, "filing": 3}
    filers = con.execute(
        "select cik, is_company, n_filings, former_names[1].valid_to from stg_sec_filings.filer "
        "order by cik"
    ).fetchall()
    assert filers == [("42", True, 3, "2015-06-30"), ("9001", False, 2, None)]
    rows = con.execute(
        "select form, filing_date, items from stg_sec_filings.filing order by filing_date"
    ).fetchall()
    assert rows == [("10-Q", date(2012, 5, 1), None), ("10-K", date(2020, 3, 1), None),
                    ("8-K", date(2020, 4, 1), "2.02,9.01")]  # fmt: skip


def test_every_version_of_a_wanted_value_is_kept_and_other_tags_are_not(tmp_data):
    def fact(end, val, filed, accn, start=None):
        return {"end": end, "val": val, "filed": filed, "accn": accn, "form": "10-Q",
                "fp": "Q1", "fy": 2020} | ({"start": start} if start else {})  # fmt: skip

    doc = {"cik": 42, "facts": {
        "us-gaap": {
            "Assets": {"units": {"USD": [fact("2020-03-31", 100, "2020-05-01", "a1"),
                                         fact("2020-03-31", 110, "2021-05-01", "a2")]}},  # restated
            "Goodwill": {"units": {"USD": [fact("2020-03-31", 5, "2020-05-01", "a1")]}},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {
            "units": {"shares": [fact("2020-04-20", 1000, "2020-05-01", "a1")]}}},
    }}  # fmt: skip
    tmp_data.sec_company.mkdir(parents=True)
    (tmp_data.sec_company / "companyfacts.zip").write_bytes(_zip({"CIK0000000042.json": doc}))
    con = db.connect(tmp_data)
    assert sec_xbrl.stage(con, tmp_data, **QUIET) == {"fact": 3}
    got = con.execute(
        "select tag, value, filed from stg_sec_xbrl.fact order by tag, filed"
    ).fetchall()
    assert got == [("Assets", 100.0, date(2020, 5, 1)), ("Assets", 110.0, date(2021, 5, 1)),
                   ("EntityCommonStockSharesOutstanding", 1000.0, date(2020, 5, 1))]  # fmt: skip


def _bars(closes: list[float], days: list[str]) -> dict:
    return {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Adj Close": closes,
            "Volume": [100] * len(closes), "Dividends": [0.0] * len(closes),
            "Stock Splits": [0.0] * len(closes), "Date": pd.to_datetime(days)}  # fmt: skip


def _yahoo(path: Path, closes: list[float], days=("2020-01-02", "2020-01-03")) -> None:
    """A full-history file, one ticker (v1's layout)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(_bars(closes, list(days)[: len(closes)])).to_parquet(path, index=False)


def _yahoo_window(path: Path, rows: list[tuple[str, str, float]]) -> None:
    """A daily window file: (ticker, day, close) rows of many tickers, long format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(_bars([r[2] for r in rows], [r[1] for r in rows]))
    frame.insert(0, "ticker", [r[0] for r in rows])
    frame.to_parquet(path, index=False)


def test_each_price_day_comes_from_the_newest_file_after_the_newest_full_history(tmp_data):
    y = tmp_data.raw / "yahoo"
    _yahoo(y / "AAA.parquet", [10.0, 11.0])
    _record(tmp_data, "yahoo/AAA.parquet", "AAA", "yahoo", fetched_at="2026-10-20T20:00:00Z")
    _yahoo_window(y / "daily/2026-10-21/batch-000.parquet",
                  [("AAA", "2020-01-03", 11.5), ("AAA", "2020-01-06", 12.0)])  # fmt: skip
    _record(tmp_data, "yahoo/daily/2026-10-21/batch-000.parquet", "daily/2026-10-21/000", "yahoo",
            fetched_at="2026-10-21T22:00:00Z")  # fmt: skip
    con = db.connect(tmp_data)

    def closes():
        prices.stage_yahoo(con, tmp_data, **QUIET)
        return con.execute("select session, close from stg_yahoo.price order by 1").fetchall()

    # a window adds a day and replaces a day the provider revised
    assert closes() == [(date(2020, 1, 2), 10.0), (date(2020, 1, 3), 11.5),
                        (date(2020, 1, 6), 12.0)]  # fmt: skip
    # a 2-for-1 split: the full history fetched again supersedes everything older
    _yahoo(y / "history/2026-10-22/AAA.parquet", [5.0, 5.75, 6.0],
           days=("2020-01-02", "2020-01-03", "2020-01-06"))  # fmt: skip
    _record(tmp_data, "yahoo/history/2026-10-22/AAA.parquet", "history/AAA/2026-10-22", "yahoo",
            fetched_at="2026-10-22T22:00:00Z")  # fmt: skip
    _yahoo_window(y / "daily/2026-10-23/batch-000.parquet", [("AAA", "2020-01-07", 6.5)])
    _record(tmp_data, "yahoo/daily/2026-10-23/batch-000.parquet", "daily/2026-10-23/000", "yahoo",
            fetched_at="2026-10-23T22:00:00Z")  # fmt: skip
    assert closes() == [(date(2020, 1, 2), 5.0), (date(2020, 1, 3), 5.75), (date(2020, 1, 6), 6.0),
                        (date(2020, 1, 7), 6.5)]  # fmt: skip
    kinds = con.execute("select file_kind, count(*) from stg_yahoo.price group by 1 order by 1")
    assert kinds.fetchall() == [("history", 3), ("window", 1)]


def test_price_staging_holds_every_file_of_each_source(tmp_data):
    _yahoo(tmp_data.yahoo / "AAPL.parquet", [10.0, 11.0])
    _yahoo(tmp_data.yahoo / "panel" / "BRK-B.parquet", [300.0])
    _record(tmp_data, "yahoo/AAPL.parquet", "AAPL", "yahoo")
    _record(tmp_data, "yahoo/panel/BRK-B.parquet", "panel/BRK-B", "yahoo")
    t = tmp_data.tiingo
    for d, ticker in (("prices", "GONE"), ("listed_prices", "AAPL")):
        (t / d).mkdir(parents=True)
        csv = ("date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,"
               "divCash,splitFactor\n2020-01-02,5,5,5,5,10,5,5,5,5,10,0.0,1.0\n")  # fmt: skip
        (t / d / f"{ticker}.csv.gz").write_bytes(gzip.compress(csv.encode()))
        _record(tmp_data, f"tiingo/{d}/{ticker}.csv.gz", f"{d}/{ticker}", "tiingo")
    (t / "prices" / "NODATA.csv.gz").write_bytes(gzip.compress(b"[]"))  # Tiingo: no prices
    _record(tmp_data, "tiingo/prices/NODATA.csv.gz", "prices/NODATA", "tiingo")
    (t / "meta").mkdir()
    (t / "meta" / "GONE.json.gz").write_bytes(gzip.compress(json.dumps(
        {"ticker": "gone", "name": "Gone Corp", "exchangeCode": "NYSE",
         "startDate": "2010-01-04", "endDate": "2015-06-30"}).encode()))  # fmt: skip
    (t / "meta" / "NOPE.json.gz").write_bytes(gzip.compress(b'{"detail": "Not found."}'))
    (t / "supported_tickers.zip").write_bytes(
        _zip(
            {
                "supported_tickers.csv": (
                    "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
                    "GONE,NYSE,Stock,USD,2010-01-04,2015-06-30\nSPY,NYSE ARCA,ETF,USD,1993-01-29,\n"
                )
            }
        )
    )
    (t / "panel_search").mkdir()
    (t / "panel_search" / "k1.json.gz").write_bytes(gzip.compress(json.dumps(
        [{"ticker": "gone", "name": "Gone Corp", "assetType": "Stock", "isActive": False}]
    ).encode()))  # fmt: skip
    _record(
        tmp_data,
        "tiingo/panel_search/k1.json.gz",
        "panel_search/k1",
        "tiingo",
        "https://api.tiingo.com/tiingo/utilities/search?query=GONE+CORP&limit=10",
    )
    con = db.connect(tmp_data)
    assert prices.stage_yahoo(con, tmp_data, **QUIET) == {"history_files": 2, "window_files": 0,
                                                          "price": 3}  # fmt: skip
    assert con.execute(
        "select ticker, session, close, raw_file from stg_yahoo.price order by ticker, session"
    ).fetchall()[0] == ("AAPL", date(2020, 1, 2), 10.0, "yahoo/AAPL.parquet")
    counts = prices.stage_tiingo(con, tmp_data, **QUIET)
    assert counts == {"files": 2, "window_files": 0, "no_prices": 1, "price": 2, "meta": 2,
                      "listing": 2, "search": 1}  # fmt: skip
    meta = con.execute("select ticker, name, end_date from stg_tiingo.meta order by 1").fetchall()
    assert meta == [("GONE", "Gone Corp", date(2015, 6, 30)), ("NOPE", None, None)]
    assert con.execute("select query, ticker from stg_tiingo.search").fetchone() == (
        "GONE CORP",
        "gone",
    )


def test_market_staging_keeps_first_releases_and_sums_finra_facilities(tmp_data):
    tmp_data.fred.mkdir(parents=True)
    obs = {"observations": [
        {"date": "2020-01-01", "value": "257.9", "realtime_start": "2020-02-13"},
        {"date": "2020-02-01", "value": ".", "realtime_start": "2020-03-11"}]}  # fmt: skip
    (tmp_data.fred / "CPIAUCSL-first-2026-10-28.json").write_text(json.dumps(obs))
    _record(tmp_data, "fred/CPIAUCSL-first-2026-10-28.json", "CPIAUCSL-first-2026-10-28", "fred")
    tmp_data.cboe.mkdir(parents=True)
    (tmp_data.cboe / "VIX_History-2026-10-28.csv").write_text(
        "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2020,13.5,13.7,13.2,12.47\n"
    )
    _record(tmp_data, "cboe/VIX_History-2026-10-28.csv", "VIX_History-2026-10-28", "cboe")
    for facility, short in (("FNSQ", 30), ("FNYX", 20)):
        rel = f"finra/short_volume/{facility}/20200102.txt.gz"
        (tmp_data.raw / rel).parent.mkdir(parents=True)
        text = ("Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
                f"20200102|AAPL|{short}|0|100|Q\n")  # fmt: skip
        (tmp_data.raw / rel).write_bytes(gzip.compress(text.encode()))
        _record(tmp_data, rel, f"{facility}/20200102", "finra_short")
    tmp_data.french.mkdir(parents=True)
    sic = (Path(__file__).parent.parent / "fixtures" / "siccodes49.txt").read_text()
    (tmp_data.french / "Siccodes49.zip").write_bytes(_zip({"Siccodes49.txt": sic}))
    con = db.connect(tmp_data)
    counts = market.stage(con, tmp_data, **QUIET)
    assert counts["fred"] == 1 and counts["vix"] == 1 and counts["short_volume"] == 1
    assert counts["sic_industry"] > 0
    assert con.execute("select period, value, available from stg_market.fred").fetchone() == (
        date(2020, 1, 1),
        257.9,
        date(2020, 2, 13),
    )  # first release, published 13 Feb
    assert con.execute("select short_volume, total_volume, facilities "
                       "from stg_market.short_volume").fetchone() == (50.0, 200.0, 2)  # fmt: skip
    assert con.execute("select close from stg_market.vix").fetchone() == (12.47,)
