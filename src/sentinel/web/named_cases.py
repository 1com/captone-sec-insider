"""The app's named cases (feature 026, T019; SC-002, SC-005).

For each named company, every section of its page as the app serves it (its own endpoints, called
in process on the real serving copy) is compared with the same values taken independently: the
build database (`core` and `feature` schemas), the frozen dilution model, and the SEC's own files
(the company's name and industry from `submissions.zip`, its share counts from `companyfacts.zip`).
A section passes when the values are equal, or when it is absent and the page states the right
reason. The page's template and scripts are scanned for typed-in dates (SC-005).

    uv run python -m sentinel.web.named_cases

Read-only, about a minute. It prints every check; `docs/report/app_named_cases.md` gets the
verdicts and the reasons for failures only, never a price or another Tiingo-derived value.
"""

import gzip
import json
import re
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from sentinel import config, db
from sentinel.models import dilution

CASES = [  # (CIK, ticker searched, what it stands for: SC-002's kinds and earlier fixes)
    ("320193", "AAPL", "a large US company"),
    ("1055726", "INO", "a small diluter: loss-making, nine offering filings in a year"),
    ("1046179", "TSM", "a foreign filer"),
    ("1418091", "TWTR", "a delisted company, taken private in 2022"),
    ("1744489", "DIS", "a reused ticker: The Walt Disney Company, since 2019"),
    ("1001039", "DIS", "a reused ticker: TWDC Enterprises, Disney until 2019"),
    ("1411579", "AMC", "a reverse split: 1 for 10 on 24 Aug 2023"),
    ("100826", "UELMO", "a company without insider trades"),
    ("1062506", "ALDA", "a blank-check company"),
    ("1031235", "SELF", "a listed company without prices"),
    ("1859199", "AIRE", "a recent offering: 424B4 of 4 Nov 2026"),
    ("1408710", "FN", "a stray filing of another company (V2-63)"),
    ("835011", "CASK", "a ticker change, MGPI to CASK (027)"),
]
SPLIT_DAYS = {"1411579": "2023-08-24"}  # adjusted prices must be continuous across these days
OUT = Path("docs/report/app_named_cases.md")
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
TYPED_DATES = [
    re.compile(r"\b(?:19|20)\d\d-\d\d-\d\d\b"),
    re.compile(rf"\b(?:{MONTHS})[a-z]*\.? \d{{1,2}}, (?:19|20)\d\d\b"),
    re.compile(rf"\b\d{{1,2}} (?:{MONTHS})[a-z]* (?:19|20)\d\d\b"),
]
SECTIONS = ("search", "facts", "quote", "prices", "shares", "filings", "insiders", "card",
            "dilution", "diagnostics")  # fmt: skip


def typed_dates(web_dir: Path) -> list[str]:
    """SC-005: dates written into the page's template and scripts (the vendored chart library
    left out); each is `file: text`."""
    found = []
    files = [*web_dir.glob("templates/*.html"), *web_dir.glob("static/*.js")]
    for f in sorted(files):
        if f.name.startswith("lightweight-charts"):
            continue
        text = f.read_text(encoding="utf-8")
        found += [f"{f.name}: {m.group(0)}" for rx in TYPED_DATES for m in rx.finditer(text)]
    return found


def _same(a, b, tol: float = 1e-9) -> bool:
    """Equal values: numbers within a relative `tol`, dates and texts as strings."""
    a, b = (x.item() if isinstance(x, np.generic) else x for x in (a, b))
    if a is None or b is None or (isinstance(a, float) and pd.isna(a)):
        return (a is None or pd.isna(a)) and (b is None or pd.isna(b))
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    return str(a)[:10] == str(b)[:10] if _is_date(a) or _is_date(b) else str(a) == str(b)


def _is_date(v) -> bool:
    return hasattr(v, "isoformat") or bool(re.fullmatch(r"\d{4}-\d\d-\d\d.*", str(v)))


def sec_json(raw: Path, kind: str, cik: str) -> dict:
    """The SEC's newest stored JSON of a company: the per-company file of the latest daily update
    (`<kind>/<date>/CIK….json.gz`) when there is one, else the bulk file (`company/<kind>.zip`)."""
    name = f"CIK{int(cik):010d}.json"
    newer = sorted(raw.glob(f"{kind}/*/{name}.gz"))
    if newer:
        return json.loads(gzip.decompress(newer[-1].read_bytes()))
    with zipfile.ZipFile(raw / "company" / f"{kind}.zip") as z:
        try:
            return json.loads(z.read(name))
        except KeyError:
            return {}


def sec_company(raw: Path, cik: str) -> dict:
    """The SEC's own record of a company (`submissions`): name, former names, SIC."""
    d = sec_json(raw, "submissions", cik)
    if not d:
        return {}
    names = {d.get("name", "")} | {f.get("name", "") for f in d.get("formerNames", [])}
    return {"name": d.get("name"), "names": {n.upper().strip() for n in names}, "sic": d.get("sic")}


