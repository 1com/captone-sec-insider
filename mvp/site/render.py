"""Render the dashboard: one page, six tabs, data inlined (plan decision M1).

`local` writes a complete document with vendored ECharts and the TradingView widget.
`artifact` writes a skeleton-less page for claude.ai (CSS and JS inline, ECharts from cdnjs).
"""

import json
import math
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from mvp.pipeline.features import ALL_FEATURES, FEATURE_DOCS, MARKET_FEATURES, NOT_USED
from mvp.util import json_safe

HERE = Path(__file__).resolve().parent
TEMPLATES, STATIC = HERE / "templates", HERE / "static"
ECHARTS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/echarts/5.6.0/echarts.min.js"
MODEL_NAMES = {"logit": "Logistic regression", "lgbm": "LightGBM"}


def pct(x, digits=1, signed=True):
    if x is None or x != x:
        return "–"
    sign = "+" if signed and x > 0 else ("−" if x < 0 else "")
    return f"{sign}{abs(x) * 100:.{digits}f}%"


def money(x):
    if x is None or x != x:
        return "–"
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}" if abs(x) < 10 * div else f"${x / div:.0f}{unit}"
    return f"${x:.0f}"


def num(x):
    return "–" if x is None else f"{int(x):,}"


def _row(study, group, bench, h, kind):
    return next(
        r
        for r in study["horizons"]
        if r["group"] == group and r["bench"] == bench and r["h"] == h and r["kind"] == kind
    )


def _summary(study, group, h):
    net, gross = _row(study, group, "iwm", h, "net"), _row(study, group, "iwm", h, "gross")
    return {
        "net": net["mean"],
        "lo": net["lo"],
        "hi": net["hi"],
        "n": net["n"],
        "median": net["median"],
        "share": net["share_pos"],
        "gross": gross["mean"],
    }


def roles_text(r):
    parts = []
    if r["ceo"]:
        parts.append("CEO/CFO" if r["ceo"] == 1 else f"{r['ceo']} CEO/CFO")
    if r["dir"]:
        parts.append(f"{r['dir']} director" + ("s" if r["dir"] > 1 else ""))
    if r["ten"]:
        parts.append(f"{r['ten']} 10% owner" + ("s" if r["ten"] > 1 else ""))
    return " · ".join(parts) or "Officers"


