"""The dilution forecast shown by the app (026, V2-61).

The daily update makes the forecasts (FR-005, T018, V2-72: `sentinel.scoring.daily`) with the
approved model (V2-52), the frozen object the holdout test scored (V2-59), and the serving copy
holds each company's newest one (`app.daily_score`). The app reads them again whenever a new copy
is published, and shows only those of the approved model: it loads that model's identity once from
MLflow, never computes a forecast itself. The reasons are the trees' per-feature contributions
(LightGBM `pred_contrib`): how much each input moved this company's chance up or down from the
average, in the trees' log-odds."""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import date

from sentinel import config
from sentinel.scoring.daily import CURRENT_DAYS, QUESTION
from sentinel.serving.publish import MAX_TURNOVER

# plain-English names of the model's inputs and how to show their values
FEATURES = {
    "ret_1m": ("Share price change, last month", "pct"),
    "ret_3m": ("Share price change, last 3 months", "pct"),
    "ret_6m": ("Share price change, last 6 months", "pct"),
    "ret_12_1": ("Share price change over the past year", "pct"),
    "vol_21": ("Price swings, last month (yearly rate)", "pct"),
    "vol_63": ("Price swings, last 3 months (yearly rate)", "pct"),
    "vol_252": ("Price swings, last year", "pct"),
    "range_vol_21": ("Price swings from daily highs and lows, last month (yearly rate)", "pct"),
    "max_drawdown_252": ("Largest fall from a peak, last year", "pct"),
    "near_high_252": ("Price compared with its 1-year high", "pct"),
    "beta_252": ("Moves with the market (beta)", "num"),
    "idio_vol_252": ("Company-specific price swings", "pct"),
    "log_close": ("Share price", "logprice"),
    "log_addv20": ("Average value traded per day", "logmoney"),
    "zero_volume_63": ("Share of days without trading, last 3 months", "pct"),
    "sessions_listed": ("Trading days since listing", "count"),
    "close": ("Share price", "price"),
    "addv20": ("Average value traded per day", "money"),
    "market_cap": ("Market value of the company", "money"),
    "shares_outstanding": ("Shares outstanding", "count"),
    "log_market_cap": ("Market value of the company", "logmoney"),
    "book_to_market": ("Book value ÷ market value", "num"),
    "leverage": ("Liabilities ÷ assets", "num"),
    "cash_to_assets": ("Cash as a share of assets", "pct"),
    "cash_runway_years": ("Cash runway (years of losses covered)", "years"),
    "loss_making": ("Loss-making", "bool"),
    "revenue_growth": ("Revenue growth, 12 months", "pct"),
    "gross_margin": ("Gross margin", "pct"),
    "rd_intensity": ("Research spending ÷ revenue", "pct"),
    "interest_coverage": ("Operating profit ÷ interest paid", "num"),
    "current_ratio": ("Current assets ÷ current liabilities", "num"),
    "receivables_to_assets": ("Receivables as a share of assets", "pct"),
    "sbc_to_revenue": ("Stock pay to staff ÷ revenue", "pct"),
    "share_growth_12m": ("Share count change, last 12 months", "pct"),
    "issue_proceeds_to_assets": ("Cash raised from selling shares ÷ assets", "pct"),
    "months_since_report": ("Months since the last financial report", "num"),
    "n_agreement_3m": ("Material agreements (8-K 1.01), 3 months", "count"),
    "n_agreement_12m": ("Material agreements (8-K 1.01), 12 months", "count"),
    "n_acquisition_3m": ("Acquisitions or sales of assets, 3 months", "count"),
    "n_acquisition_12m": ("Acquisitions or sales of assets, 12 months", "count"),
    "n_bankruptcy_3m": ("Bankruptcy reports, 3 months", "count"),
    "n_bankruptcy_12m": ("Bankruptcy reports, 12 months", "count"),
    "n_delisting_notice_3m": ("Delisting notices, 3 months", "count"),
    "n_delisting_notice_12m": ("Delisting notices, 12 months", "count"),
    "n_unregistered_sale_3m": ("Private share sales (8-K 3.02), 3 months", "count"),
    "n_unregistered_sale_12m": ("Private share sales (8-K 3.02), 12 months", "count"),
    "n_auditor_change_3m": ("Auditor changes, 3 months", "count"),
    "n_auditor_change_12m": ("Auditor changes, 12 months", "count"),
    "n_restatement_3m": ("Restated financial statements, 3 months", "count"),
    "n_restatement_12m": ("Restated financial statements, 12 months", "count"),
    "n_exec_change_3m": ("Executive or director changes, 3 months", "count"),
    "n_exec_change_12m": ("Executive or director changes, 12 months", "count"),
    "n_late_filing_3m": ("Late-filing notices, 3 months", "count"),
    "n_late_filing_12m": ("Late-filing notices, 12 months", "count"),
    "n_offering_3m": ("Share offering filings, 3 months", "count"),
    "n_offering_12m": ("Share offering filings, 12 months", "count"),
    "n_shelf_effective_3m": ("Shelf registrations made effective, 3 months", "count"),
    "n_shelf_effective_12m": ("Shelf registrations made effective, 12 months", "count"),
    "n_activist_3m": ("Activist investor stakes (13D), 3 months", "count"),
    "n_activist_12m": ("Activist investor stakes (13D), 12 months", "count"),
    "n_8k_12m": ("Event reports (8-K), 12 months", "count"),
    "days_since_results": ("Days since the last results", "count"),
    "days_to_next_results": ("Days to the next expected results", "count"),
    "short_ratio_1m": ("Short-sale share of volume, last month", "pct"),
    "short_ratio_3m": ("Short-sale share of volume, last 3 months", "pct"),
    "short_ratio_chg": ("Change in the short-sale share", "pctpt"),
}