def sec_shares(raw: Path, cik: str) -> dict[str, int]:
    """The cover-page share counts the SEC extracted (`companyfacts`), the first filed value for
    each count's date."""
    d = sec_json(raw, "companyfacts", cik)
    facts = d.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {})
    first: dict[str, tuple[str, int]] = {}
    for e in facts.get("units", {}).get("shares", []):
        if e["end"] not in first or e["filed"] < first[e["end"]][0]:
            first[e["end"]] = (e["filed"], e["val"])
    return {end: v for end, (_, v) in first.items()}


def expected_reason(facts: dict, card: dict) -> str:
    """The reason a page without a dilution forecast should state (FR-004, V2-27, V2-66)."""
    if card.get("foreign_filer") or facts.get("filer_type") == "foreign":
        return "foreign"
    if facts.get("is_blank_check"):
        return "blank-check"
    if not facts.get("listed"):
        return "no longer trade"
    if not facts.get("has_prices"):
        return "no share prices"
    if not card:
        return "no recent price"
    if facts.get("is_fund"):
        return "funds"
    return "not complete"


def check(page: dict, b: duckdb.DuckDBPyConnection, raw: Path, model, cik: str) -> dict:
    """Each section's verdict: (passed, note) or (None, note) when it does not apply."""
    c, out = page["company"], {}
    facts, card = c.get("facts") or {}, c.get("card") or {}
    one = lambda sql: b.execute(sql, [cik]).fetchone()  # noqa: E731

    out["search"] = (any(r.get("cik") == cik for r in page["search"]), "found by its ticker")

    sec = sec_company(raw, cik)
    name_ok = (facts.get("name") or "").upper().strip() in sec.get("names", set())
    sic_ok = str(facts.get("sic") or "") == str(sec.get("sic") or "")
    out["facts"] = (bool(sec) and name_ok and sic_ok, f"name and SIC against the SEC: {sec}")

    last = one(
        "select session, close / cum_split_after from core.price_daily where cik = ? "
        "and not coalesce(glitch, false) and close > 0 order by session desc limit 1"
    )
    q = c.get("quote") or {}
    if last is None:
        out["quote"] = (q.get("session") is None, "no prices in the data, none shown")
    else:
        ok = _same(q.get("session"), last[0]) and _same(q.get("close"), last[1])
        out["quote"] = (ok, "last session and split-adjusted close against core.price_daily")

    span = one(
        "select count(*), min(session), max(session) from core.price_daily where cik = ? "
        "and not coalesce(glitch, false) and close > 0"
    )
    t = page["prices"].get("t", [])
    ok = len(t) == span[0] and (not t or (_same(t[0], span[1]) and _same(t[-1], span[2])))
    note = "days, first and last day against core.price_daily"
    if ok and cik in SPLIT_DAYS:
        day = SPLIT_DAYS[cik]
        i = next(k for k, s in enumerate(t) if str(s)[:10] >= day)
        ratio = page["prices"]["c"][i] / page["prices"]["c"][i - 1]
        ok = 0.5 < ratio < 2
        note += f"; across the split of {day} the adjusted close moves by a factor {ratio:.2f}"
    out["prices"] = (ok, note)

    shown = c.get("shares") or []
    data_counts = dict(
        b.execute(
            "select period_end::varchar, value from core.financial_fact where cik = ? "
            "and item = 'shares_outstanding' and first_filed and value > 0 "
            "qualify row_number() over (partition by period_end order by filed, value) = 1",
            [cik],
        ).fetchall()
    )
    sec_counts = sec_shares(raw, cik)
    off_data = [s for s in shown if not _same(s["reported"], data_counts.get(s["period_end"]))]
    at_sec = [s for s in shown if s["period_end"] in sec_counts]
    off_sec = [s for s in at_sec if int(s["reported"]) != sec_counts[s["period_end"]]]
    out["shares"] = (
        len(shown) == len(data_counts) and not off_data and not off_sec,
        f"{len(shown)} counts shown, {len(data_counts)} in core.financial_fact, {len(off_data)} "
        f"differ; {len(at_sec)} found in the SEC's file, {len(off_sec)} differ",
    )

    n_f, last_f = one("select count(*), max(filing_date) from core.filing where cik = ?")
    shown_n = sum(page["filings"]["counts"].values())
    newest = page["filings"]["filings"][0]["filing_date"] if page["filings"]["filings"] else None
    out["filings"] = (
        shown_n == n_f and _same(newest, last_f),
        f"{shown_n:,} filings shown, {n_f:,} in core.filing; newest date equal",
    )

    n_i, bought, sold = one(
        "select count(*), coalesce(sum(value_usd) filter (where side = 'buy'), 0), "
        "coalesce(sum(value_usd) filter (where side = 'sell'), 0) from core.insider_activity "
        "where issuer_cik = ? and side in ('buy', 'sell')"
    )
    m = page["insiders"]["monthly"]
    ok = (len(page["insiders"]["trades"]) == n_i
          and _same(sum(r["bought"] or 0 for r in m), bought, 1e-6)
          and _same(sum(r["sold"] or 0 for r in m), sold, 1e-6))  # fmt: skip
    out["insiders"] = (ok, f"{n_i:,} filings; the monthly totals against core.insider_activity")

    snap = b.execute("select * from feature.snapshot where cik = ? and latest", [cik]).df()
    if snap.empty:
        out["card"] = (not card, "no latest feature row in the data, no card shown")
    else:
        row = snap.iloc[0].to_dict()
        cols = [k for k in row if k in card]
        diff = [k for k in cols if not _same(card[k], row[k], 1e-9)]
        out["card"] = (not diff, f"{len(cols)} values against feature.snapshot; differ: {diff}")

    d = c.get("dilution") or {}
    if d.get("available"):
        rows = snap.copy()
        rows["as_of"] = pd.to_datetime(rows["as_of"])
        pred = dilution.predict(model, rows).iloc[0]
        ok = (_same(d["chance"], float(pred["dilution_prob"]), 1e-9)
              and int(d["band"]) == int(pred["dilution_band"])
              and _same(d["as_of"], row["as_of"]))  # fmt: skip
        out["dilution"] = (ok, "chance, band and date against the frozen model on the data's row")
    else:
        want = expected_reason(facts, card)
        given = d.get("reason", "")
        out["dilution"] = (want in given, f"no forecast; expected a reason with '{want}', "
                                          f"the page says: {given}")  # fmt: skip

    diag = c.get("diagnostics") or {}
    first, last_d, days, glitch = one(
        "select min(session), max(session), count(*), count(*) filter (where glitch) "
        "from core.price_daily where cik = ?"
    )
    dp = diag.get("prices") or {}
    span_ok = days == 0 or (_same(dp.get("first"), first) and _same(dp.get("last"), last_d))
    ok = (
        int(dp.get("days") or 0) == days
        and int(dp.get("glitch_days") or 0) == glitch
        and diag.get("filings") == n_f
        and diag.get("insider_filings") == n_i
        and span_ok
    )
    out["diagnostics"] = (ok, "price days and dates, filing and insider counts against the data")
    return out