def view_model(c: dict) -> dict:
    study, model = c["study"], c["model"]
    h = c["meta"]["horizon"]
    a, b = _summary(study, "A", h), _summary(study, "B1", h)
    years_a = [y for y in study["by_year"] if y["group"] == "A" and y["mean"] is not None]
    top_year = max(years_a, key=lambda y: y["mean"]) if years_a else None

    if a["lo"] is not None and a["lo"] > 0:
        verdict = (
            f"Yes, modestly. Stocks bought by insider clusters beat small caps by "
            f"{pct(a['net'])} over the next three months, after costs."
        )
    elif a["net"] and a["net"] > 0:
        verdict = (
            f"Possibly, but not clearly. Clusters beat small caps by {pct(a['net'])} on "
            f"average, but the 95% band includes zero."
        )
    else:
        verdict = "No. After costs, clusters did not beat small caps in the pilot."
    detail = f"The typical (median) event gained {pct(a['median'])}"
    if top_year:
        detail += (
            f", and {top_year['year']} carries much of the average "
            f"({pct(top_year['mean'])} that year)"
        )
    detail += (
        f". Solo CEO/CFO purchases did about as well ({pct(b['net'])}). These numbers cover "
        "survivors only; the pre-registered 2012–2026 study will test the idea properly."
    )

    sel = model["selected"]
    res = model["results"]
    rs, rb, rc = res[sel], res["baseline"], res["constant"]
    if (
        rs["auc"]
        and rs["auc"] > max(rb["auc"] or 0, 0.5) + 0.02
        and rs["log_loss"] < rc["log_loss"]
    ):
        m_verdict = (
            "Somewhat. The model ranks 2011 events better than chance and better than "
            "market data alone."
        )
    else:
        m_verdict = (
            "Not yet. In this small pilot the insider details add little beyond market data."
        )
    n_top = round(rs["n"] / 5)
    m_detail = (
        f"On 2011 events the selected model ranked winners only slightly better than chance "
        f"(AUC {rs['auc']:.2f}); a model that sees only market data scored {rb['auc']:.2f}. "
        f"Its probabilities were no sharper than always predicting the base rate (log loss "
        f"{rs['log_loss']:.3f} against {rc['log_loss']:.3f}). The top fifth of scored events "
        f"earned {pct(rs['top_fifth_net'])} against {pct(rs['all_net'])} for all 2011 events, "
        f"but with about {n_top} events in that group the gap is fragile. The full study has "
        "about five times as many development events, plus delisted stocks."
    )
    rows = []
    for key, name, sees in (
        (sel, MODEL_NAMES[sel], "Insider + market data"),
        (
            "lgbm" if sel == "logit" else "logit",
            MODEL_NAMES["lgbm" if sel == "logit" else "logit"],
            "Insider + market data",
        ),
        ("baseline", "Market-only baseline", "Market data only"),
        ("constant", "Base rate (no skill)", "Nothing"),
    ):
        r = res[key]
        rows.append(
            {
                "name": name,
                "sees": sees,
                "auc": r["auc"],
                "log_loss": r["log_loss"],
                "brier": r["brier"],
                "hit": r.get("top_fifth_hit"),
                "top5": r.get("top_fifth_net"),
                "selected": key == sel,
            }
        )

    recent = c["screener"]
    scored = [r for r in recent if r["score"] is not None]
    funnel, prev = [], None
    for i, f in enumerate(c["funnel"]):
        funnel.append({**f, "keep": (f["n"] / prev) if (i >= 2 and prev) else None})
        prev = f["n"]
    cov = c["coverage"]
    pilot_total = sum(v["events"] for v in cov.values())
    used_total = sum(v["used"] for v in cov.values())
    return {
        "verdict": verdict,
        "verdict_detail": detail,
        "a": a,
        "b": b,
        "m": {
            "auc": rs["auc"],
            "base_auc": rb["auc"],
            "selected_name": MODEL_NAMES[sel],
            "top5": rs["top_fifth_net"],
            "all": rs["all_net"],
            "n_train": model["n_train"],
            "n_test": model["n_test"],
            "n_all": model["n_all"],
            "verdict": m_verdict,
            "verdict_detail": m_detail,
            "rows": rows,
            "base_rate": model["base_rate_all"],
            "train_years": model["train_years"],
            "test_year": model["test_year"],
        },
        "recent": {
            "total": len(recent),
            "open": sum(r["window_open"] for r in recent),
            "a": sum(r["group"] == "A" for r in recent),
            "b1": sum(r["group"] == "B1" for r in recent),
            "scored": len(scored),
        },
        "funnel": funnel,
        "used_total": used_total,
        "pilot_total": pilot_total,
        "coverage_share": used_total / pilot_total if pilot_total else 0,
        "coverage": [(g, cov[g]) for g in ("A", "B1")],
        "top_recent": sorted(
            (r for r in scored if r["window_open"]), key=lambda r: r["score"], reverse=True
        )[:6],
        "horizon_rows": {
            bench: [
                {
                    "group": g,
                    "h": hh,
                    "n": _row(study, g, bench, hh, "net")["n"],
                    "gross": _row(study, g, bench, hh, "gross")["mean"],
                    "net": _row(study, g, bench, hh, "net")["mean"],
                    "lo": _row(study, g, bench, hh, "net")["lo"],
                    "hi": _row(study, g, bench, hh, "net")["hi"],
                    "median": _row(study, g, bench, hh, "net")["median"],
                    "share": _row(study, g, bench, hh, "net")["share_pos"],
                }
                for g in ("A", "B1")
                for hh in sorted({r["h"] for r in study["horizons"]})
            ]
            for bench in ("iwm", "spy")
        },
        "cost_median": c["stats"]["cost_median"],
        "priced_tickers": c["stats"]["priced_tickers"],
    }


def _featured(c: dict, out_dir: Path) -> str | None:
    """Default company for the lookup tab: a high-scored recent event at a company with a long
    insider history, so the demo opens on a rich timeline."""
    scored = sorted(
        (r for r in c["screener"] if r["score"] is not None), key=lambda r: r["score"], reverse=True
    )[:40]
    shards: dict[int, dict] = {}
    best, best_key = None, None
    for r in scored:
        k = int(r["cik"]) % c["meta"]["shards"]
        if k not in shards:
            shards[k] = json.loads((out_dir / "data" / f"companies-{k}.json").read_text("utf-8"))
        p = shards[k].get(r["cik"]) or {}
        t = p.get("totals") or {}
        filings = (t.get("buys") or 0) + (t.get("sells") or 0)
        key = (min(len(p.get("quarters", [])), 24) >= 12, filings >= 20, r["score"])
        if best_key is None or key > best_key:
            best, best_key = r["cik"], key
    return best


