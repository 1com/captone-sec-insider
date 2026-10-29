"""Layer 4, family C: company events per row of `feature.row`, from `core.filing` (filings known
by the row's date, filed in the 3 or 12 months before it) and `core.results_release` (v1's
definitions).

- `n_<event>_3m`, `n_<event>_12m` for the 8-K items and forms in `EVENTS`; `n_8k_12m`.
- Offerings count share sales only: registrations (S-1, S-3, F-1, F-3, with amendments) and final
  prospectuses 424B1, 424B3, 424B4, and 424B5 unless a pricing term sheet (FWP) came in the
  `TERM_SHEET_DAYS` before it, as with large companies' bond sales (424B2: banks' structured
  notes).
- `days_since_results`: days since the last results release known at the row's date (its report
  filed, `confirmed`, before that day); `days_to_next_results`: the last release plus the median of
  the company's previous four gaps between releases, minus the row's date (negative when overdue).
"""

import duckdb
import numpy as np
import pandas as pd

from sentinel import db
from sentinel.config import Paths


def _item(code: str) -> str:
    return f"list_contains(string_split(coalesce(f.items, ''), ','), '{code}')"


EQUITY_FORMS = ("S-1", "S-1/A", "F-1", "F-1/A", "S-3", "S-3/A", "F-3", "F-3/A",
                "424B1", "424B3", "424B4")  # fmt: skip
TERM_SHEET_DAYS = 5
EVENTS = {
    "agreement": _item("1.01"), "acquisition": _item("2.01"), "bankruptcy": _item("1.03"),
    "delisting_notice": _item("3.01"), "unregistered_sale": _item("3.02"),
    "auditor_change": _item("4.01"), "restatement": _item("4.02"), "exec_change": _item("5.02"),
    "late_filing": "f.form in ('NT 10-K', 'NT 10-Q', 'NT 10-K/A', 'NT 10-Q/A')",
    "offering": f"(f.form in {EQUITY_FORMS} or (f.form = '424B5' and not f.debt_deal))",
    "shelf_effective": "f.form = 'EFFECT'",
    "activist": "f.form in ('SC 13D', 'SC 13D/A')",
}  # fmt: skip
EVENT_FEATURES = [f"n_{k}_{w}" for k in EVENTS for w in ("3m", "12m")] + [
    "n_8k_12m", "days_since_results", "days_to_next_results"]  # fmt: skip
NOT_8K = ("late_filing", "offering", "shelf_effective", "activist")
EIGHT_K_FEATURES = [c for c in EVENT_FEATURES if not any(c.startswith(f"n_{k}_") for k in NOT_8K)]


def results_timing(rows: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """`days_since_results` and `days_to_next_results` for `rows` (cik, as_of as timestamps), from
    `results` (cik, filing_date, confirmed as timestamps). Missing before a company's first known
    release."""
    by_cik = {
        cik: (g["filing_date"].to_numpy(), g["confirmed"].to_numpy())
        for cik, g in results.sort_values("filing_date").groupby("cik")
    }
    since, to_next = [], []
    for cik, t in zip(rows["cik"], rows["as_of"].to_numpy(), strict=True):
        filed, confirmed = by_cik.get(cik, (None, None))
        dates = None if filed is None else filed[confirmed < t]
        k = 0 if dates is None else len(dates)
        if k == 0:
            since.append(np.nan)
            to_next.append(np.nan)
            continue
        last = dates[k - 1]
        since.append((t - last) / np.timedelta64(1, "D"))
        gaps = np.diff(dates[max(0, k - 5) : k]) / np.timedelta64(1, "D")
        to_next.append(
            ((last - t) / np.timedelta64(1, "D")) + np.median(gaps) if len(gaps) else np.nan
        )
    return rows.assign(days_since_results=since, days_to_next_results=to_next)


def build_events(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.filing", "core.results_release"], "feature.event")
    counts = ",\n".join(
        f"count(*) filter (where {cond} and f.filing_date > r.as_of - interval 3 month) "
        f"as n_{k}_3m,\ncount(*) filter (where {cond}) as n_{k}_12m"
        for k, cond in EVENTS.items()
    )
    with db.transaction(con):
        con.execute(
            f"""
            create or replace temp table _filing as
            select f.cik, f.form, f.items, f.filing_date, f.known_at,
                   f.form = '424B5' and exists (
                       select 1 from core.filing x
                       where x.cik = f.cik and x.form = 'FWP'
                         and x.filing_date between f.filing_date - interval {TERM_SHEET_DAYS} day
                                               and f.filing_date) as debt_deal
            from core.filing f
            where f.cik in (select distinct cik from feature.row) and f.known_at is not null
            """
        )
        con.execute(
            f"""
            create or replace temp table _counts as
            select r.cik, r.as_of, {counts},
                   count(*) filter (where f.form like '8-K%') as n_8k_12m
            from feature.row r
            left join _filing f on f.cik = r.cik and f.known_at <= r.as_of
                 and f.filing_date > r.as_of - interval 12 month
            group by r.cik, r.as_of
            """
        )
        rows = con.execute("select cik, as_of from feature.row").df()
        results = con.execute(
            "select cik, filing_date, confirmed from core.results_release "
            "where cik in (select distinct cik from feature.row)"
        ).df()
        for frame, cols in ((rows, ["as_of"]), (results, ["filing_date", "confirmed"])):
            for c in cols:
                frame[c] = pd.to_datetime(frame[c]).astype("datetime64[ns]")
        timing = results_timing(rows, results)
        timing["as_of"] = timing["as_of"].dt.date
        con.register("_timing", timing)
        con.execute(
            f"""
            create or replace table feature.event as
            select c.cik, c.as_of, {", ".join(f"c.{x}" for x in EVENT_FEATURES[:-2])},
                   t.days_since_results, t.days_to_next_results
            from _counts c left join _timing t using (cik, as_of)
            order by c.cik, c.as_of
            """
        )
        con.unregister("_timing")
        con.execute("drop table _filing")
        con.execute("drop table _counts")
    return {"event": db.count(con, "feature.event")}
