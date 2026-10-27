"""Window returns for any set of positions (plan §6.6, §6.7; feature 006 research R2–R5).

A position is (id, issuer, T, SIC, cost, price source). For each horizon H it is entered at the
adjusted open of session T+1 (its close when the open is unusable) and left at the adjusted close
of session T+H, or earlier when the issuer's prices end: then the delisting return applies and
the benchmark is earned for the rest of the window. Measures: buy-and-hold abnormal returns
against SPY, IWM and the issuer's Fama–French 49 industry (equal- and value-weighted), and the
FF5 + momentum cumulative abnormal return. Every sum is order-free (exact DECIMAL), so a rebuild
gives identical values.
"""

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np

from sentinel.config import registered_value

BHAR_MEASURES = ("spy", "iwm", "ind_ew", "ind_vw")
ALL_MEASURES = (*BHAR_MEASURES, "ff6")
FACTORS = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom")
OTHER_INDUSTRY = {49: 49, 12: 12}  # SIC codes in no range: "Other" (research R3)
RESULT_COLUMNS = (
    "id VARCHAR, horizon INTEGER, measure VARCHAR, entry_session DATE, exit_session DATE, "
    "end_session DATE, entry_at_close BOOLEAN, stock_return DOUBLE, bench_return DOUBLE, "
    "gross DOUBLE, delisted BOOLEAN, delisting_class VARCHAR, delisting_return DOUBLE, "
    "gross_dl_zero DOUBLE, gross_dl_wipeout DOUBLE"
)


@dataclass
class Skipped:
    no_entry_price: int = 0


def development_end(params: dict) -> date:
    """The last day a development window may end: the day before the holdout starts."""
    start = registered_value(params, "holdout")["start"]
    return date.fromordinal(start.toordinal() - 1)


def industry_sql(scheme: int, sic: str) -> str:
    """SQL for the industry number of `sic` (a column) in the 12 or 49 scheme, "Other" if none."""
    return f"""coalesce((select min(si.industry_no) from core.sic_industry si
                         where si.scheme = {scheme}
                           and try_cast({sic} as INTEGER) between si.sic_from and si.sic_to),
                        {OTHER_INDUSTRY[scheme]})"""


def _windows(con, source: str, horizons: list[int], end: date) -> None:
    """`_win`: one row per position and horizon whose exit session is on or before `end`."""
    con.execute(
        f"""
        create or replace temp table _pos as
        select x.*, s.session_no as t_no, {industry_sql(49, "x.sic")} as industry_no
        from {source} x join core.session s on s.session = x.t_session
        """
    )
    con.execute(
        """
        create or replace temp table _px as
        select p.issuer_cik, s.session_no, p.adj_close,
               p.open * p.adj_close / p.close as adj_open,
               coalesce(p.open > 0 and p.open between p.low and p.high, false) as open_ok
        from core.price_daily p join core.session s using (session)
        where p.issuer_cik in (select issuer_cik from _pos) and p.close > 0 and p.adj_close > 0
        """
    )
    horizons_sql = ", ".join(f"({h})" for h in horizons)
    con.execute(
        f"""
        create or replace temp table _win as
        with h(horizon) as (values {horizons_sql}),
        last as (select issuer_cik, max(session_no) as last_no from _px group by 1),
        base as (
            select p.*, h.horizon, p.t_no + 1 as entry_no, p.t_no + h.horizon as exit_no,
                   l.last_no
            from _pos p cross join h join last l using (issuer_cik)
        )
        select b.*, se.session as entry_session, sx.session as exit_session,
               least(b.exit_no, b.last_no) as end_no, b.last_no < b.exit_no as delisted,
               not e.open_ok as entry_at_close,
               case when e.open_ok then e.adj_open else e.adj_close end as entry_price
        from base b
        join core.session se on se.session_no = b.entry_no
        join core.session sx on sx.session_no = b.exit_no
        join _px e on e.issuer_cik = b.issuer_cik and e.session_no = b.entry_no
        where sx.session <= cast('{end}' as DATE)
        """
    )
    con.execute(
        """
        create or replace temp table _win as
        select w.*, s.session as end_session, x.adj_close as end_price,
               w.end_no < w.entry_no or (w.end_no = w.entry_no and w.entry_at_close) as flat
        from _win w
        asof join _px x on x.issuer_cik = w.issuer_cik and w.end_no >= x.session_no
        join core.session s on s.session_no = w.end_no
        """
    )


