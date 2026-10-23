"""Event-study summaries with uncertainty that respects overlapping events (research R5).

Bands come from a moving-block bootstrap over calendar months: events in the same month move
together, so months (not events) are resampled, in blocks of consecutive months.
"""

import math

import numpy as np
import pandas as pd


def _month_sums(values: np.ndarray, months: pd.Series):
    """Per-month sums (rows) and counts of `values` (events × columns), months in calendar order."""
    frame = pd.DataFrame(values).assign(_m=months.to_numpy())
    grouped = frame.groupby("_m", sort=True)
    sums = grouped.sum(min_count=1).to_numpy(dtype=float)
    counts = frame.notna().groupby(frame["_m"]).sum().drop(columns="_m").to_numpy(dtype=float)
    return np.nan_to_num(sums), counts


def block_bootstrap(
    values: np.ndarray,
    months: pd.Series,
    block: int,
    reps: int,
    rng: np.random.Generator,
    chunk: int = 200,
):
    """2.5/97.5 percentile band of the event-weighted mean, resampling blocks of months.

    `values` is events × columns (a single column for a horizon, many for a path).
    """
    values = values.reshape(len(values), -1)
    sums, counts = _month_sums(values, months)
    m = len(sums)
    if m == 0:
        nan = np.full(values.shape[1], np.nan)
        return nan, nan
    block = max(1, min(block, m))
    n_blocks = math.ceil(m / block)
    draws = []
    for start in range(0, reps, chunk):
        r = min(chunk, reps - start)
        starts = rng.integers(0, m - block + 1, size=(r, n_blocks))
        idx = (starts[:, :, None] + np.arange(block)).reshape(r, -1)[:, :m]
        s = sums[idx].sum(axis=1)
        c = counts[idx].sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            draws.append(s / c)
    draws = np.concatenate(draws)
    return np.nanpercentile(draws, 2.5, axis=0), np.nanpercentile(draws, 97.5, axis=0)


def summarize(ret: pd.DataFrame, paths: dict, ks: np.ndarray, settings) -> dict:
    """Tables, paths and per-year results for the dashboard (used events only)."""
    b = settings.mvp["bootstrap"]
    rng = np.random.default_rng(b["seed"])
    used = ret["priced"].fillna(False) & ret["passes_floors"].fillna(False)
    months = pd.to_datetime(ret["signal_date"]).dt.to_period("M").astype(str)
    out = {"horizons": [], "paths": {}, "by_year": [], "ks": ks.tolist()}
    for group in ("A", "B1"):
        sel = used & (ret["group"] == group)
        for bench in ("iwm", "spy"):
            mat = paths[bench.upper()][sel.to_numpy()]
            lo, hi = block_bootstrap(mat, months[sel], b["path_block_months"], b["reps"], rng)
            out["paths"][f"{group}_{bench}"] = {
                "mean": np.nanmean(mat, axis=0).round(5).tolist() if len(mat) else [],
                "lo": np.round(lo, 5).tolist(),
                "hi": np.round(hi, 5).tolist(),
                "n": int(sel.sum()),
            }
            for h in settings.horizons:
                for kind in ("gross", "net"):
                    col = f"{kind}_{h}_{bench}"
                    v = ret.loc[sel, col].astype(float)
                    v = v[np.isfinite(v)]
                    block = max(1, math.ceil(h / 21))
                    lo, hi = block_bootstrap(v.to_numpy(), months[v.index], block, b["reps"], rng)
                    out["horizons"].append(
                        {
                            "group": group,
                            "bench": bench,
                            "h": h,
                            "kind": kind,
                            "n": len(v),
                            "mean": float(v.mean()) if len(v) else None,
                            "median": float(v.median()) if len(v) else None,
                            "share_pos": float((v > 0).mean()) if len(v) else None,
                            "lo": float(lo[0]) if len(v) else None,
                            "hi": float(hi[0]) if len(v) else None,
                        }
                    )
        years = pd.to_datetime(ret["signal_date"]).dt.year
        h = settings.primary_horizon
        for y in sorted(years[sel].unique()):
            v = ret.loc[sel & (years == y), f"net_{h}_iwm"].astype(float).dropna()
            out["by_year"].append(
                {
                    "group": group,
                    "year": int(y),
                    "n": len(v),
                    "mean": float(v.mean()) if len(v) else None,
                }
            )
    return out
