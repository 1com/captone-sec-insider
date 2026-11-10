"""Exploratory analysis of the three training sets (specs/004-eda): the helpers the EDA notebooks
share, so the three agree on method.

Only development rows are loaded (`as_of` on or before `development.last_window_end` of
`config/risk_params.yaml`); the holdout is never explored. Features get a family by name
(`FAMILIES`); identifiers, flags, answers, window ends and the results-move baseline get none.
Tables measure relations on whatever rows they are given: the notebooks pass eligible rows with an
answer, as the models will use.
"""

import re
from datetime import date

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import roc_auc_score

from sentinel import config

_P = config.paths()
_DEV = config.risk_params(_P)["development"]
EXPORT = _P.exports / "ml"
DEV_END: date = _DEV["last_window_end"]
TEST_YEARS: list[int] = list(_DEV["test_years"])
ANSWER = {"volatility": "vol_63_future", "results_move": "move", "dilution": "dilution"}
# the rows each question's model learns from (V2-26, V2-27)
ELIGIBLE = {"volatility": "eligible_volatility", "results_move": "eligible",
            "dilution": "eligible_dilution"}  # fmt: skip
DATES = ("as_of", "window_end", "filing_date", "report_date", "close_after")
WINDOW_END = {"volatility": "window_end", "results_move": "close_after", "dilution": "window_end"}
FAMILIES: list[tuple[str, str]] = [
    ("price", r"ret_\w+|vol_(21|63|252)|range_vol_21|max_drawdown_252|near_high_252|beta_252"
              r"|idio_vol_252|log_close|close"),
    ("trading", r"log_addv20|addv20|zero_volume_63|sessions_listed"),
    ("size", r"market_cap|log_market_cap|shares_outstanding"),
    ("financials", r"book_to_market|leverage|cash_to_assets|cash_runway_years|loss_making"
                   r"|revenue_growth|gross_margin|rd_intensity|interest_coverage|current_ratio"
                   r"|receivables_to_assets|sbc_to_revenue|share_growth_12m"
                   r"|issue_proceeds_to_assets|months_since_report"),
    ("filing events", r"n_(?!prev$)\w+|days_since_results|days_to_next_results"),
    ("insider", r"buy_\w+|sell_\w+|planned_sell_share_12m|ceo_cfo_sold_12m"
                r"|offering_buy_value_12m|buyers_14d|net_buy_to_mcap_12m"),
    ("short volume", r"short_ratio_\w+"),
    ("macro", r"vix\w*|spy_vol_63|dgs\w+|t10y2y\w*|dff\w*|baa10y\w*|cpi_yoy|unemployment\w*"),
]  # fmt: skip
# features that cannot be below zero (counts, amounts, prices, volatilities)
NON_NEGATIVE = (r"n_\w+|buy_\w+|sell_\w+|buyers_14d|close|addv20|market_cap|shares_outstanding"
                r"|sessions_listed|vol_\w+|range_vol_21|idio_vol_252|zero_volume_63"
                r"|cash_runway_years|offering_buy_value_12m|spy_vol_63|vix")  # fmt: skip
SIZE_BANDS = [(300e6, "micro"), (2e9, "small"), (10e9, "mid"), (np.inf, "large")]


def load(name: str, columns: list[str] | None = None, folder=None) -> pd.DataFrame:
    """The development rows of training set `name`, sorted by company and date; `columns` (with
    `cik` and `as_of` always) to load fewer; `folder` to read a kept export instead of the current
    one (the holdout test, 010)."""
    cols = None
    if columns is not None:
        cols = ["cik", "as_of", *[c for c in columns if c not in ("cik", "as_of")]]
    table = pq.read_table((folder or EXPORT) / f"{name}.parquet", columns=cols,
                          filters=[("as_of", "<=", DEV_END)])  # fmt: skip
    frame = table.to_pandas()
    for c in DATES:
        if c in frame:
            frame[c] = pd.to_datetime(frame[c])
    return frame.sort_values(["cik", "as_of"], kind="stable").reset_index(drop=True)


