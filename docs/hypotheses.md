# Hypotheses for the three models

**Status: approved by the researcher on 4 November 2026 (V2-46), before the clean re-runs of 005,
006 and 007** (V2-40, V2-41). Each model notebook ends with a verdict per hypothesis, rather than an
explanation found after the results; the report quotes the verdicts as they came out.

## Why hypotheses in a forecasting project

The three questions are forecasts ("what will volatility be?"), not tests of a cause ("do insider
purchases raise returns?", v1's study). A forecast is judged by its accuracy on years it never saw,
and the pre-registration already fixes what protects against fooling ourselves: the answers
(`config/risk_params.yaml`), the walk-forward test years 2019–2022, the baselines and the
one-standard-error rule (D60). What was missing is *why* each family of features should help.
Written down first, the reasons make the models explainable, guard against patterns that hold by
chance, and give the report its scientific claims: which mechanisms carry information about the
future, out of sample.

## How each hypothesis is tested

- **Family check** (D60): the chosen model is refitted without the family on every walk-forward
  fold (2019–2022), with the same settings and seeds. The family **adds** if the deciding measure
  gets worse, averaged over the four test years, by more than one standard error of the four
  yearly differences; it **adds nothing** otherwise. Deciding measures: log error for volatility
  (005), the log loss of the 5%/10%/20% chances for the results move (V2-41), log loss for
  dilution (V2-37). Where a hypothesis names single features inside a family, those features are
  removed as a group the same way.
- **Direction check**: the rank correlation between the hypothesis' key feature and the answer, in
  each test year separately; the expected sign in at least three of the four years.
- **Verdict**: *supported* (adds, right direction), *not supported* (adds nothing), or *opposite*
  (the direction is reversed). Hypotheses that expect no effect are supported when the family
  adds nothing.
- **Honest limits**: the EDA (004) has already shown how features relate to the answers in
  2012–2022, so these hypotheses are informed, not blind, on those years. Four test years give
  little statistical power: a family can matter and still fall within one standard error. The
  blind check is the holdout test (010) on 2023 onward, run once.

## Volatility (005): the annualised volatility of the next three months

| # | Family | Mechanism | Expected | Test |
|---|---|---|---|---|
| H-V1 | price: past volatility | Turbulence persists, but drifts back toward normal: a calm stock stays fairly calm, a wild one calms somewhat | higher past volatility, higher future volatility; the slope of log future on log past below 1 (EDA: 0.78) | the mean-reversion rule beats the naive baseline in the test years; the slope |
| H-V2 | size and trading | Small and thinly traded companies swing more than their own past suggests: fewer buyers and sellers, less news coverage | smaller or less traded, higher volatility | family check (size and trading together) |
| H-V3 | financials | Fragile companies (losses, little cash, weak interest coverage) react more to any news | loss-making or low interest coverage, higher volatility | family check (financials) |
| H-V4 | macro | Market-wide fear moves every stock: the regime shifts volatility up or down for all | rising VIX or market volatility, higher future volatility | family check (macro) |
| H-V5 | insider, short volume | No clear mechanism for a stock's overall volatility beyond the families above | no effect | family check: adds nothing |
| H-V6 | all, combined | Combining the company's features improves on the one-line mean-reversion rule | the model beats the rule by more than one standard error | the level comparison under the one-standard-error rule |

## Results-day move (006): the move beyond the market on the results day

| # | Family | Mechanism | Expected | Test |
|---|---|---|---|---|
| H-R1 | the company's history (`prev4_mean`, `n_prev`) | Some companies habitually surprise the market; their history repeats | larger past moves, larger next move | the baseline ranks the moves (rank correlation above 0); family check (history) |
| H-R2 | price: volatility | A stock that is volatile on ordinary days is also volatile on its results day, beyond its own results history | higher idiosyncratic volatility, larger move | family check (price) |
| H-R3 | size and trading | Small companies are followed by fewer analysts, so their results surprise more | smaller, larger move | family check (size and trading) |
| H-R4 | financials | Loss-making and cash-poor companies' results are more uncertain | loss-making, larger move | family check (financials) |
| H-R5 | macro | In fearful markets investors react more strongly to any news | higher VIX, larger move | family check (macro) |
| H-R6 | insider, short volume | No clear mechanism for the size of a results move | no effect | family check: adds nothing |

## Dilution (007): shares outstanding up 10% or more within six months

| # | Family | Mechanism | Expected | Test |
|---|---|---|---|---|
| H-D1 | filing events: offerings | A registration, a shelf that became effective or an unregistered sale is permission and intent to sell new shares | an offering filing in the last 12 months, higher chance | the offering rule beats the base rate in every test year; family check (filing events) |
| H-D2 | financials: need | A company losing money with little cash left must raise money, and selling shares is often its only way | loss-making or under a year of cash, higher chance | group check (cash runway, loss-making, cash share, R&D, stock-based pay) |
| H-D3 | financials: habit | A company that issued shares recently keeps issuing (programs, warrants, at-the-market sales) | higher share growth over 12 months, higher chance | group check (share growth, issue proceeds) |
| H-D4 | size and price | Small, cheap, volatile stocks dilute more: their capital needs are large relative to their value | smaller or more volatile, higher chance | family check (size and price) |
| H-D5 | insider, short volume, macro | No clear mechanism beyond the company's own need and permission | no effect | family check: adds nothing (already found for insider and macro, V2-36) |