# What each input measures, in plain words, behind the "?" beside each factor (026 FR-027; the
# researcher, 18 Nov). Written from the code that computes it (`sentinel.features`): price,
# trading and size from the daily prices and the SEC share counts; financials from the latest SEC
# reports known on the day; events from the SEC filings of the last 3 or 12 months; short sales
# from FINRA. A test keeps one for every input.
_TWICE = (
    " The model reads it as it is and on a log scale, so it is listed twice under Every factor."
)
_EVENTS = {
    "agreement": "Event reports (form 8-K, item 1.01) announcing a material agreement, such as a "
    "loan, a merger or a deal to sell shares.",
    "acquisition": "Event reports (8-K, item 2.01) saying the company completed the purchase or "
    "sale of a business or of major assets.",
    "bankruptcy": "Event reports (8-K, item 1.03) of a bankruptcy or receivership.",
    "delisting_notice": "Event reports (8-K, item 3.01) that the exchange warned the company it "
    "breaks a listing rule, such as a share price below $1, or will delist it.",
    "unregistered_sale": "Event reports (8-K, item 3.02) of shares sold privately, without an "
    "offering registered with the SEC, often to a few large investors.",
    "auditor_change": "Event reports (8-K, item 4.01) that the company changed its auditor.",
    "restatement": "Event reports (8-K, item 4.02) that earlier financial statements can no "
    "longer be relied on and will be corrected.",
    "exec_change": "Event reports (8-K, item 5.02) of directors or senior officers leaving or "
    "joining.",
    "late_filing": "Notices that a quarterly or annual report will be late (forms NT 10-Q and "
    "NT 10-K).",
    "offering": "Filings to sell new shares: registration statements (S-1, S-3, F-1, F-3 and "
    "their amendments) and final prospectuses (424B1, 424B3, 424B4 and 424B5, leaving out bond "
    "sales).",
    "shelf_effective": "Notices that the SEC declared one of the company's registration "
    "statements effective (form EFFECT): from then on the company may sell what it registered, "
    "with a shelf registration in several sales over the years.",
    "activist": "Filings by an investor who holds more than 5% of the shares and may seek to "
    "influence the company (Schedule 13D and its amendments).",
}
ABOUT = {
    "ret_1m": "How much the share price rose or fell over the last 21 trading days (about a "
    "month), adjusted for splits and dividends.",
    "ret_3m": "How much the share price rose or fell over the last 63 trading days (about three "
    "months), adjusted for splits and dividends.",
    "ret_6m": "How much the share price rose or fell over the last 126 trading days (about six "
    "months), adjusted for splits and dividends.",
    "ret_12_1": "The price change from a year ago to a month ago (252 to 21 trading days back), "
    "adjusted for splits and dividends: the stock's longer trend, leaving out the latest month.",
    "vol_21": "How much the price swings from day to day over the last 21 trading days: the "
    "spread (standard deviation) of the daily price changes, scaled to a yearly rate. Large, "
    "steady companies are often near 20-30%; small, risky ones far above.",
    "vol_63": "The day-to-day price swings over the last 63 trading days (about three months): "
    "the spread of the daily price changes, scaled to a yearly rate.",
    "vol_252": "The day-to-day price swings over the last 252 trading days (about a year): the "
    "spread of the daily price changes, as a yearly rate.",
    "range_vol_21": "The price swings measured from each day's high and low rather than from the "
    "closing prices (Parkinson's estimate), over the last 21 trading days, as a yearly rate.",
    "max_drawdown_252": "The deepest fall from an earlier high within the last year: -60% means "
    "that at some point the price stood 60% below a peak reached earlier in the year.",
    "near_high_252": "Today's price as a share of the highest price of the last year: 100% means "
    "at its 1-year high, 30% means 70% below it (adjusted for splits and dividends).",
    "beta_252": "How strongly the price moves with the whole market (SPY, a fund holding the "
    "S&P 500) over the last year: 1 means as much as the market, 2 twice as much, 0 not at all.",
    "idio_vol_252": "The part of the price swings that the market's moves do not explain: the "
    "company's own ups and downs over the last year, as a yearly rate. It is high for small "
    "companies whose own news moves the price.",
    "log_close": "The latest closing share price." + _TWICE,
    "close": "The latest closing share price." + _TWICE,
    "log_addv20": "The average value of the shares traded per day over the last 20 trading days, "
    "in dollars: how easily the stock can be bought and sold." + _TWICE,
    "addv20": "The average value of the shares traded per day over the last 20 trading days, in "
    "dollars: how easily the stock can be bought and sold." + _TWICE,
    "zero_volume_63": "The share of the last 63 trading days (about three months) on which no "
    "shares traded at all; high for thinly traded stocks.",
    "sessions_listed": "How many trading days the stock has had a price in our data, counted up "
    "to 1,260 (about five years), so every older listing shows 1,260; low for new listings.",
    "market_cap": "The market value of the company: the share price times the shares "
    "outstanding." + _TWICE,
    "log_market_cap": "The market value of the company: the share price times the shares "
    "outstanding." + _TWICE,
    "shares_outstanding": "The number of shares the company has issued, from its latest SEC "
    "filing known on the day, adjusted for any stock split since.",
    "book_to_market": "The company's book value (its assets minus its liabilities, from its "
    "latest report) divided by its market value; above 1, the market values it below its own "
    "accounts.",
    "leverage": "Total liabilities divided by total assets, from the latest report: 0.6 means it "
    "owes 60 cents for each dollar of assets; above 1, it owes more than it owns.",
    "cash_to_assets": "Cash and cash equivalents as a share of total assets, from the latest "
    "report.",
    "cash_runway_years": "How many years the company's cash would last at its current burn: its "
    "cash divided by the cash its operations used over the last 12 months, counted up to 10 "
    "years. Only for companies whose operations use cash; those near the end of their cash "
    "often sell shares.",
    "loss_making": "Yes if the latest net income the company reported, usually for its latest "
    "quarter, was a loss.",
    "revenue_growth": "Revenue over the latest 12-month period against the 12 months before.",
    "gross_margin": "Gross profit (revenue minus the direct cost of what was sold) as a share of "
    "revenue, over the latest 12 months.",
    "rd_intensity": "Research and development spending as a share of revenue, over the latest 12 "
    "months; high for young biotech and technology companies.",
    "interest_coverage": "Operating profit divided by interest paid, over the latest 12 months: "
    "how many times the business earns its interest; below 1, it does not earn it.",
    "current_ratio": "Current assets (cash and what turns into cash within a year) divided by "
    "current liabilities (what is due within a year); below 1, more is due this year than the "
    "company has at hand.",
    "receivables_to_assets": "Money that customers owe the company (receivables) as a share of "
    "its total assets, from the latest report.",
    "sbc_to_revenue": "Pay given to staff in shares or options (stock-based compensation) as a "
    "share of revenue, over the latest 12 months; such pay adds shares over time.",
    "share_growth_12m": "How much the number of shares changed over the last year: today's count "
    "against the count known a year earlier, both adjusted for splits.",
    "issue_proceeds_to_assets": "Cash raised by selling new shares over the latest 12 months "
    "(from the cash-flow statement) as a share of total assets.",
    "months_since_report": "Months since the company filed its latest quarterly or annual report "
    "(10-Q, 10-K, 20-F or 40-F).",
    **{
        f"n_{event}_{window}m": f"{text} The number filed in the last {window} months."
        for event, text in _EVENTS.items()
        for window in (3, 12)
    },
    "n_8k_12m": "All event reports (form 8-K) the company filed in the last 12 months, whatever "
    "the event.",
    "days_since_results": "Days since the company last released its quarterly or annual results.",
    "days_to_next_results": "Days until the next results are expected: the last release plus the "
    "company's usual gap between releases (the median of its last four gaps); negative when they "
    "are overdue.",
    "short_ratio_1m": "Of the shares traded away from the exchanges and reported to FINRA over "
    "the last month, the share that were sold short (by sellers who borrowed them). Much of it is "
    "routine trading by market makers, so it is not the same as the bets held against a stock "
    "(short interest).",
    "short_ratio_3m": "The same short-sale share of the volume reported to FINRA, over the last "
    "three months.",
    "short_ratio_chg": "The last month's short-sale share minus that of the three months before "
    "it, in percentage points: positive when short selling rose.",
}


