"""Layer 4, family B: financial statements per row of `feature.row` (v1's definitions), from
`core.financial_fact` and `core.shares_outstanding`, each value usable from its `known_at`.

Each item's value is that of the latest period known at the row's date; an instant older than 456
days, an annual flow older than 548 days or a latest net income older than 456 days counts as
missing. Annual flows are periods of 330–400 days and carry the value a year earlier as known at
that moment (for growth). A share count is put in the row date's shares with the price series'
split factors, so a split after the count does not distort market value (V2-13).

`log_market_cap`, `book_to_market`, `leverage` (liabilities, else assets − equity, over assets),
`cash_to_assets`, `cash_runway_years` (cash over operating cash burn, capped at 10),
`loss_making` (latest net income below zero), `revenue_growth` (annual, against a year earlier),
`gross_margin`, `rd_intensity`, `interest_coverage`, `current_ratio`, `receivables_to_assets`,
`sbc_to_revenue`, `share_growth_12m` (split-adjusted shares against the count known a year
earlier), `issue_proceeds_to_assets`, `months_since_report` (since the last periodic report: 10-K,
10-Q, 20-F, 40-F and amendments).
"""

import duckdb
import numpy as np
import pandas as pd

from sentinel import db
from sentinel.config import Paths

BATCH = 1000  # companies per batch
INSTANT = ["shares_outstanding", "equity", "assets", "liabilities", "cash", "current_assets",
           "current_liabilities", "receivables", "long_term_debt"]  # fmt: skip
FLOW = ["revenue", "gross_profit", "operating_income", "operating_cash_flow", "capex",
        "rd_expense", "interest_expense", "stock_compensation", "stock_issue_proceeds",
        "dividends_paid", "net_income"]  # fmt: skip
ANNUAL_DAYS = (330, 400)
STALE_DAYS = {"instant": 456, "annual": 548, "latest": 456}  # older values count as missing
REPORT_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A")
FUND_FEATURES = [
    "log_market_cap", "book_to_market", "leverage", "cash_to_assets", "cash_runway_years",
    "loss_making", "revenue_growth", "gross_margin", "rd_intensity", "interest_coverage",
    "current_ratio", "receivables_to_assets", "sbc_to_revenue", "share_growth_12m",
    "issue_proceeds_to_assets", "months_since_report",
]  # fmt: skip


def fact_steps(facts: pd.DataFrame) -> pd.DataFrame:
    """What was known when: for each company and item, one row each time a filing brought a newer
    period (`known_at`, its `period_end`, `value`, and for annual items the value one year earlier
    as known at that moment). Items: instants, annual flows, and `net_income_latest` (any period,
    the shortest when several end on the same day). `facts`: cik, concept, period_start,
    period_end, value, filed, known_at (timestamps)."""
    f = facts.copy()
    f["days"] = (f["period_end"] - f["period_start"]).dt.days
    parts = [f[f["concept"].isin(INSTANT)].assign(kind="instant")]
    annual = f[f["concept"].isin(FLOW) & f["days"].between(*ANNUAL_DAYS)]
    parts.append(annual.assign(kind="annual"))
    latest = f[(f["concept"] == "net_income") & f["days"].notna()]
    latest = latest.sort_values(["days", "filed"]).drop_duplicates(["cik", "period_end", "filed"])
    parts.append(latest.assign(concept="net_income_latest", kind="latest"))
    rows = []
    for (cik, concept, kind), g in pd.concat(parts).groupby(["cik", "concept", "kind"]):
        g = g.sort_values(["filed", "period_end"])
        best, seen = None, []
        for known, end, value in zip(g["known_at"], g["period_end"], g["value"], strict=True):
            seen.append((end, value))
            if best is None or end > best:
                best = end
                prev = None
                if kind == "annual":
                    year_ago = [v for e, v in seen if 330 <= (end - e).days <= 400]
                    prev = year_ago[-1] if year_ago else None
                rows.append((cik, concept, kind, known, end, value, prev))
    return pd.DataFrame(rows, columns=["cik", "concept", "kind", "known_at", "period_end",
                                       "value", "prev_value"])  # fmt: skip