def _delisting(con, params: dict) -> None:
    """`_dl`: the delisting class and return of each delisted window (research R5)."""
    returns = registered_value(params, "delisting_returns")
    fallback = returns["performance_nasdaq"]  # unknown class, unknown venue
    classes = (
        "left join core.delisting d on d.issuer_cik = w.issuer_cik"
        if con.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = 'core' and table_name = 'delisting'"
        ).fetchone()[0]
        else "left join (select null::VARCHAR as issuer_cik, null::VARCHAR as class, "
        "null::DOUBLE as delisting_return) d on false"
    )
    con.execute(
        f"""
        create or replace temp table _dl as
        select w.id, w.horizon,
               case when w.delisted then coalesce(d.class, 'unknown') end as delisting_class,
               case when w.delisted then coalesce(d.delisting_return, {fallback}) else 0 end
                   as dlr
        from _win w {classes}
        """
    )


def _benchmarks(con) -> None:
    """`_bench`: buy-and-hold benchmark returns to the end session and for the rest (R2, R3)."""
    con.execute(
        """
        create or replace temp table _etf as
        select y.ticker, s.session_no, y.adj_close, y.open * y.adj_close / y.close as adj_open
        from stg.price_yahoo y join core.session s using (session)
        where y.ticker in ('SPY', 'IWM') and y.close > 0 and y.adj_close > 0
        """
    )
    con.execute(
        """
        create or replace temp table _ind as
        select f.industry_no, f.weighting, s.session_no,
               cast(sum(cast(ln(1 + f.ret) as DECIMAL(38, 18))) over (
                   partition by f.industry_no, f.weighting order by s.session_no
                   rows between unbounded preceding and current row) as DOUBLE) as cum
        from core.ff_industry_daily f join core.session s on s.session = f.date
        where f.scheme = 49 and f.ret is not null
        """
    )
    con.execute(
        """
        create or replace temp table _bench as
        with etf as (
            select w.id, w.horizon, lower(t.ticker) as measure,
                   ee.adj_close as entry_close, ee.adj_open as entry_open,
                   en.adj_close as end_close, ex.adj_close as exit_close
            from _win w cross join (values ('SPY'), ('IWM')) t(ticker)
            left join _etf ee on ee.ticker = t.ticker and ee.session_no = w.entry_no
            left join _etf en on en.ticker = t.ticker and en.session_no = w.end_no
            left join _etf ex on ex.ticker = t.ticker and ex.session_no = w.exit_no
        ),
        ind as (
            select w.id, w.horizon, 'ind_' || v.weighting as measure,
                   exp(c_end.cum - c_start.cum) - 1 as to_end,
                   exp(c_exit.cum - c_end.cum) - 1 as rest
            from _win w cross join (values ('ew'), ('vw')) v(weighting)
            left join _ind c_start on c_start.industry_no = w.industry_no
                 and c_start.weighting = v.weighting
                 and c_start.session_no = w.entry_no - 1 + cast(w.entry_at_close as INTEGER)
            left join _ind c_end on c_end.industry_no = w.industry_no
                 and c_end.weighting = v.weighting and c_end.session_no = w.end_no
            left join _ind c_exit on c_exit.industry_no = w.industry_no
                 and c_exit.weighting = v.weighting and c_exit.session_no = w.exit_no
        ),
        win as (select id, horizon, entry_at_close from _win)
        select e.id, e.horizon, e.measure,
               case when w.entry_at_close then e.end_close / e.entry_close
                    else e.end_close / e.entry_open end - 1 as to_end,
               e.exit_close / e.end_close - 1 as rest
        from etf e join win w using (id, horizon)
        union all
        select id, horizon, measure, to_end, rest from ind
        """
    )