def _day(value) -> str:
    """'2026-11-12' as '12 Nov 2026'."""
    d = date.fromisoformat(str(value)[:10])
    return f"{d.day} {d:%b %Y}"


def no_share_count(card: dict, facts: dict) -> str | None:
    """Why a company in the question has no forecast when its latest row has no share count
    (V2-74): the answer cannot be measured, so the model was never trained or tested on such
    rows (`sentinel publish` serves none of their forecasts)."""
    shares = card.get("shares_outstanding")
    if not card.get("eligible_dilution") or (shares is not None and shares == shares):
        return None  # out of the question for another reason, or a count is known (not NaN)
    whose = (
        "the company files no reports with the SEC that give its share count"
        if "non_reporting" in (card.get("filer_type"), facts.get("filer_type"))
        else "no share count from the company's SEC filings is known yet"
    )
    return (
        f"No forecast: {whose}, so whether its shares rise by 10% or more cannot be measured, "
        "and the model was never tested on such companies (decision V2-74)."
    )


def _money(value) -> str:
    """$400.0 million, $10.0 million, $1.2 billion; below a million in dollars."""
    x = float(value)
    for size, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(x) >= size:
            return f"${x / size:,.1f} {word}"
    return f"${x:,.0f}"


def turnover(card: dict) -> float | None:
    """The value traded per day (`addv20`, the average of the last 20 trading days) as a multiple
    of the market value (the price times the reported share count), when both are known: how
    many times a day every share would change hands (V2-75)."""
    try:
        traded, value = float(card["addv20"]), float(card["market_cap"])
    except KeyError, TypeError, ValueError:
        return None
    if not (math.isfinite(traded) and math.isfinite(value)) or value <= 0:
        return None
    return traded / value


