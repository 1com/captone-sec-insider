"""The validation round (specs/022-validation): seven checks of values that look normal but may be
wrong, each returning its cases from the build database (read-only), sorted so that named
examples are picked the same way on every run; and `edgar_text`, an SEC document's text for
evidence. The checks may look at later data to *find* a problem; a rule proposed from them must
work with what was known at the time (constitution I).
"""

import html
import re

import duckdb
import httpx
import numpy as np
import pandas as pd

from sentinel import config
from sentinel.labels.risk import share_steps

DEV_END = "2022-12-31"


def price_mismatch_causes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Check 1. Per company where Yahoo and Tiingo disagree on daily returns (`core.price_check`
    verdict `mismatch`): shared days, the median ratio of the two closes, the share of days whose
    closes agree within 2%, the chosen source, and the likely cause."""
    m = con.execute(
        """
        with p as (select * from core.price_check where verdict = 'mismatch'),
        j as (select p.cik, y.close / t.close as ratio
              from p join stg_yahoo.price y on y.ticker = p.yahoo_ticker
              join stg_tiingo.price t on t.ticker = p.tiingo_ticker and t.session = y.session
              where y.close > 0 and t.close > 0)
        select p.cik, p.yahoo_ticker, p.tiingo_ticker, p.differ_share, count(j.ratio) as days,
               median(j.ratio) as close_ratio,
               avg(case when abs(j.ratio - 1) < 0.02 then 1.0 else 0.0 end) as same_close,
               c.source as chosen
        from p left join j using (cik) left join core.price_choice c using (cik)
        group by all order by p.cik
        """
    ).df()
    whole = m["close_ratio"].where(m["close_ratio"] >= 1, 1 / m["close_ratio"])
    m["cause"] = np.select(
        [m["days"] == 0, m["same_close"] >= 0.9,
         (whole >= 1.9) & ((whole - whole.round()).abs() <= 0.05 * whole), m["same_close"] < 0.2],
        ["no shared closes", "closes agree: the adjustment differs",
         "steady whole-number ratio: a split or unit in one source",
         "closes apart on most days: possibly another stock"],
        "partly: differences in some periods",
    )  # fmt: skip
    return m


def extreme_returns(con: duckdb.DuckDBPyConnection, above: float = 10.0) -> pd.DataFrame:
    """Check 2. Month-end rows (to 2022) with a one-month return above `above` (+1,000%): the
    biggest one-day jump in that month, and whether either source recorded a split within five
    days of it."""
    return con.execute(
        f"""
        with r as (select cik, as_of, ret_1m, close, eligible_volatility from feature.snapshot
                   where month_end and as_of <= DATE '{DEV_END}' and ret_1m > {above}),
        d as (select p.cik, p.session, p.ticker, p.adj_close / lag(p.adj_close) over w as jump
              from core.price_daily p where p.cik in (select cik from r)
              window w as (partition by p.cik order by p.session)),
        top as (select r.*, d.session as jump_day, d.ticker, d.jump
                from r join d on d.cik = r.cik
                 and d.session between r.as_of - interval 1 month and r.as_of
                qualify row_number() over (partition by r.cik, r.as_of order by d.jump desc) = 1)
        select top.*,
               exists (select 1 from stg_yahoo.price y where y.ticker = top.ticker
                       and y.split_ratio not in (0, 1)
                       and y.session between top.jump_day - 5 and top.jump_day + 5) as yahoo_split,
               exists (select 1 from stg_tiingo.price t where t.ticker = top.ticker
                       and t.split_factor not in (0, 1)
                       and t.session between top.jump_day - 5 and top.jump_day + 5) as tiingo_split
        from top order by ret_1m desc
        """
    ).df()


def split_dilution(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Check 3. Dilution answers of 1 whose two share counts (as `label.dilution` picks them: the
    last filed by the month-end, the last filed within the window) straddle a split in the price
    series: the raw count ratio, the split factor applied, and whether the increase is the split
    itself (adjusted ratio within 10% of the factor or its inverse, or a raw count unchanged)."""
    rows = con.execute(
        f"select cik, as_of, window_end from label.dilution "
        f"where dilution = 1 and as_of <= DATE '{DEV_END}'"
    ).df()
    shares = con.execute(
        "select cik, as_of as period_end, shares as value, filed from core.shares_outstanding "
        "where cik in (select distinct cik from label.dilution where dilution = 1)"
    ).df()
    steps = share_steps(shares)
    split = con.execute(
        "select s.cik, s.as_of as period_end, p.cum_split_after as cum "
        "from core.shares_outstanding s "
        "asof left join core.price_daily p on p.cik = s.cik and p.session <= s.as_of"
    ).df()
    steps = steps.merge(split, on=["cik", "period_end"], how="left")
    out = []
    by = {c: g.sort_values("filed") for c, g in steps.groupby("cik")}
    for cik, as_of, end in rows.itertuples(index=False):
        g = by.get(cik)
        if g is None:
            continue
        filed = g["filed"].to_numpy(dtype="datetime64[ns]")
        i0 = np.searchsorted(filed, np.datetime64(pd.Timestamp(as_of)), side="right") - 1
        i1 = np.searchsorted(filed, np.datetime64(pd.Timestamp(end)), side="right") - 1
        if i0 < 0 or i1 <= i0:
            continue
        c0, c1 = g["value"].iloc[i0], g["value"].iloc[i1]
        f = g["cum"].iloc[i0] / g["cum"].iloc[i1]
        if not np.isfinite(f) or abs(f - 1) < 1e-9:
            continue  # no split between the two counts
        adjusted = c1 / (c0 * f)
        out.append({"cik": cik, "as_of": as_of, "count_before": c0, "count_after": c1,
                    "split_factor": f, "raw_ratio": c1 / c0,
                    "adjusted_ratio": adjusted})  # fmt: skip
    t = pd.DataFrame(out)
    if t.empty:
        return t
    near = lambda x, y: (x / y - 1).abs() <= 0.1  # noqa: E731
    t["split_read_as_dilution"] = (
        near(t["adjusted_ratio"], t["split_factor"])
        | near(t["adjusted_ratio"], 1 / t["split_factor"])
        | near(t["raw_ratio"], pd.Series(1.0, index=t.index))
    )
    return t.sort_values(["split_read_as_dilution", "cik", "as_of"], ascending=[False, True, True])


