import io
import zipfile
from datetime import date

from sentinel.provisional.tiingo_list import match, normalise, parse_supported

EXCHANGES = ["NYSE", "NASDAQ", "NYSE MKT", "AMEX", "NYSE ARCA"]


def tiingo_zip(rows):
    lines = ["ticker,exchange,assetType,priceCurrency,startDate,endDate"]
    lines += [",".join(r) for r in rows]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("supported_tickers.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


INDEX = parse_supported(
    tiingo_zip(
        [
            ("BRK-B", "NYSE", "Stock", "USD", "1996-05-09", "2026-10-21"),
            ("OLD", "NASDAQ", "Stock", "USD", "2001-01-02", "2009-06-30"),
            ("OLD", "NYSE", "Stock", "USD", "2015-03-02", "2020-11-30"),
            ("GONE", "NASDAQ", "Stock", "USD", "2005-01-03", "2012-02-01"),
            ("FX", "LSE", "Stock", "GBP", "2010-01-04", "2024-01-02"),
            ("ETF1", "NYSE ARCA", "ETF", "USD", "2010-01-04", "2024-01-02"),
        ]
    ),
    EXCHANGES,
)


def test_normalise():
    assert normalise(" brk.b ") == "BRK-B"
    assert normalise("ABC/WS") == "ABC-WS"
    assert normalise("NONE") is None
    assert normalise("n/a") is None
    assert normalise("") is None
    assert normalise("[NONE]") is None
    assert normalise("N/A/") is None
    assert normalise("$XYZ ") == "XYZ"


def test_bankruptcy_q_ticker_matches_when_plain_ticker_is_reused():
    index = parse_supported(
        tiingo_zip(
            [
                ("TWOU", "NASDAQ", "Stock", "USD", "2026-02-06", "2026-10-21"),  # new company
                ("TWOUQ", "PINK", "Stock", "USD", "2014-03-28", "2026-10-21"),  # 2U's full history
            ]
        ),
        EXCHANGES + ["PINK"],
    )
    assert match(index, ["TWOU"], date(2019, 8, 9), date(2022, 2, 14)) == ("matched", "TWOUQ")


def test_dot_class_ticker_matches():
    assert match(INDEX, ["BRK.B"], date(2018, 1, 1), date(2019, 1, 1)) == ("matched", "BRK-B")


def test_reused_ticker_matches_the_overlapping_listing():
    assert match(INDEX, ["OLD"], date(2018, 5, 1), date(2018, 9, 1)) == ("matched", "OLD")


def test_ticker_outside_span_is_ticker_only():
    assert match(INDEX, ["GONE"], date(2016, 1, 4), date(2019, 1, 1)) == ("ticker_only", None)


def test_absent_and_filtered_rows_are_unmatched():
    assert match(INDEX, ["NOPE"], date(2016, 1, 4), date(2019, 1, 1)) == ("unmatched", None)
    assert match(INDEX, ["FX"], date(2016, 1, 4), date(2019, 1, 1)) == ("unmatched", None)
    assert match(INDEX, ["ETF1"], date(2016, 1, 4), date(2019, 1, 1)) == ("unmatched", None)


def test_disabled_check_is_not_checked():
    assert match(None, ["BRK.B"], date(2018, 1, 1), date(2019, 1, 1)) == ("not_checked", None)


def test_parsing_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parse_supported(
        tiingo_zip([("A", "NYSE", "Stock", "USD", "2010-01-04", "2024-01-02")]), EXCHANGES
    )
    assert list(tmp_path.iterdir()) == []