def _bhar(con) -> None:
    """`_res` rows for the four buy-and-hold measures (research R5's formula)."""
    con.execute(
        f"""
        create or replace temp table _res ({RESULT_COLUMNS})
        """
    )
    con.execute(
        """
        insert into _res
        with base as (
            select w.id, w.horizon, b.measure, w.entry_session, w.exit_session, w.end_session,
                   w.entry_at_close, w.delisted, d.delisting_class, d.dlr,
                   case when w.flat then 0 else w.end_price / w.entry_price - 1 end as rs,
                   b.to_end as rb, b.rest
            from _win w join _dl d using (id, horizon) join _bench b using (id, horizon)
        )
        select id, horizon, measure, entry_session, exit_session, end_session, entry_at_close,
               (1 + rs) * (1 + dlr) * (1 + rest) - 1 as stock_return,
               (1 + rb) * (1 + rest) - 1 as bench_return,
               (1 + rest) * ((1 + rs) * (1 + dlr) - (1 + rb)) as gross,
               delisted, delisting_class, case when delisted then dlr end,
               (1 + rest) * ((1 + rs) - (1 + rb)) as gross_dl_zero,
               case when delisted then -(1 + rest) * (1 + rb)
                    else (1 + rest) * ((1 + rs) - (1 + rb)) end as gross_dl_wipeout
        from base
        """
    )


def _ff6(con, params: dict, chunk: int = 2000) -> None:
    """Append the FF5 + momentum CAR rows to `_res` (research R4): betas from sessions T−252 to
    T−21 with at least the registered number of returns, no intercept in the abnormal return,
    day T+1 open-to-close, the delisting return on the last session and zero after it."""
    window = registered_value(params, "factor_beta_window")
    first, last, need = window["start_offset"], window["end_offset"], window["min_observations"]
    con.execute(
        f"""
        create or replace temp table _fac as
        pivot (select s.session_no, f.factor, f.ret from core.ff_factor_daily f
               join core.session s on s.session = f.date
               where f.factor in ({", ".join(f"'{x}'" for x in (*FACTORS, "rf"))}))
        on factor using any_value(ret)
        """
    )
    con.execute(
        """
        create or replace temp table _rets as
        select issuer_cik, session_no, adj_close / lag(adj_close) over w - 1 as r,
               session_no - lag(session_no) over w as gap
        from _px window w as (partition by issuer_cik order by session_no)
        """
    )
    positions = con.execute("select distinct id, issuer_cik, t_no from _win order by id").fetchall()
    windows = con.execute(
        "select id, horizon, entry_no, end_no, exit_no, entry_at_close, flat from _win "
        "order by id, horizon"
    ).fetchall()
    by_id: dict[str, list] = {}
    for row in windows:
        by_id.setdefault(row[0], []).append(row)
    dl = dict(
        ((i, h), (d, c))
        for i, h, c, d in con.execute(
            "select id, horizon, delisting_class, dlr from _dl"
        ).fetchall()
    )
    meta = {
        (r[0], r[1]): r[2:]
        for r in con.execute(
            "select id, horizon, entry_session, exit_session, end_session, entry_at_close, "
            "delisted, end_price / entry_price - 1, flat from _win"
        ).fetchall()
    }
    out: list[tuple] = []
    for i in range(0, len(positions), chunk):
        part = positions[i : i + chunk]
        con.execute(
            "create or replace temp table _part (id VARCHAR, issuer_cik VARCHAR, t_no INTEGER)"
        )
        con.executemany("insert into _part values (?, ?, ?)", part)
        est = con.execute(
            f"""
            select p.id, r.r - f.rf, {", ".join(f"f.{x}" for x in FACTORS)}
            from _part p join _rets r on r.issuer_cik = p.issuer_cik
                 and r.session_no between p.t_no + {first} and p.t_no + {last} and r.gap = 1
            join _fac f on f.session_no = r.session_no
            where r.r is not null
            order by p.id, r.session_no
            """
        ).fetchall()
        days = con.execute(
            f"""
            with span as (
                select w.id, w.issuer_cik, min(w.entry_no) as a, max(w.end_no) as b
                from _win w where w.id in (select id from _part) group by 1, 2
            )
            select sp.id, s.session_no, f.rf, {", ".join(f"f.{x}" for x in FACTORS)},
                   case when s.session_no = sp.a then x.adj_close / x.adj_open - 1
                        when x.session_no is null then 0 else r.r end as r,
                   s.session_no = sp.a as first_day
            from span sp
            join core.session s on s.session_no between sp.a and sp.b
            left join _fac f on f.session_no = s.session_no
            left join _px x on x.issuer_cik = sp.issuer_cik and x.session_no = s.session_no
            left join _rets r on r.issuer_cik = sp.issuer_cik and r.session_no = s.session_no
            order by sp.id, s.session_no
            """
        ).fetchall()
        betas = _fit(est, need)
        series: dict[str, list] = {}
        for row in days:
            series.setdefault(row[0], []).append(row[1:])
        for pid, _, _ in part:
            out += _car_rows(pid, betas.get(pid), series.get(pid, []), by_id.get(pid, []), dl, meta)
    if out:
        con.executemany(f"insert into _res values ({', '.join(['?'] * 15)})", out)