def share_count_doubt(card: dict) -> dict | None:
    """When the trading rules out the reported share count (V2-75: more than `MAX_TURNOVER`
    times the market value traded a day), the multiple, for the page to mark the market value
    and the share count as doubtful; otherwise None. It applies to every company, in the
    question or not."""
    times = turnover(card)
    if times is None or times <= MAX_TURNOVER:
        return None
    return {"times": round(times, 1), "limit": MAX_TURNOVER}


def implausible_count(card: dict) -> str | None:
    """Why a company in the question has no forecast when its trading rules out its share count
    (V2-75): the count is almost certainly wrong, and so are the model's inputs that use it
    (`sentinel publish` serves none of these forecasts; the log keeps them)."""
    doubt = share_count_doubt(card)
    if not card.get("eligible_dilution") or doubt is None:
        return None
    shares = card.get("shares_outstanding")
    count = f" of {float(shares):,.0f} shares" if shares is not None and shares == shares else ""
    times = f"{doubt['times']:,.0f}" if doubt["times"] >= 100 else f"{doubt['times']:.1f}"
    return (
        f"No forecast: the shares traded per day ({_money(card['addv20'])} on average over the "
        f"last 20 trading days) are worth more than {MAX_TURNOVER} times the company's market "
        f"value ({_money(card['market_cap'])}, from its reported count{count}), as if every "
        f"share changed hands {times} times a day. The share count in its SEC data is almost "
        "certainly wrong (for example, given in thousands), and so are the model's inputs that "
        "use it (decision V2-75)."
    )