def _asof(rows: pd.DataFrame, steps: pd.DataFrame, at: str, concept: str) -> pd.DataFrame:
    """For each row, the step of `concept` known at its `at` date, or nothing if stale."""
    s = steps[steps["concept"] == concept].sort_values("known_at")
    left = rows[["cik", at]].reset_index().sort_values(at)
    m = pd.merge_asof(left, s, left_on=at, right_on="known_at", by="cik")
    if len(s):
        stale = (m[at] - m["period_end"]).dt.days > STALE_DAYS[s["kind"].iloc[0]]
        m.loc[stale, ["value", "prev_value"]] = np.nan
    return m.set_index("index").reindex(rows.index)


def _split_at(rows: pd.DataFrame, splits: pd.DataFrame, when: pd.Series) -> np.ndarray:
    """Each row's company's `cum_split_after` on the last price day on or before `when`, or for
    a date before its prices start (a count from before listing), on its first price day."""
    left = pd.DataFrame({"cik": rows["cik"], "when": when}).reset_index()
    left = left[left["when"].notna()].sort_values("when")
    right = splits.sort_values("session")
    back, ahead = (pd.merge_asof(left, right, left_on="when", right_on="session", by="cik",
                                 direction=d) for d in ("backward", "forward"))  # fmt: skip
    value = back["cum_split_after"].fillna(ahead["cum_split_after"])
    return pd.Series(value.to_numpy(), index=back["index"]).reindex(rows.index).to_numpy()


def fundamentals(rows: pd.DataFrame, steps: pd.DataFrame, reports: pd.DataFrame,
                 splits: pd.DataFrame) -> pd.DataFrame:  # fmt: skip
    """Family B for each row (`cik`, `as_of`, `close`, `cum_split_after`). `reports`: (`cik`,
    `known_at`) of periodic reports; `splits`: (`cik`, `session`, `cum_split_after`) daily."""
    v = {c: _asof(rows, steps, "as_of", c)["value"] for c in INSTANT + FLOW}
    v["net_income_latest"] = _asof(rows, steps, "as_of", "net_income_latest")["value"]
    revenue_prev = _asof(rows, steps, "as_of", "revenue")["prev_value"]
    shares_now = _asof(rows, steps, "as_of", "shares_outstanding")
    back = rows.assign(year_ago=rows["as_of"] - pd.Timedelta(days=365))
    shares_then = _asof(back, steps, "year_ago", "shares_outstanding")
    split_now = rows["cum_split_after"].to_numpy(dtype=float)

    def in_row_shares(step: pd.DataFrame) -> pd.Series:
        """A count in the shares of the row's date: × the split factor at its period end ÷ now."""
        at_count = _split_at(rows, splits, step["period_end"])
        return step["value"] * at_count / np.where(split_now > 0, split_now, np.nan)

    shares = in_row_shares(shares_now)
    out = pd.DataFrame(index=rows.index)
    cap = rows["close"] * shares
    out["log_market_cap"] = np.log(cap.where(cap > 0))
    out["book_to_market"] = v["equity"] / cap.where(cap > 0)
    assets = v["assets"].where(v["assets"] > 0)
    liabilities = v["liabilities"].fillna(v["assets"] - v["equity"])
    out["leverage"] = liabilities / assets
    out["cash_to_assets"] = v["cash"] / assets
    burn = -v["operating_cash_flow"].where(v["operating_cash_flow"] < 0)
    out["cash_runway_years"] = (v["cash"] / burn).clip(upper=10)
    out["loss_making"] = (
        (v["net_income_latest"] < 0).astype(float).where(v["net_income_latest"].notna())
    )
    revenue = v["revenue"].where(v["revenue"] > 0)
    out["revenue_growth"] = (revenue / revenue_prev.where(revenue_prev > 0) - 1).clip(-1, 10)
    out["gross_margin"] = (v["gross_profit"] / revenue).clip(-10, 1)
    out["rd_intensity"] = (v["rd_expense"] / revenue).clip(upper=10)
    interest = v["interest_expense"].where(v["interest_expense"] > 0)
    out["interest_coverage"] = (v["operating_income"] / interest).clip(-100, 100)
    out["current_ratio"] = (
        v["current_assets"] / v["current_liabilities"].where(v["current_liabilities"] > 0)
    ).clip(upper=50)
    out["receivables_to_assets"] = v["receivables"] / assets
    out["sbc_to_revenue"] = (v["stock_compensation"] / revenue).clip(upper=10)
    then = in_row_shares(shares_then)
    out["share_growth_12m"] = (shares / then.where(then > 0) - 1).clip(-1, 20)
    out["issue_proceeds_to_assets"] = v["stock_issue_proceeds"] / assets
    left = rows[["cik", "as_of"]].reset_index().sort_values("as_of")
    last = pd.merge_asof(left, reports.sort_values("known_at"), left_on="as_of",
                         right_on="known_at", by="cik").set_index("index")  # fmt: skip
    out["months_since_report"] = ((last["as_of"] - last["filing_date"]).dt.days / 30.44).reindex(
        rows.index
    )
    out["market_cap"] = cap  # for the insider family's net buying against market value
    out["shares_outstanding"] = shares
    return out


