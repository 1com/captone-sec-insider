"""Live outcome tracking for EDGAR-SENTINEL (Feature 009).

Scans open forecasts in `score.daily` whose evaluation windows have closed,
records the realized answers, errors, and hit rates in `score.outcome`.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb

from sentinel.scoring import schema


def evaluate_outcomes(
    con: duckdb.DuckDBPyConnection,
    echo: Callable[[str], None] = lambda _: None,
) -> dict[str, int]:
    """Evaluate closed forecast windows and record outcomes in score.outcome."""
    schema.create_tables(con)
    now_ts = datetime.now(UTC).replace(tzinfo=None)

    counts = {"volatility": 0, "dilution": 0, "results_move": 0}

    # 1. Volatility outcomes (join with label.volatility where window has closed)
    vol_rows = con.execute("""
        select
            s.cik,
            s.as_of,
            s.question,
            s.model_version,
            l.vol_window_end as window_end,
            s.forecast_val,
            s.band as forecast_band,
            l.vol_63_future as actual_val,
            (s.forecast_val - l.vol_63_future) as error,
            s.extra_json
        from score.daily s
        join label.volatility l using (cik, as_of)
        where s.question = 'volatility'
          and l.vol_63_future is not null
    """).fetchall()

    if vol_rows:
        evaluated_vol = []
        for r in vol_rows:
            cik, as_of, q, m_ver, w_end, f_val, f_band, act_val, err, extra = r
            is_hit = False
            if extra:
                try:
                    meta = json.loads(extra)
                    low = meta.get("vol_low_80", -1e9)
                    high = meta.get("vol_high_80", 1e9)
                    is_hit = bool(low <= act_val <= high)
                except Exception:
                    is_hit = bool(abs(err) <= 0.05)
            else:
                is_hit = bool(abs(err) <= 0.05)

            evaluated_vol.append(
                (cik, as_of, q, m_ver, w_end, f_val, f_band, act_val, err, is_hit, now_ts)
            )

        con.executemany(
            """
            insert into score.outcome
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict (cik, as_of, question, model_version)
            do update set
                window_end = excluded.window_end,
                forecast_val = excluded.forecast_val,
                forecast_band = excluded.forecast_band,
                actual_val = excluded.actual_val,
                error = excluded.error,
                is_hit = excluded.is_hit,
                evaluated_at = excluded.evaluated_at
        """,
            evaluated_vol,
        )
        counts["volatility"] = len(evaluated_vol)

    # 2. Dilution outcomes (join with label.dilution where window has closed)
    dil_rows = con.execute("""
        select
            s.cik,
            s.as_of,
            s.question,
            s.model_version,
            l.dilution_window_end as window_end,
            s.forecast_val,
            s.band as forecast_band,
            cast(l.dilution as double) as actual_val,
            (s.forecast_val - cast(l.dilution as double)) as error
        from score.daily s
        join label.dilution l using (cik, as_of)
        where s.question = 'dilution'
          and l.dilution is not null
    """).fetchall()

    if dil_rows:
        evaluated_dil = []
        for r in dil_rows:
            cik, as_of, q, m_ver, w_end, f_val, f_band, act_val, err = r
            # Hit definition: binary prediction at 10% probability threshold matches actual dilution
            is_hit = bool((f_val >= 0.10) == (act_val == 1.0))
            evaluated_dil.append(
                (cik, as_of, q, m_ver, w_end, f_val, f_band, act_val, err, is_hit, now_ts)
            )

        con.executemany(
            """
            insert into score.outcome
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict (cik, as_of, question, model_version)
            do update set
                window_end = excluded.window_end,
                forecast_val = excluded.forecast_val,
                forecast_band = excluded.forecast_band,
                actual_val = excluded.actual_val,
                error = excluded.error,
                is_hit = excluded.is_hit,
                evaluated_at = excluded.evaluated_at
        """,
            evaluated_dil,
        )
        counts["dilution"] = len(evaluated_dil)

    # 3. Results-day move outcomes (join with label.results_move)
    res_rows = con.execute("""
        select
            s.cik,
            s.as_of,
            s.question,
            s.model_version,
            l.close_after as window_end,
            s.forecast_val,
            s.band as forecast_band,
            l.move as actual_val,
            (s.forecast_val - l.move) as error
        from score.daily s
        join label.results_move l using (cik, as_of)
        where s.question = 'results_move'
          and l.move is not null
    """).fetchall()

    if res_rows:
        evaluated_res = []
        for r in res_rows:
            cik, as_of, q, m_ver, w_end, f_val, f_band, act_val, err = r
            # Hit definition: prediction within 5 percentage points of actual move
            is_hit = bool(abs(err) <= 0.05)
            evaluated_res.append(
                (cik, as_of, q, m_ver, w_end, f_val, f_band, act_val, err, is_hit, now_ts)
            )

        con.executemany(
            """
            insert into score.outcome
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict (cik, as_of, question, model_version)
            do update set
                window_end = excluded.window_end,
                forecast_val = excluded.forecast_val,
                forecast_band = excluded.forecast_band,
                actual_val = excluded.actual_val,
                error = excluded.error,
                is_hit = excluded.is_hit,
                evaluated_at = excluded.evaluated_at
        """,
            evaluated_res,
        )
        counts["results_move"] = len(evaluated_res)

    total_eval = sum(counts.values())
    if total_eval > 0:
        echo(
            f"  outcomes evaluated: {counts['volatility']:,} volatility, "
            f"{counts['dilution']:,} dilution, {counts['results_move']:,} results_move"
        )
    return counts