def rules_failed(card: dict, rules: dict) -> list[str]:
    """The rules every question applies (`risk_params.yaml` `panel`, fixed before any model was
    built) that the company's latest row fails, in plain words with its own values (V2-73)."""
    out = []
    day = _day(card["as_of"]) if card.get("as_of") else "the latest day"
    close, floor = card.get("close"), float(rules["min_close"])
    if close is not None and close < floor:
        out.append(f"the share price is below ${floor:,.2f} (${close:,.2f} on {day})")
    trade, least = card.get("addv20"), float(rules["min_addv20_usd"])
    if trade is None:
        out.append(f"no trading was recorded over the last 20 trading days (at least "
                   f"${least:,.0f} a day is needed)")  # fmt: skip
    elif trade < least:
        out.append(f"the shares trade less than ${least:,.0f} a day (${trade:,.0f} on average "
                   f"over the last 20 trading days)")  # fmt: skip
    days, need = card.get("sessions_listed"), int(rules["min_price_history_sessions"])
    if days is not None and days < need:
        out.append(f"the shares have traded for only {int(days):,} days (at least {need} are "
                   f"needed)")  # fmt: skip
    if card.get("active_filer") is False:
        out.append(f"the company has filed nothing with the SEC in the last "
                   f"{int(rules['active_filer_months'])} months")  # fmt: skip
    return out