def _typical(fmt: str, st: dict) -> str:
    m, mean = st.get("median"), st.get("mean")
    if m is None:
        return "–"
    match fmt:
        case "count":
            return f"{m:.0f}"
        case "log_usd":
            return money(math.exp(m))
        case "log1p_usd":
            return money(math.exp(m) - 1)
        case "share":
            return pct(m, 0, False)
        case "log_ratio":
            return f"holdings × {math.exp(m):.2f}"
        case "log_ratio_trade":
            return f"{pct(math.exp(m), 1, False)} of a day's trading"
        case "days":
            return f"{m:.1f} days"
        case "flag":
            return f"yes for {mean * 100:.0f}% of events"
        case "cost":
            return pct(m, 2, False)
        case "pct_daily":
            return f"{pct(m, 1, False)} a day"
        case _:
            return pct(m, 1)


def scoring_view(c: dict) -> dict:
    model, stats = c["model"], c["feature_stats"]
    learned = model["learned"]
    sel = model["selected"]
    logit_max = max(abs(w) for w in learned["logit"].values()) or 1
    base_vals = learned["baseline"].values()
    base_max = max((abs(w) for w in base_vals), default=1) or 1
    rows = []
    for key, label in ALL_FEATURES.items():
        plan, source, fmt, desc, how = FEATURE_DOCS[key]
        lw, gw = learned["logit"][key], learned["lgbm"][key]
        bw = learned["baseline"].get(key)
        rows.append({
            "plan": plan, "label": label, "desc": desc, "how": how, "source": source,
            "group": "Stock" if key in MARKET_FEATURES else
                     ("Insider + stock" if source == "Form 4 + prices" else "Insider"),
            "coverage": stats[key]["coverage"], "typical": _typical(fmt, stats[key]),
            "market": key in MARKET_FEATURES,
            "logit": lw, "logit_w": abs(lw) / logit_max * 100,
            "lgbm": gw, "lgbm_w": gw / max(learned["lgbm"].values()) * 100 if gw else 0,
            "base": bw, "base_w": abs(bw) / base_max * 100 if bw is not None else 0,
            "final": learned["final"][key],
        })
    used_for = {sel: f"Live scores (refitted on all {model['n_all']:,} pilot events)",
                "baseline": "Comparison: do insider details add anything?",
                "constant": "Comparison: the no-skill line"}
    other = "lgbm" if sel == "logit" else "logit"
    outputs = []
    for key, name, inputs in ((sel, MODEL_NAMES[sel], "All 19 features"),
                              (other, MODEL_NAMES[other], "All 19 features"),
                              ("baseline", "Market-only baseline", "6 stock features"),
                              ("constant", "Base rate (no skill)", "None")):
        r = model["results"][key]
        outputs.append({"name": name, "inputs": inputs, "auc": r["auc"], "log_loss": r["log_loss"],
                        "brier": r["brier"], "hit": r.get("top_fifth_hit"),
                        "top5": r.get("top_fifth_net"), "all": r.get("all_net"),
                        "used": used_for.get(key, "Comparison: candidate not selected"),
                        "selected": key == sel})
    return {"rows": rows, "not_used": NOT_USED, "outputs": outputs,
            "quantiles": model["score_quantiles"], "baseline_kind": learned["baseline_kind"],
            "selected_name": MODEL_NAMES[sel]}


def render(context: dict, out_dir: Path, mode: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"])
    )
    env.filters.update(pct=pct, money=money, num=num)
    c = dict(context)
    c["screener"] = [{**r, "roles": roles_text(r)} for r in context["screener"]]
    v = view_model(c)
    v["s"] = scoring_view(c)
    featured = _featured(c, out_dir)
    data = {k: c[k] for k in ("meta", "study", "screener", "search")}
    data["model"] = {k: c["model"][k] for k in ("selected", "results", "drivers")}
    data["featured"] = featured
    if featured:
        shard = int(featured) % c["meta"]["shards"]
        profiles = json.loads((out_dir / "data" / f"companies-{shard}.json").read_text("utf-8"))
        data["featured_profile"] = profiles.get(featured)
    data_json = json.dumps(
        json_safe(data), separators=(",", ":"), default=str, ensure_ascii=False, allow_nan=False
    )
    data_json = data_json.replace("</", "<\\/")
    html = env.get_template("index.html.j2").render(
        mode=mode,
        c=c,
        v=v,
        data_json=data_json,
        css=(STATIC / "style.css").read_text("utf-8"),
        js=(STATIC / "app.js").read_text("utf-8"),
        echarts_src="vendor/echarts.min.js" if mode == "local" else ECHARTS_CDN,
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    if mode == "local":
        (out_dir / "vendor").mkdir(exist_ok=True)
        shutil.copy2(STATIC / "vendor" / "echarts.min.js", out_dir / "vendor" / "echarts.min.js")
    return out_dir / "index.html"