def first_count_outliers(con: duckdb.DuckDBPyConnection, far: float = 100.0) -> pd.DataFrame:
    """Check 4. Companies whose first accepted share count is `far` times or more away from the
    median of their next three (the typo rule cannot judge a first count)."""
    return con.execute(
        f"""
        with s as (select *, row_number() over (partition by cik order by known_at, as_of) as k
                   from core.shares_outstanding),
        f as (select a.cik, a.as_of, a.shares as first_count, a.source,
                     median(b.shares) as next_three
              from s a join s b on b.cik = a.cik and b.k between 2 and 4
              where a.k = 1 group by all)
        select *, first_count / next_three as ratio from f
        where first_count >= {far} * next_three or first_count * {far} <= next_three
        order by greatest(ratio, 1 / ratio) desc
        """
    ).df()


def crowded_releases(con: duckdb.DuckDBPyConnection, at_least: int = 5) -> pd.DataFrame:
    """Check 5. Company-years (2010–2022) with `at_least` results releases or more, with the
    shortest gap between two releases and the dates."""
    return con.execute(
        f"""
        with r as (select cik, filing_date, year(filing_date) as y,
                          filing_date - lag(filing_date) over (partition by cik
                                                               order by filing_date) as gap
                   from core.results_release where confirmed is not null)
        select cik, y as year, count(*) as releases, min(gap) as shortest_gap_days,
               list(filing_date order by filing_date) as dates
        from r where y between 2010 and 2022 group by cik, y having count(*) >= {at_least}
        order by shortest_gap_days, cik
        """
    ).df()


def tiingo_price_jumps(con: duckdb.DuckDBPyConnection, times: float = 10.0) -> pd.DataFrame:
    """Check 6. Companies priced from Tiingo whose latest close is `times` or more above or below
    the median close of its year before."""
    return con.execute(
        f"""
        with c as (select cik, session, close from core.price_daily where source = 'tiingo'),
        l as (select cik, max(session) as last_day from c group by cik),
        m as (select l.cik, l.last_day, any_value(x.close) filter (where x.session = l.last_day)
                     as last_close, median(x.close) as year_median
              from l join c x on x.cik = l.cik
               and x.session between l.last_day - interval 365 day and l.last_day
              group by all)
        select *, last_close / year_median as ratio from m
        where last_close >= {times} * year_median or last_close * {times} <= year_median
        order by greatest(ratio, 1 / ratio) desc
        """
    ).df()


def unjudged_insider_lines(con: duckdb.DuckDBPyConnection, above: float = 1e9) -> pd.DataFrame:
    """Check 7. Insider trade lines worth more than `above` dollars that the V2-24 rule could not
    judge, because no price of the stock was known by the filing date."""
    return con.execute(
        f"""
        select t.issuer_cik as cik, t.accession, t.trans_date, t.filing_date, t.trans_code,
               t.shares, t.price, t.shares * t.price as value, t.open_market
        from core.insider_trade t
        where t.shares * t.price > {above} and not t.value_typo
          and not exists (select 1 from core.price_daily p where p.cik = t.issuer_cik
                          and p.session <= t.filing_date)
        order by value desc
        """
    ).df()


def edgar_text(url: str, words: str | None = None, width: int = 300, timeout: float = 30) -> str:
    """The text of an SEC document (tags removed), or with `words` (a regex) the passages around
    each match. Uses the contact from `.env`, as the SEC requires."""
    agent = config.secrets(config.paths()).sec_user_agent
    r = httpx.get(url, headers={"User-Agent": agent}, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    text = html.unescape(re.sub(r"<[^>]+>", " ", r.text))
    text = re.sub(r"\s+", " ", text)
    if words is None:
        return text
    hits = [m.start() for m in re.finditer(words, text, re.I)]
    return " … ".join(text[max(0, h - width) : h + width] for h in hits[:3]) or "(no match)"


def filing_url(cik: str, accession: str) -> str:
    """The SEC's complete text of one filing."""
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{accession}.txt")  # fmt: skip


def share_history(con: duckdb.DuckDBPyConnection, cik: str, start: str, end: str) -> pd.DataFrame:
    """A company's accepted share counts between two dates, with the filing each came from and
    the price series' split factor on its date: the evidence for checks 3 and 4."""
    return con.execute(
        """
        select s.as_of, s.shares, s.filed, s.source, f.accession, f.form, p.cum_split_after
        from core.shares_outstanding s
        left join core.financial_fact f on f.cik = s.cik and f.period_end = s.as_of
             and f.filed = s.filed and f.item in ('shares_outstanding', 'shares_basic_avg')
             and f.first_filed
        asof left join core.price_daily p on p.cik = s.cik and p.session <= s.as_of
        where s.cik = ? and s.as_of between ? and ? order by s.as_of
        """,
        [cik, start, end],
    ).df()
