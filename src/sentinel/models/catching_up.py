"""The dilution answer's catching-up effect (decision V2-70; feature 007).

The answer (`config/risk_params.yaml`, labels: dilution) compares the last share count *published*
by the forecast date with the last one published within the next 182 days. A share sale made before
the forecast date but not yet in a published count is therefore answered 1 too: the forecast partly
catches up with a sale already announced (AMC, May to July 2021). This module measures how often,
on the approved model's development rows (2012 to mid-2022), and how the approved model scores with
and without those rows in its test years 2019-2022, rebuilt exactly as notebook 007 does
(`dilution.fit` per year, `chances` on the test year), checked against the approved record.

"Announced": a share-sale filing dated after the start count's own date and known by the forecast
date: a final share prospectus (424B1, 424B3, 424B4, or 424B5 without a bond term sheet in the
`TERM_SHEET_DAYS` before it, as in `features/events.py`) or a notice of an unregistered sale (8-K
item 3.02). The strict variant leaves out 424B3 (resale and merger prospectuses). The measure misses
a program announced before the count whose sales came after it, and a notice need not cover the
whole rise.

From a clone with the data, under the memory cap, not while the daily update runs (about five
minutes; the four test years are refitted):

    systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0 \\
        uv run python -m sentinel.models.catching_up

It reads the database read-only and the kept export of the approved models (`holdout.kept`),
writes no MLflow record, computes no answer from 2023 on, and writes the aggregates to
`docs/report/dilution_catching_up.md`.
"""

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss
from threadpoolctl import threadpool_limits

from sentinel import config, db, eda, holdout
from sentinel.features.events import TERM_SHEET_DAYS
from sentinel.labels.risk import share_steps
from sentinel.models import dilution, report

OUT = Path("docs/report/dilution_catching_up.md")
TOLERANCE = 1e-9  # the rebuilt test-year log loss against the approved record


