"""Layer 4, families E and F: short selling per row of `feature.row`, and market and macro values
per date.

- `feature.short`: FINRA short volume over total (off-exchange) volume for the month to the row's
  date (`short_ratio_1m`), the three months to it (`short_ratio_3m`), and the month's ratio minus
  that of the three months before it (`short_ratio_chg`). v1 used calendar months, which looks
  ahead from a mid-month row; trailing windows give the same at month-ends (V2-13). Window sums
  are differences of running totals.
- `feature.macro`: per date, values known at its close: the VIX and its change over a month,
  SPY's 63-day volatility, the market series of `sources.fred_market_series` (risk_params) and
  their changes over three months, CPI inflation over a year and unemployment with its change over
  three months (first releases only).
"""

import duckdb
import numpy as np
import pandas as pd

from sentinel import db
from sentinel.config import Paths, risk_params
from sentinel.features.price import ANNUAL, spy_returns

SHORT_FEATURES = ["short_ratio_1m", "short_ratio_3m", "short_ratio_chg"]


def macro_features(p: Paths) -> list[str]:
    series = risk_params(p)["sources"]["fred_market_series"]
    return ["vix", "vix_chg_1m", "spy_vol_63"] + [
        f"{s.lower()}{suffix}" for s in series for suffix in ("", "_chg_3m")
    ] + ["cpi_yoy", "unemployment", "unemployment_chg_3m"]  # fmt: skip


def build_short(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.short_volume"], "feature.short")
    lookbacks = {"a": "r.as_of", "b": "r.d1", "c": "r.d3", "e": "r.d4"}
    joins = "\n".join(
        f"asof left join _cum {k} on {k}.cik = r.cik and {k}.session <= {when}"
        for k, when in lookbacks.items()
    )
    sv = {k: f"coalesce({k}.cum_sv, 0)" for k in lookbacks}
    tv = {k: f"coalesce({k}.cum_tv, 0)" for k in lookbacks}

    def ratio(hi: str, lo: str) -> str:
        return f"({sv[hi]} - {sv[lo]}) / nullif({tv[hi]} - {tv[lo]}, 0)"

    with db.transaction(con):
        con.execute(
            """
            create or replace temp table _cum as
            select cik, session, sum(short_volume) over w as cum_sv,
                   sum(total_volume) over w as cum_tv
            from core.short_volume
            where cik in (select distinct cik from feature.row)
            window w as (partition by cik order by session rows unbounded preceding)
            """
        )
        con.execute(
            f"""
            create or replace table feature.short as
            with r as (
                select cik, as_of, cast(as_of - interval 1 month as DATE) as d1,
                       cast(as_of - interval 3 month as DATE) as d3,
                       cast(as_of - interval 4 month as DATE) as d4
                from feature.row
            )
            select r.cik, r.as_of, {ratio("a", "b")} as short_ratio_1m,
                   {ratio("a", "c")} as short_ratio_3m,
                   {ratio("a", "b")} - {ratio("b", "e")} as short_ratio_chg
            from r
            {joins}
            order by r.cik, r.as_of
            """
        )
        con.execute("drop table _cum")
    return {"short": db.count(con, "feature.short")}


def macro_table(dates: pd.Series, obs: pd.DataFrame, spy: pd.Series,
                market_series: list[str]) -> pd.DataFrame:  # fmt: skip
    """Family F for each date in `dates` (timestamps). `obs`: core.macro_observation (series,
    period, value, known_at as timestamps)."""
    t = pd.DataFrame({"as_of": dates.sort_values().unique()})

    def known(series: pd.DataFrame, at: pd.Series) -> np.ndarray:
        s = series.sort_values("known_at")
        m = pd.merge_asof(pd.DataFrame({"at": at}).reset_index(), s, left_on="at",
                          right_on="known_at").set_index("index")  # fmt: skip
        return m["value"].reindex(at.index).to_numpy()

    month, quarter = t["as_of"] - pd.DateOffset(months=1), t["as_of"] - pd.DateOffset(months=3)
    vix = obs[obs["series"] == "VIX"]
    t["vix"] = known(vix, t["as_of"])
    t["vix_chg_1m"] = t["vix"] - known(vix, month)
    spy_vol = spy.rolling(63, min_periods=40).std() * ANNUAL
    t["spy_vol_63"] = spy_vol.reindex(t["as_of"]).to_numpy()
    for s in market_series:
        series, name = obs[obs["series"] == s], s.lower()
        t[name] = known(series, t["as_of"])
        t[f"{name}_chg_3m"] = t[name] - known(series, quarter)
    cpi = obs[obs["series"] == "CPIAUCSL"]
    by_period = dict(zip(cpi["period"], cpi["value"], strict=True))
    latest = pd.merge_asof(t[["as_of"]], cpi.sort_values("known_at"), left_on="as_of",
                           right_on="known_at")  # fmt: skip
    year_ago = latest["period"] - pd.DateOffset(months=12)
    t["cpi_yoy"] = (latest["value"] / year_ago.map(by_period) - 1).to_numpy()
    un = obs[obs["series"] == "UNRATE"]
    t["unemployment"] = known(un, t["as_of"])
    t["unemployment_chg_3m"] = t["unemployment"] - known(un, quarter)
    return t


def build_macro(con: duckdb.DuckDBPyConnection, p: Paths, echo=print) -> dict:
    db.require(con, ["feature.row", "core.macro_observation", "stg_yahoo.price"], "feature.macro")
    market_series = risk_params(p)["sources"]["fred_market_series"]
    dates = pd.to_datetime(
        con.execute("select distinct as_of from feature.row").df()["as_of"]
    ).astype("datetime64[ns]")
    obs = con.execute(
        "select series, period, value, known_at from core.macro_observation "
        "where known_at is not null"
    ).df()
    for c in ("period", "known_at"):
        obs[c] = pd.to_datetime(obs[c]).astype("datetime64[ns]")
    t = macro_table(dates, obs, spy_returns(con), market_series)
    t["as_of"] = t["as_of"].dt.date
    with db.transaction(con):
        con.register("_macro", t[["as_of", *macro_features(p)]])
        con.execute("create or replace table feature.macro as select * from _macro order by as_of")
        con.unregister("_macro")
    return {"macro_dates": db.count(con, "feature.macro")}