def family(col: str) -> str | None:
    """The feature family of column `col`, or None for identifiers, flags, answers and the like."""
    for name, pattern in FAMILIES:
        if re.fullmatch(pattern, col):
            return name
    return None


def features(frame: pd.DataFrame) -> list[str]:
    """The feature columns of `frame`, in file order."""
    return [c for c in frame.columns if family(c)]


def size_band(market_cap: pd.Series) -> pd.Series:
    """micro (< $300 M), small (< $2 B), mid (< $10 B), large, or unknown (no market value)."""
    out = pd.Series("unknown", index=market_cap.index, dtype=object)
    lower = 0.0
    for upper, name in SIZE_BANDS:
        out[(market_cap >= lower) & (market_cap < upper)] = name
        lower = upper
    return out


def coverage_table(frame: pd.DataFrame, by, answer: str | None = None,
                   eligible: str = "eligible") -> pd.DataFrame:  # fmt: skip
    """Rows, companies, the eligible share (by the `eligible` column) and (with `answer`) the share
    of eligible rows with an answer, per group of `by` (a column name or a Series)."""
    keys = frame[by] if isinstance(by, str) else by
    g = frame.groupby(keys, dropna=False, observed=True)
    out = pd.DataFrame({"rows": g.size(), "companies": g["cik"].nunique(),
                        "eligible": g[eligible].mean()})  # fmt: skip
    if answer:
        out["answered_if_eligible"] = (
            frame[answer].notna().where(frame[eligible]).groupby(keys, observed=True).mean()
        )
    return out


def eligibility_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    """Why rows are not eligible (a row can have several reasons): rows and share of the
    ineligible rows; `no reason found` should be 0."""
    out = frame[~frame["eligible"]]
    reasons = {
        "not an active filer": ~out["active_filer"].astype(bool),
        "excluded (fund or blank check)": out["excluded"].astype(bool),
        "close below $1": ~(out["close"] >= 1),
        "20-day traded value below $10,000": ~(out["addv20"] >= 10_000),
        "fewer than 63 price days": ~(out["sessions_listed"] >= 63),
    }
    table = pd.DataFrame({k: [int(v.sum())] for k, v in reasons.items()}, index=["rows"]).T
    table.loc["no reason found"] = int((~pd.concat(reasons, axis=1).any(axis=1)).sum())
    table["share"] = table["rows"] / max(len(out), 1)
    return table