def _car_rows(pid, beta, days, windows, dl, meta) -> list[tuple]:
    """The `ff6` result rows of one position. `days`: (session_no, rf, six factors, r, first_day)
    over the span of its windows; the abnormal return of a day is (r − rf) − β′f."""
    if beta is not None and days:
        arr = np.array([[np.nan if v is None else v for v in d[:9]] for d in days], dtype=float)
        nos, first = arr[:, 0], np.array([bool(d[9]) for d in days])
        ar = (arr[:, 8] - arr[:, 1]) - arr[:, 2:8] @ beta
    rows = []
    for _, horizon, _, end_no, _, at_close, _ in windows:
        car = None
        if beta is not None and days:
            mask = nos <= end_no
            if at_close:
                mask &= ~first
            segment = ar[mask]
            car = None if np.isnan(segment).any() else float(segment.sum())
        dlr, cls = dl[(pid, horizon)]
        entry_s, exit_s, end_s, at_close_flag, delisted, rs, flat = meta[(pid, horizon)]
        rs = 0.0 if flat else rs
        rows.append((
            pid, horizon, "ff6", entry_s, exit_s, end_s, at_close_flag,
            (1 + rs) * (1 + dlr) - 1, None,
            None if car is None else car + (dlr if delisted else 0.0),
            delisted, cls, dlr if delisted else None,
            car, None if car is None else (car - 1.0 if delisted else car),
        ))  # fmt: skip
    return rows


def _fit(rows: list[tuple], need: int) -> dict[str, np.ndarray]:
    """OLS with an intercept per position; returns the factor slopes (the intercept is dropped)."""
    betas: dict[str, np.ndarray] = {}
    start = 0
    while start < len(rows):
        pid, end = rows[start][0], start
        while end < len(rows) and rows[end][0] == pid:
            end += 1
        block = np.array([r[1:] for r in rows[start:end]], dtype=float)
        if len(block) >= need:
            y, x = block[:, 0], np.column_stack([np.ones(len(block)), block[:, 1:]])
            coef, *_ = np.linalg.lstsq(x, y, rcond=None)
            betas[pid] = coef[1:]
        start = end
    return betas


def window_returns(
    con: duckdb.DuckDBPyConnection,
    params: dict,
    source: str,
    horizons: list[int],
    measures=ALL_MEASURES,
    end: date | None = None,
) -> Skipped:
    """Fill `_res` (RESULT_COLUMNS) for the positions in `source` (id, issuer_cik, t_session,
    sic): one row per position, horizon and measure whose window ends by `end`."""
    end = end or development_end(params)
    _windows(con, source, horizons, end)
    skipped = Skipped(
        no_entry_price=con.execute(
            f"select count(*) from (select x.id from {source} x join core.session s "
            "on s.session = x.t_session) where id not in (select id from _win)"
        ).fetchone()[0]
    )
    _delisting(con, params)
    _benchmarks(con)
    _bhar(con)
    con.execute(
        "delete from _res where measure not in ("
        + ", ".join(f"'{m}'" for m in measures if m != "ff6")
        + ", '')"
    )
    if "ff6" in measures:
        _ff6(con, params)
    return skipped
