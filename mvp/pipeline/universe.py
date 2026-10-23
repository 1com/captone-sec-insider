"""Which events and companies the MVP uses, and which ticker prices each company.

Events are feature 001's provisional events (pilot rules). A company is "listed today" when its CIK
is in the latest SEC ticker snapshot (research R1); only listed companies can be priced from Yahoo.
"""

import re
from datetime import date

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from mvp.config import SENTINEL, Settings
from sentinel.ingest.sec_reference import latest_snapshot, load_snapshot
from sentinel.provisional.candidates import issuer_info
from sentinel.provisional.tiingo_list import normalise

EVENTS_FILE = SENTINEL.provisional / "events_PROVISIONAL.parquet"
SCRATCH_DB = SENTINEL.provisional / "provisional_PROVISIONAL.duckdb"
GROUP_NAMES = {"A": "Cluster", "B1": "Solo CEO/CFO"}
NON_COMMON = re.compile(r"-(P[A-Z]?|WS|W|U|R|RT)$")


def choose_ticker(
    listings: list[tuple[str, str | None]], last_reported: str | None
) -> tuple[str, str | None] | None:
    """Pick the common-stock ticker among a company's SEC listings (research R3).

    Prefer the ticker the company last reported on Form 4, then a ticker without a class or
    security suffix (shortest first), then anything left.
    """
    clean = [(normalise(t), x) for t, x in listings if normalise(t)]
    # Preferred shares, warrants, units and rights are not the common stock: never price them.
    clean = [(t, x) for t, x in clean if not NON_COMMON.search(t)]
    if not clean:
        return None
    wanted = normalise(last_reported)
    for ticker, exchange in clean:
        if ticker == wanted:
            return ticker, exchange
    plain = sorted((t for t in clean if "-" not in t[0]), key=lambda t: (len(t[0]), t[0]))
    return plain[0] if plain else clean[0]


def load_events() -> pd.DataFrame:
    ev = pq.read_table(EVENTS_FILE).to_pandas()
    ev = ev.drop(columns=["status", "in_labelled_window"], errors="ignore")
    ev["signal_date"] = pd.to_datetime(ev["signal_date"]).dt.date
    ev["event_id"] = ev["issuer_cik"] + ":" + ev["group"] + ":" + ev["signal_date"].astype(str)
    ev["member_accessions"] = ev["member_accessions"].apply(list)
    return ev


def build_universe(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (events, companies). Events carry sample, listed flag and ticker."""
    events = load_events()
    con = duckdb.connect(str(SCRATCH_DB), read_only=True)
    info = issuer_info(con)
    con.close()
    snap = load_snapshot(latest_snapshot(SENTINEL))

    rows = []
    for cik in sorted(set(events["issuer_cik"]), key=int):
        inf = info.get(cik)
        pick = choose_ticker(snap.get(cik, []), inf.last_ticker if inf else None)
        rows.append(
            {
                "issuer_cik": cik,
                "name": (inf.name if inf else "") or f"CIK {cik}",
                "last_reported_ticker": inf.last_ticker if inf else "",
                "listed": cik in snap,
                "ticker": pick[0] if pick else None,
                "exchange": pick[1] if pick else None,
            }
        )
    companies = pd.DataFrame(rows)

    def sample(d: date) -> str:
        if settings.pilot_start <= d <= settings.pilot_end:
            return "pilot"
        if settings.recent_start <= d <= settings.recent_end:
            return "recent"
        return "other"

    events["sample"] = events["signal_date"].map(sample)
    events = events.merge(
        companies[["issuer_cik", "name", "listed", "ticker", "exchange"]],
        on="issuer_cik",
        how="left",
    )
    events["group_name"] = events["group"].map(GROUP_NAMES)
    return events, companies


def tickers_to_price(events: pd.DataFrame) -> list[str]:
    wanted = events[events["sample"].isin(["pilot", "recent"]) & events["listed"]]
    return sorted(set(wanted["ticker"].dropna())) + ["IWM", "SPY"]