def missing_table(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Each column's missing share, most missing first, with its family."""
    t = pd.DataFrame({"family": [family(c) for c in cols],
                      "missing": frame[cols].isna().mean().to_numpy()}, index=cols)  # fmt: skip
    return t.sort_values("missing", ascending=False, kind="stable")


def missing_by_year(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Missing share per column (rows) and year (columns)."""
    return frame[cols].isna().groupby(frame["as_of"].dt.year).mean().T


def extremes_table(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Per column: infinite values, negatives where impossible, and the min, 1st, 50th, 99th
    percentile and max of the finite values."""
    rows = {}
    for c in cols:
        x = pd.to_numeric(frame[c], errors="coerce").astype(float)
        finite = x[np.isfinite(x)]
        q = finite.quantile([0.01, 0.5, 0.99]) if len(finite) else pd.Series([np.nan] * 3)
        rows[c] = {
            "infinite": int(np.isinf(x).sum()),
            "negative": int((finite < 0).sum()) if re.fullmatch(NON_NEGATIVE, c) else 0,
            "min": finite.min(), "p1": q.iloc[0], "median": q.iloc[1], "p99": q.iloc[2],
            "max": finite.max(),
        }  # fmt: skip
    return pd.DataFrame(rows).T


def _spearman(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    ok = x.notna() & y.notna() & np.isfinite(x.astype(float)) & np.isfinite(y.astype(float))
    n = int(ok.sum())
    if n < 3 or x[ok].nunique() < 2:
        return np.nan, n
    return float(x[ok].rank().corr(y[ok].rank())), n


def rank_table(frame: pd.DataFrame, cols: list[str], answer: str) -> pd.DataFrame:
    """Spearman rank correlation of each column with the answer, strongest (by size) first."""
    rows = {c: dict(zip(("spearman", "n"), _spearman(frame[c], frame[answer]), strict=True))
            for c in cols}  # fmt: skip
    t = pd.DataFrame(rows).T.astype({"spearman": float, "n": int})
    t.insert(0, "family", [family(c) for c in t.index])
    return t.reindex(t["spearman"].abs().sort_values(ascending=False).index)


def rank_by_year(frame: pd.DataFrame, cols: list[str], answer: str) -> pd.DataFrame:
    """Spearman of each column (rows) with the answer within each year (columns)."""
    years = frame["as_of"].dt.year
    return pd.DataFrame({y: {c: _spearman(g[c], g[answer])[0] for c in cols}
                         for y, g in frame.groupby(years)})  # fmt: skip


def decile_table(frame: pd.DataFrame, col: str, answer: str) -> pd.DataFrame:
    """The answer's mean and median in each tenth of `col` (ties split by row order), with the
    feature's range in each."""
    f = frame[[col, answer]].dropna()
    f = f[np.isfinite(f[col].astype(float))]
    bins = pd.qcut(f[col].rank(method="first"), 10, labels=range(1, 11))
    g = f.groupby(bins, observed=True)
    return pd.DataFrame({"from": g[col].min(), "to": g[col].max(), "n": g.size(),
                         "mean": g[answer].mean(), "median": g[answer].median()})  # fmt: skip


def redundant_pairs(frame: pd.DataFrame, cols: list[str], threshold: float = 0.9,
                    sample: int = 200_000, seed: int = 0) -> pd.DataFrame:  # fmt: skip
    """Pairs of columns whose Spearman correlation is at least `threshold` in size, on a fixed
    sample of rows."""
    f = frame[cols]
    if len(f) > sample:
        f = f.sample(sample, random_state=seed)
    f = f.astype(float).replace([np.inf, -np.inf], np.nan)
    corr = f.rank().corr()
    pairs = [(a, b, corr.loc[a, b]) for i, a in enumerate(cols) for b in cols[i + 1:]
             if abs(corr.loc[a, b]) >= threshold]  # fmt: skip
    t = pd.DataFrame(pairs, columns=["a", "b", "spearman"])
    return t.reindex(t["spearman"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def purge_table(frame: pd.DataFrame, window_end: str, test_years=None) -> pd.DataFrame:
    """Per test year: training rows (dated before the year with the window ended before it), rows
    purged (dated before the year, window ending in or after it) and test rows (dated in it)."""
    rows = {}
    for y in test_years or TEST_YEARS:
        start = pd.Timestamp(year=y, month=1, day=1)
        before = frame["as_of"] < start
        rows[y] = {"train_rows": int((before & (frame[window_end] < start)).sum()),
                   "purged": int((before & (frame[window_end] >= start)).sum()),
                   "test_rows": int((frame["as_of"].dt.year == y).sum())}  # fmt: skip
    return pd.DataFrame(rows).T


def folds(frame: pd.DataFrame, question: str, years=None) -> dict[int, dict[str, pd.Series]]:
    """The walk-forward folds, cut by dates only (research R3; never a random split). For test year
    Y each row with an answer falls in one block, by its date (`as_of`) and the day its answer was
    known (`WINDOW_END`): `inner` (answer known before the validation year Y-1: the model learns
    from it), `gap` (dated before Y-1, answer known in Y-1: left out), `valid` (dated in Y-1,
    answer known before Y: settings, calibration, band edges), `purged` (dated before Y, answer
    known in Y or later: left out) and `test` (dated in Y: scored once). A model fitted for the
    holdout is the fold of `DEV_END.year + 1`, which has no test rows here (sealed)."""
    end, dated = frame[WINDOW_END[question]], frame["as_of"]
    known = end.notna()
    out = {}
    for y in years or TEST_YEARS:
        test_start, valid_start = pd.Timestamp(y, 1, 1), pd.Timestamp(y - 1, 1, 1)
        out[y] = {
            "inner": end < valid_start,
            "gap": (dated < valid_start) & (end >= valid_start) & (end < test_start),
            "valid": (dated >= valid_start) & (end < test_start),
            "purged": (dated < test_start) & (end >= test_start),
            "test": known & (dated.dt.year == y),
        }
    return out


def check_folds(frame: pd.DataFrame, fold_masks: dict, question: str) -> pd.DataFrame:
    """Each fold's blocks in time order, or an AssertionError naming the fold and the broken rule;
    the boundaries per fold (to show in the notebook)."""
    end, dated = frame[WINDOW_END[question]], frame["as_of"]
    sealed = pd.Timestamp(DEV_END)
    assert not (end > sealed).any(), "an answer in the holdout is in the data: the seal is broken"
    out = {}
    for y, f in fold_masks.items():
        test_start, valid_start = pd.Timestamp(y, 1, 1), pd.Timestamp(y - 1, 1, 1)
        names = list(f)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                assert not (f[a] & f[b]).any(), f"{y}: a row is in both {a} and {b}"
        inner, valid, test = f["inner"], f["valid"], f["test"]
        for name, m in (("inner", inner), ("valid", valid), ("test", test)):
            assert end[m].notna().all(), f"{y}: a {name} row has no answer"
            assert (end[m] <= sealed).all(), f"{y}: a {name} row's answer is in the holdout"
        assert (end[inner] < valid_start).all(), f"{y}: an inner answer is known in validation"
        assert (dated[valid] >= valid_start).all(), f"{y}: a validation row is too early"
        assert (end[valid] < test_start).all(), f"{y}: a validation answer is known in the test"
        assert dated[test].dt.year.eq(y).all(), f"{y}: a test row is outside the test year"
        if inner.any() and valid.any():
            assert dated[inner].max() < dated[valid].min(), f"{y}: validation is not after inner"
        if (inner | valid).any() and test.any():
            assert end[inner | valid].max() < dated[test].min(), f"{y}: training sees the test"
        out[y] = {"inner rows": int(inner.sum()), "inner dated to": dated[inner].max(),
                  "inner answers known by": end[inner].max(), "valid rows": int(valid.sum()),
                  "valid dated from": dated[valid].min(),
                  "valid answers known by": end[valid].max(),
                  "left out (gap, purged)": int((f["gap"] | f["purged"]).sum()),
                  "test rows": int(test.sum()), "test dated from": dated[test].min()}  # fmt: skip
    return pd.DataFrame(out).T


def known_before(frame: pd.DataFrame, question: str, day) -> None:
    """Call before fitting anything (a model, settings, a calibration, band edges, a range):
    every row it learns from must have its answer known before `day`, the start of the period it
    is judged on."""
    late = frame[WINDOW_END[question]].isna() | (frame[WINDOW_END[question]] >= pd.Timestamp(day))
    assert not late.any(), f"{int(late.sum())} rows' answers are not known before {day}"


def auc(y: pd.Series, score: pd.Series) -> float:
    """Area under the ROC curve of `score` for the yes/no answer `y` (rows with both)."""
    ok = y.notna() & score.notna() & np.isfinite(score.astype(float))
    return float(roc_auc_score(y[ok].astype(int), score[ok].astype(float)))


def top_decile_lift(y: pd.Series, score: pd.Series) -> float:
    """The answer's rate in the tenth of rows with the highest score, over the overall rate."""
    ok = y.notna() & score.notna() & np.isfinite(score.astype(float))
    y, score = y[ok].astype(float), score[ok].astype(float)
    top = score.rank(method="first", ascending=False) <= max(len(score) // 10, 1)
    return float(y[top].mean() / y.mean())
