# 02 – Now–Next–Future roadmap

## NOW: the capstone, 22 October – 18 November 2026

The weeks follow plan §9.3, Thursday to Wednesday. **Critical path: Step 6 → Step 7 → the lock.** Delisted-stock prices gate everything after them, so the Tiingo month starts with the price pull on Thursday 29 October.

| Week | Dates | Builds | Checkpoint at the end of the week |
|---|---|---|---|
| 1 | 22–28 Oct | ✅ E1 Steps 0–5: data download, staging, entities, gates, preliminary events · E1 Step 6: symbol map, filing headers, D45 check · feature 002 wrap-up and merge to `main` · design of E2 | Event counts known ✅; audit sheets back from the researcher; every event company mapped or listed as unmatched; Tiingo candidate list ready |
| 2 | 29 Oct – 4 Nov | E2 prices, final events, delistings · E3 financials and costs · E8 stock lookup (parallel track) · **pre-registration lock** | Price coverage ≥ 90% reported; golden set checked; `prereg-v1` tagged and pushed on 4 Nov |
| 3 | 5–11 Nov | E4 labels and features · E5 event study · E6 ML tournament | Event-study results frozen (9 Nov) before ML; model selected (11 Nov) |
| 4 | 12–18 Nov | E7 holdout (once) and production refit · E8 screener and model card with P1–P8 · E9 robustness, offline rebuild, report | Holdout evaluated (12 Nov); product demo (16 Nov); report handed in (18 Nov) |

**After hand-in:** delete all Tiingo data when the paid month ends (about 28 November), and log the deletion.

**Weekends** (24–25 Oct, 31 Oct – 1 Nov, 7–8 Nov, 14–15 Nov) are buffer, and are worked when the schedule needs them (decided 23 Oct; [04](04-effort-prioritization.md)).

## NEXT: month 2 (after the capstone)

Builds trust and freshness on the finished study.

- **Daily EDGAR ingestion**, if it was cut: new Form 4s within a day, so the screener is current (user research row 7).
- **Forward test of live scores**: evaluate the clusters scored in November once their 63-session windows close, from about February 2027 (row 13).
- **Alerts or a monthly digest** for a watch-list, once daily data exists (row 14).
- **CSV export and an OTC filter**, if they were not built as Could items (rows 12, 15).
- **B2 and H2b**, if B2 was cut.

## FUTURE: month 3 and beyond

Expansion, only if the study finds a signal worth productising.

- Near-real-time filings (EDGAR feeds) and push alerts for active traders.
- Insider *selling* signals, and short ideas.
- Broker availability for non-US investors; translations.
- A licensed price source that allows public display of prices and scores (plan §8.6, licensing).
- Monetisation, tested on real willingness to pay rather than the synthetic answers.
