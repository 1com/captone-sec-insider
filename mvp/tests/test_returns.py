from datetime import date

import numpy as np
import pandas as pd
import pytest

from mvp.config import PilotViolation, load_settings
from mvp.pipeline import prices as px
from mvp.pipeline.returns import abdi_ranaldo, event_returns

S = load_settings()
DAYS = pd.bdate_range("2005-01-03", "2007-12-31")


def frame(close: np.ndarray, splits=None, volume=1_000_000.0) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": volume,
            "splits": 0.0,
        },
        index=DAYS,
    )
    if splits:
        for day, ratio in splits.items():
            df.loc[pd.Timestamp(day), "splits"] = ratio
    s = df["splits"].replace(0.0, 1.0)
    df["unadj_close"] = df["close"] * s[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    return df


def event(ticker="XYZ", day=date(2006, 6, 15), group="A"):
    return pd.DataFrame(
        [
            {
                "event_id": f"1:{group}:{day}",
                "issuer_cik": "1",
                "group": group,
                "signal_date": day,
                "ticker": ticker,
            }
        ]
    )


def flat():
    return frame(np.full(len(DAYS), 100.0))


def test_abdi_ranaldo_is_zero_for_constant_prices():
    c = np.full(25, 10.0)
    assert abdi_ranaldo(c, c, c) == 0.0


def test_entry_at_next_open_and_abnormal_return():
    close = np.full(len(DAYS), 50.0)
    start = DAYS.get_loc(pd.Timestamp("2006-06-16"))  # entry day: the session after T
    close[start:] = 50.0 * 1.01 ** np.arange(1, len(DAYS) - start + 1)
    stock = frame(close)
    stock["open"] = stock["close"].shift(1).fillna(50.0)  # open at the previous close
    ret, paths, ks = event_returns(event(), {"XYZ": stock, "IWM": flat(), "SPY": flat()}, S)
    row = ret.iloc[0]
    assert row["entry_date"] == date(2006, 6, 16)
    # five sessions held: from the entry open to the 5th close = 1.01^5 - 1; the benchmark is flat
    assert row["gross_5_iwm"] == pytest.approx(1.01**5 - 1, rel=1e-9)
    assert row["net_5_iwm"] == pytest.approx(row["gross_5_iwm"] - row["cost"])
    assert paths["IWM"][0, list(ks).index(0)] == pytest.approx(0.01, rel=1e-9)


def test_events_after_the_pilot_sample_raise():
    with pytest.raises(PilotViolation):
        event_returns(event(day=date(2012, 1, 3)), {"XYZ": flat(), "IWM": flat(), "SPY": flat()}, S)


def test_as_traded_price_drives_the_floor():
    # $10 today after a 1-for-10 reverse split in 2007 means $1 as traded in 2006: fails $2
    stock = frame(np.full(len(DAYS), 10.0), splits={"2007-03-01": 0.1})
    ret, _, _ = event_returns(event(), {"XYZ": stock, "IWM": flat(), "SPY": flat()}, S)
    assert ret.iloc[0]["unadj_close_t"] == pytest.approx(1.0)
    assert not ret.iloc[0]["passes_floors"]


def test_unpriced_events_are_kept_and_explained():
    ret, _, _ = event_returns(event(ticker=None), {"IWM": flat(), "SPY": flat()}, S)
    assert not ret.iloc[0]["priced"]
    assert "Yahoo" in ret.iloc[0]["reason"]


def test_unadjusting_from_split_history(tmp_path, monkeypatch):
    monkeypatch.setattr(px, "YAHOO", tmp_path)
    raw = frame(np.full(len(DAYS), 20.0), splits={"2006-01-03": 2.0})
    raw.drop(columns=["unadj_close"]).to_parquet(tmp_path / "ABC.parquet")
    df = px.load("ABC")
    assert df.loc["2005-12-30", "unadj_close"] == pytest.approx(40.0)  # before a 2:1 split
    assert df.loc["2006-01-03", "unadj_close"] == pytest.approx(20.0)