def _timestamps(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        frame[c] = pd.to_datetime(frame[c]).astype("datetime64[ns]")
    return frame


def build_fundamentals(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.price_daily", "core.financial_fact",
                     "core.shares_outstanding", "core.filing"], "feature.fundamental")  # fmt: skip
    ciks = [r[0] for r in con.execute("select distinct cik from feature.row order by 1").fetchall()]
    items = ", ".join(f"'{c}'" for c in INSTANT + FLOW if c != "shares_outstanding")
    extra = ["market_cap", "shares_outstanding"]
    with db.transaction(con):
        con.execute(
            "create or replace table feature.fundamental (cik VARCHAR, as_of DATE, "
            + ", ".join(f"{c} DOUBLE" for c in FUND_FEATURES + extra)
            + ")"
        )
        for i in range(0, len(ciks), BATCH):
            args = [ciks[i : i + BATCH]]
            within = "cik in (select unnest(?::VARCHAR[]))"
            rows = con.execute(
                "select r.cik, r.as_of, d.close, d.cum_split_after from feature.row r "
                "join core.price_daily d on d.cik = r.cik and d.session = r.as_of "
                f"where r.{within} order by r.cik, r.as_of",
                args,
            ).df()
            facts = con.execute(
                f"""
                select cik, item as concept, period_start, period_end, value, filed, known_at
                from core.financial_fact where item in ({items}) and {within}
                union all
                select cik, 'shares_outstanding', null, as_of, shares, filed, known_at
                from core.shares_outstanding where {within}
                """,
                args * 2,
            ).df()
            reports = con.execute(
                f"select cik, filing_date, known_at from core.filing where form in {REPORT_FORMS} "
                f"and known_at is not null and {within}",
                args,
            ).df()
            splits = con.execute(
                f"select cik, session, cum_split_after from core.price_daily where {within}", args
            ).df()
            _timestamps(rows, ["as_of"])
            _timestamps(facts, ["period_start", "period_end", "filed", "known_at"])
            _timestamps(reports, ["filing_date", "known_at"])
            _timestamps(splits, ["session"])
            out = fundamentals(rows, fact_steps(facts), reports, splits)
            out.insert(0, "as_of", rows["as_of"].dt.date)
            out.insert(0, "cik", rows["cik"])
            con.register("_chunk", out[["cik", "as_of", *FUND_FEATURES, *extra]])
            con.execute("insert into feature.fundamental select * from _chunk")
            con.unregister("_chunk")
            done = min(i + BATCH, len(ciks))
            if done % 4000 < BATCH or done == len(ciks):
                echo(f"  financial-statement features: {done:,}/{len(ciks):,} companies")
    return {"fundamental": db.count(con, "feature.fundamental")}