def main(p: config.Paths | None = None, out: Path = OUT, echo=print) -> Path:
    """Fetch every named case's page from the app, check each section, write `out`."""
    from fastapi.testclient import TestClient

    from sentinel import holdout
    from sentinel.web import main as web

    p = p or config.paths()
    raw = p.raw / "sec"
    model = holdout.frozen_models(p, ("dilution",))["dilution"]["model"]
    client = TestClient(web.app)
    if web.PASSWORD is not None:
        client.auth = ("check", web.PASSWORD)
    results, notes = {}, []
    with duckdb.connect(
        str(p.build_db), read_only=True, config={"memory_limit": db.MEMORY_LIMIT}
    ) as b:
        for cik, ticker, kind in CASES:
            page = {
                "search": client.get("/api/search", params={"q": ticker}).json(),
                "company": client.get(f"/api/company/{cik}").json(),
                "prices": client.get(f"/api/prices/{cik}").json(),
                "insiders": client.get(f"/api/insiders/{cik}").json(),
                "filings": client.get(f"/api/filings/{cik}", params={"limit": 1}).json(),
            }
            res = check(page, b, raw, model, cik)
            results[(cik, ticker, kind)] = res
            echo(f"\n{ticker} (CIK {cik}), {kind}")
            for s in SECTIONS:
                ok, note = res[s]
                echo(f"  {'PASS' if ok else 'FAIL'} {s}: {note}")
                if not ok:  # price values are Tiingo-derived: never written to the file
                    private = s in ("quote", "prices")
                    shown = "differs from core.price_daily (values not shown here)"
                    notes.append(f"- **{ticker}, {s}**: " + (shown if private else note))
    dates = typed_dates(Path(web.__file__).parent)
    echo(f"\ntyped-in dates in the template and scripts: {dates or 'none'}")
    head = "| case | CIK | stands for | " + " | ".join(SECTIONS) + " |"
    rule = "|" + "---|" * (len(SECTIONS) + 3)
    body = [
        f"| {t} | {c} | {k} | "
        + " | ".join("pass" if r[s][0] else "**FAIL**" for s in SECTIONS)
        + " |"
        for (c, t, k), r in results.items()
    ]
    n_fail = sum(not r[s][0] for r in results.values() for s in SECTIONS)
    text = "\n".join([
        "# The app's named cases (026, SC-002 and SC-005)",
        "",
        "*Generated by `python -m sentinel.web.named_cases` from the app's own endpoints on the "
        "serving copy, checked against the build database, the frozen dilution model and the SEC's "
        "files; never edited by hand. Verdicts only: no price or other value is written here.*",
        "",
        f"{len(results)} named cases, {len(SECTIONS)} sections each: {n_fail} failed.",
        "",
        head, rule, *body,
        "",
        "## Failures",
        "",
        *(notes or ["None."]),
        "",
        "## Typed-in dates (SC-005)",
        "",
        *([f"- {x}" for x in dates] or ["None in the template and scripts."]),
        "",
    ])  # fmt: skip
    out = Path(out)
    out.write_text(text, encoding="utf-8")
    echo(f"written: {out}")
    return out


if __name__ == "__main__":
    main()