class Forecasts:
    """The approved model's newest forecast for every eligible company still trading, with its
    reasons, as the daily update stored them."""

    def __init__(self, p: config.Paths | None = None):
        self.p = p or config.paths()
        self._lock = threading.Lock()
        self.version: str | None = None  # the approved model's; only its forecasts are shown
        self.info: dict = {}
        self.card: dict = {}
        self.by_cik: dict[str, dict] = {}
        self.as_of: str | None = None
        self.current: set[str] = set()
        self._version = None
        self._rules: dict | None = None

    def rules(self) -> dict:
        """The rules every question applies (`risk_params.yaml` `panel`), read once."""
        if self._rules is None:
            self._rules = config.risk_params(self.p)["panel"]
        return self._rules

    def _load(self) -> None:
        from sentinel.scoring import daily  # MLflow is imported only when the app first needs it

        frozen = daily.approved(self.p)
        m = frozen["model"]
        tags = frozen["run"].data.tags
        self.version = daily.version(frozen)
        self.info = {
            "model": "LightGBM (gradient-boosted trees), Platt-calibrated, five bands",
            "approved": "V2-52 (5 Nov 2026)",
            "frozen_run": frozen["run"].info.run_id,
            "commit": frozen["commit"][:7],
            "data_hash": frozen["data_hash"],
            "export_date": frozen["export_date"],
            "trained_through": m.trained_through,
            "cutoff": str(m.calibrator.cutoff.date()),
            "features": len(m.features),
            "frozen_tag": tags.get("frozen", ""),
        }
        path = self.p.root / "docs" / "report" / "model_card.json"
        self.card = json.loads(path.read_text(encoding="utf-8"))["dilution"]

    def refresh(self, con) -> None:
        """Read the forecasts again when a new serving copy has been published."""
        version = os.stat(self.p.serving_db).st_mtime_ns
        if version == self._version:
            return
        with self._lock:
            if version == self._version:
                return
            if self.version is None:
                self._load()
            current = con.execute(
                "select cik from app.company_card where as_of >= "
                "(select max(as_of) from app.company_card) - ?::integer",
                [CURRENT_DAYS],
            ).fetchall()
            rows = con.execute(
                "select cik, as_of, forecast_val, band, extra_json from app.daily_score "
                "where question = ? and model_version = ?",
                [QUESTION, self.version],
            ).fetchall()
            # one dict swapped in whole, so a page read during a refresh sees one day's forecasts
            self.by_cik = {
                str(cik): {
                    "chance": float(chance),
                    "band": int(band),
                    "band_name": json.loads(extra)["band_name"],
                    "as_of": as_of.isoformat(),
                    "extra": extra,  # the reasons, read when the company's page is asked for
                }
                for cik, as_of, chance, band, extra in rows
            }
            self.as_of = max((f["as_of"] for f in self.by_cik.values()), default=None)
            self.current = {str(r[0]) for r in current}
            self._version = version

    @staticmethod
    def factors(extra: str) -> list[dict]:
        """Every input of a forecast (its `extra_json`) in plain words, the largest contribution
        first, each with what it measures (`about`, FR-027)."""
        out = []
        for f, value, effect in json.loads(extra)["factors"]:
            label, kind = FEATURES.get(f, (f, "num"))
            out.append({"feature": f, "label": label, "kind": kind, "value": value,
                        "effect": effect, "about": ABOUT.get(f)})  # fmt: skip
        return out

    def for_company(self, cik: str, card: dict, listed: bool, facts: dict | None = None) -> dict:
        """The forecast, or why there is none (FR-004; the reasons checked by the named cases,
        T019): `facts` as `data.company` gives them (filer type, blank-check, prices, fund)."""
        f = self.by_cik.get(cik)
        if f is not None:
            out = {"available": True, **{k: v for k, v in f.items() if k != "extra"},
                   "factors": self.factors(f["extra"])}  # fmt: skip
            if card.get("as_of") and f["as_of"] < str(card["as_of"])[:10]:
                out["stale"] = True  # the latest update made no forecast: shown with its date
            return out
        facts = facts or {}
        if card.get("foreign_filer") or facts.get("filer_type") == "foreign":
            reason = (
                "No forecast for foreign companies: they report their share counts differently "
                "(annual 20-F reports instead of quarterly 10-Q), so the model cannot follow "
                "them (decision V2-27)."
            )
        elif facts.get("is_blank_check"):
            reason = (
                "No forecast for blank-check companies: a shell company without a business of its "
                "own is left out of every question until it merges with one (decision V2-66)."
            )
        elif not listed:
            reason = "No forecast: the company's shares no longer trade."
        elif not facts.get("has_prices", True):
            reason = (
                "No forecast: our data has no share prices for this company, and the model "
                "needs them."
            )
        elif cik not in self.current:
            reason = "No forecast: the company's shares have no recent price in our data."
        elif card.get("excluded") or facts.get("is_fund"):
            reason = "No forecast: funds, trusts and similar vehicles are outside this question."
        elif uncounted := no_share_count(card, facts):
            reason = uncounted
        elif implausible := implausible_count(card):
            reason = implausible
        elif card.get("eligible_dilution"):
            reason = (
                "No forecast yet: the daily update has not made one for this company (the "
                "forecasts are made every weekday)."
            )
        elif failed := rules_failed(card, self.rules()):
            rule = "a rule" if len(failed) == 1 else "rules"
            reason = (
                f"No forecast: {'; '.join(failed)}. The forecasts leave out such companies "
                f"({rule} fixed before any model was built)."
            )
        else:
            reason = (
                "No forecast: the data needed (recent share counts and financial reports) is not "
                "complete for this company."
            )
        return {"available": False, "reason": reason}