def sale_filings(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    """Share-sale filings dated from `start` to `end`: `cik` (integer), `filing_date`,
    `known_at`, `strict` (False for 424B3)."""
    frame = con.execute(
        f"""
        select cast(f.cik as bigint) as cik, f.filing_date, f.known_at, f.form <> '424B3' as strict
        from core.filing f
        where f.known_at is not null and f.filing_date between ? and ?
          and (f.form in ('424B1', '424B3', '424B4')
               or (f.form = '424B5' and not exists (
                      select 1 from core.filing x
                      where x.cik = f.cik and x.form = 'FWP'
                        and x.filing_date between f.filing_date - interval {TERM_SHEET_DAYS} day
                                              and f.filing_date))
               or list_contains(string_split(coalesce(f.items, ''), ','), '3.02'))
        """,
        [start, end],
    ).df()
    for c in ("filing_date", "known_at"):
        frame[c] = pd.to_datetime(frame[c]).astype("datetime64[ns]")
    return frame


def start_counts(rows: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """`rows` (cik, as_of) with `count_date`: the own date of the start count the answer uses,
    the last `share_steps` count filed on or before the forecast date (`labels/risk.py`)."""
    shares = shares.assign(
        cik=shares["cik"].astype("int64"),
        period_end=pd.to_datetime(shares["period_end"]).astype("datetime64[ns]"),
        filed=pd.to_datetime(shares["filed"]).astype("datetime64[ns]"),
    )
    steps = share_steps(shares)[["cik", "period_end", "filed"]]
    left = rows.assign(
        cik=rows["cik"].astype("int64"),
        as_of=pd.to_datetime(rows["as_of"]).astype("datetime64[ns]"),
    )
    out = pd.merge_asof(
        left.sort_values("as_of"),
        steps.sort_values(["filed", "period_end"]),
        left_on="as_of",
        right_on="filed",
        by="cik",
        direction="backward",
    )
    return out.rename(columns={"period_end": "count_date"}).drop(columns="filed")


def announced(counts: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    """Per row of `counts` (cik, as_of, count_date, ...): `announced`, a share-sale filing dated
    after `count_date` and known by `as_of`, and `announced_strict`, the same without 424B3."""
    with duckdb.connect(config={"memory_limit": db.MEMORY_LIMIT}) as con:
        con.register("c", counts.reset_index(drop=True).reset_index(names="i"))
        con.register("s", sales)
        flags = con.execute(
            """
            select c.i, count(s.cik) > 0 as announced,
                   count(s.cik) filter (where s.strict) > 0 as announced_strict
            from c left join s
              on s.cik = c.cik and s.filing_date > c.count_date and s.known_at <= c.as_of
            group by c.i order by c.i
            """
        ).df()
    out = counts.reset_index(drop=True)
    out["announced"] = flags["announced"].to_numpy(dtype=bool)
    out["announced_strict"] = flags["announced_strict"].to_numpy(dtype=bool)
    return out


def share_table(rows: pd.DataFrame, flag: str) -> pd.DataFrame:
    """Per year and over all: the answers of 1, the share of them announced, the share of the
    answers of 0 with such a filing, and the dilution rate with and without one."""

    def one(d: pd.DataFrame) -> dict:
        yes, no = d[d["dilution"] == 1], d[d["dilution"] == 0]
        return {
            "answers of 1": len(yes),
            "of them announced": yes[flag].mean(),
            "answers of 0 with a filing": no[flag].mean(),
            "rate if announced": d.loc[d[flag], "dilution"].mean(),
            "rate if not announced": d.loc[~d[flag], "dilution"].mean(),
        }

    years = {str(y): one(g) for y, g in rows.groupby(rows["as_of"].dt.year)}
    return pd.DataFrame({**years, "all": one(rows)}).T


def rebuild(rows: pd.DataFrame, echo=print) -> pd.DataFrame:
    """The approved model's test-year chances and bands (notebook 007, cell 16): `dilution.fit`
    per test year, its calibrated chances and bands on that year's test rows."""
    threadpool_limits(dilution.THREADS)
    folds = eda.folds(rows, dilution.ANSWER)
    eda.check_folds(rows, folds, dilution.ANSWER)
    parts = []
    for year, f in folds.items():
        m = dilution.fit(rows, year)
        test = rows.loc[f["test"], ["cik", "as_of", dilution.ANSWER]].copy()
        raw, test["p"] = m.chances(rows[f["test"]])
        test["band"] = m.bands.predict(test[["as_of"]].assign(chance=raw))
        test["year"] = year
        echo(f"  {year}: refitted, {len(test):,} test rows")
        parts.append(test)
    return pd.concat(parts)


def check_record(test: pd.DataFrame, uri: str) -> float:
    """The largest difference between the rebuilt test-year log loss and the approved record's
    (the notebook's clipping); refuses above `TOLERANCE`."""
    records, _ = report.load_records(uri)
    res = report._frame(records["dilution"]["tables"]["results"])
    rec = res[res["level"] == "boosting"].assign(year=lambda d: d["year"].astype(str))
    rec = rec.set_index("year")["log_loss"]
    worst = 0.0
    for year, g in test.groupby("year"):
        p = np.clip(g["p"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        ll = log_loss(g[dilution.ANSWER].astype(int), p, labels=[0, 1])
        worst = max(worst, abs(ll - float(rec[str(year)])))
    if worst > TOLERANCE:
        raise RuntimeError(f"the rebuilt model differs from the approved record by {worst:.2e}")
    return worst


def score_table(test: pd.DataFrame, flag: str) -> pd.DataFrame:
    """All test rows, the announced ones and the others: rows, answers of 1, rate, AUC, and the
    rows of band 5 with their dilution rate."""

    def one(d: pd.DataFrame) -> dict:
        y = d[dilution.ANSWER].astype(float)
        top = d[d["band"] == 5]
        return {
            "rows": len(d),
            "answers of 1": int(y.sum()),
            "rate": y.mean(),
            "AUC": eda.auc(y.reset_index(drop=True), d["p"].reset_index(drop=True)),
            "band 5 rows": len(top),
            "band 5 rate": top[dilution.ANSWER].mean(),
        }

    return pd.DataFrame(
        {
            "all test rows": one(test),
            "announced": one(test[test[flag]]),
            "nothing announced": one(test[~test[flag]]),
        }
    ).T


def _md(frame: pd.DataFrame, index: str) -> str:
    def cell(v) -> str:
        if isinstance(v, (int, np.integer)) or (isinstance(v, float) and v.is_integer() and v > 1):
            return f"{int(v):,}"
        return f"{v:.3f}" if isinstance(v, float) else str(v)

    head = f"| {index} | " + " | ".join(frame.columns) + " |"
    rule = "|" + "---|" * (len(frame.columns) + 1)
    body = [f"| {i} | " + " | ".join(cell(v) for v in row) + " |" for i, row in frame.iterrows()]
    return "\n".join([head, rule, *body])


def main(p: config.Paths | None = None, out: Path = OUT, echo=print) -> Path:
    """Measure, rebuild, check and write `out` (the module's docstring)."""
    p = p or config.paths()
    uri = f"sqlite:///{p.mlflow_db}"
    models = holdout.frozen_models(p, ("dilution",))
    folder = holdout.kept(p, models)
    split_like = pd.read_parquet(folder.parent / "split_like.parquet")
    split_like["as_of"] = pd.to_datetime(split_like["as_of"])
    rows = dilution.learnable(eda.load("dilution", folder=folder), split_like)
    echo(f"the approved model's rows: {len(rows):,} (kept export {folder.parent.name})")
    with duckdb.connect(
        str(p.build_db), read_only=True, config={"memory_limit": db.MEMORY_LIMIT}
    ) as con:
        shares = con.execute(
            "select cik, as_of as period_end, shares as value, filed from core.shares_outstanding"
        ).df()
        first, last = rows["as_of"].min(), rows["as_of"].max()
        sales = sale_filings(con, (first - pd.DateOffset(years=1)).date(), last.date())
    flags = announced(start_counts(rows[["cik", "as_of", dilution.ANSWER]], shares), sales)
    if flags["count_date"].isna().any():
        raise RuntimeError("a row without the start count its answer was computed from")
    echo("refitting the approved model for each test year (about five minutes)")
    test = rebuild(rows, echo)
    worst = check_record(test, uri)
    test = test.assign(
        cik=test["cik"].astype("int64"),
        as_of=pd.to_datetime(test["as_of"]).astype("datetime64[ns]"),
    ).merge(
        flags[["cik", "as_of", "announced", "announced_strict"]],
        on=["cik", "as_of"],
        how="left",
        validate="one_to_one",
    )
    yes5 = test[(test[dilution.ANSWER] == 1) & (test["band"] == 5)]
    years = sorted(test["year"].unique())
    auc_years = pd.DataFrame(
        {
            str(y): {
                "all rows": score_table(g, "announced").loc["all test rows", "AUC"],
                "nothing announced": score_table(g, "announced").loc["nothing announced", "AUC"],
                "nothing announced (strict)": score_table(g, "announced_strict").loc[
                    "nothing announced", "AUC"
                ],
            }
            for y, g in test.groupby("year")
        }
    ).T
    text = f"""# Dilution: forecasts that catch up with an announced sale

*Generated by `python -m sentinel.models.catching_up` (decision V2-70) from the approved dilution
model's rows (kept export {folder.parent.name}) and the build database; never edited by hand. Every
number is an aggregate over many companies; no answer from 2023 on is used.*

**Why.** The answer compares the last share count *published* by the forecast date with the last one
published within the next 182 days. A sale made before the forecast date but not yet in a published
count is therefore answered 1 too. "Announced": a share-sale filing (a final share prospectus, not a
bond deal, or an 8-K item 3.02 notice of an unregistered sale) dated after the start count's own
date and known by the forecast date; "strict" leaves out 424B3 (resale and merger prospectuses).
The measure misses a program announced before the count whose sales came after it, and a notice
need not cover the whole rise.

## 1. How often an answer of 1 was already announced ({first.year} to {last.date()})

{_md(share_table(flags, "announced"), "year")}

Strict:

{_md(share_table(flags, "announced_strict"), "year")}

## 2. The approved model with and without them (test years {years[0]}-{years[-1]})

Rebuilt with the approved code (`dilution.fit` per test year, as notebook 007): each year's log
loss equals the approved record (largest difference {worst:.1e}).

{_md(score_table(test, "announced"), "test rows")}

Strict:

{_md(score_table(test, "announced_strict"), "test rows")}

AUC per test year:

{_md(auc_years, "year")}

Of the answers of 1 the model put in band 5 ({len(yes5):,}), {yes5["announced"].mean():.1%} were
already announced ({yes5["announced_strict"].mean():.1%} strict).
"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    echo(f"written: {out}")
    return out


if __name__ == "__main__":
    main()
