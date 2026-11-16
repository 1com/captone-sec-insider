# Demo path (about 5 minutes)

> **16 Nov: no fixed path.** The researcher shows the app freely ("ill show them around, click a few
> stocks"). The companies below stay as checked examples, not a script.

The live part of the presentation (019, User Story 2). Every step names what to point at, never an
exact chance or price: the data change every weekday. Numbers quoted aloud come from the number
sheet (`docs/presentation/numbers.md`) by id.

## Before the talk

- Open http://localhost:8100 in the browser that will be shown, sign in, and reload with Ctrl+F5
  so the newest page script is used. Zoom so the page reads from the back of the room (125%).
- Check the landing page's "Data current to" date, then open each company below once.
- The day before and the morning of the presentation, walk the path with a clock. A company that
  no longer shows what its step needs is replaced by its spare: in particular, check step 4's spare
  (its price was close to $1).
- Keep the backup screenshots (`data/handin/backup/`, this computer only: the app's charts can use
  the private price source) open in a second window.
- The daily update runs on weekdays from 10:00 for about 50 minutes (three hours on 16 Nov, the SEC
  being slow); the app keeps serving, but check it is up before starting if the talk falls in that
  time.

## The path

| Step | Time | Company (spare) | Open | Point at | Say |
|---|---|---|---|---|---|
| 1 | 0:30 | Landing page | http://localhost:8100 | "Data current to", the list of the highest chances, the search box | Every weekday at 10:00 the platform reads the new filings and prices and makes a forecast for each company still trading: these are today's highest chances of a 10%+ rise in shares within six months. |
| 2 | 1:30 | Alaunos Therapeutics, TCRT, CIK 1107421 (Treasure Global, TGL, CIK 1905956) | click it in the top list, or search "Alaunos" | the chance and its band; "How often companies in this band diluted": the test years and the one-time test; "Main reasons"; the share-sale markers on the price chart | A small biotech that recently sold shares: band 5. On the one-time test, band 5 companies diluted 42% of the time (`dil.band5.real`). The reasons are the model's own: each input's push up or down; here its small market value and its recent share sales. |
| 3 | 1:00 | Apple, AAPL, CIK 320193 (Microsoft, MSFT, CIK 789019) | search "Apple" | band 1; the insider chart with pre-planned sales hidden and shown; the filings with their plain-English names | A large company in the lowest band. Insiders sell often, mostly under pre-planned programmes; every filing is explained in plain words. (With Microsoft say "many" instead of "mostly".) |
| 4 | 0:30 | Hyperscale Data, GPUS, CIK 896493 (PDS Biotechnology, PDSB, CIK 1472091) | search "GPUS" | the dilution panel's reason: the rule, the company's price and its date | No forecast, and the page says why: shares below $1 are left out by a rule fixed before any model was built, so the model was never tested on them. This company filed a dozen share-sale documents in the last year, and still the page does not guess. |
| 5 | 0:45 | MGP Ingredients, CASK, formerly MGPI, CIK 835011 (Viavi, VIAV, formerly JDSU, CIK 912093) | search "MGP" (the old ticker is not searchable) | the price chart over all years: it starts in 2010 | It changed its ticker from MGPI to CASK on 5 Nov 2026; the page shows today's ticker only. Before our repair a ticker change cut the history: this company kept two days of sixteen years. |
| 6 | 0:45 | step 2's company | Diagnostics: "How the dilution forecast works" | the one-time test's table and its calibration | The same frozen model, scored once on the answers from 2023 on, which it had never seen: these are the numbers from the slides. |

## Checked on the data of 16 Nov (to 13 Nov 2026)

The live app at http://localhost:8100 on 16 Nov (T011); no chance or price is written here.

| Step | Company | What its step needs, as found |
|---|---|---|
| 1 | Landing page | data current to 13 Nov 2026 for prices, filings, insider filings, short sales and financials; 3,682 forecasts; the top 15 all in band 5, Treasure Global first, Alaunos second |
| 2 | Alaunos (TCRT) | band 5; prices from Yahoo since 2010; main reasons: market value, company-specific price swings, private share sales (8-K item 3.02) in the last 3 months, offering filings in the last 12; share-sale markers in the last year (S-3, 8-K); the one-time test's record in the band panel; its price well above $1 |
| 2 spare | Treasure Global (TGL) | band 5; prices from Yahoo since its listing in August 2022; private share sales and offering filings among its main reasons; its price well above $1 |
| 3 | Apple (AAPL) | band 1; 481 insider sales, 350 of them pre-planned (10b5-1); 94 filings in the last year, each with a plain-English name |
| 3 spare | Microsoft (MSFT) | band 1; 705 insider sales, 263 of them pre-planned |
| 4 | Hyperscale Data (GPUS) | no forecast; the page names the $1 rule with the company's price and its date; its price far below $1; 12 share-sale markers in the last year (424B5, S-3, 8-K, S-8) |
| 4 spare | PDS Biotechnology (PDSB) | no forecast, the same rule; its price close to $1, so it may get a forecast on a good day |
| 5 | MGP Ingredients (CASK) | prices from Yahoo from 4 Jan 2010 to 13 Nov 2026 in one chart. Yahoo's new CASK series lacks 9-11 Nov 2026 and the chain does not take those days from MGPI's rows: a three-day hole, not visible on the chart (noted for after the hand-in) |
| 5 spare | Viavi (VIAV) | prices from 4 Jan 2010; the page lists its former name JDS Uniphase |
| 6 | every page | the one-time test's record (results, bands, rows, dates) from the model card |

Changed from the plan's candidates:
- BioVie (BIVI) is no longer step 2's spare, because its prices come from the private source; every
  demo company's chart now comes from Yahoo.
- Step 4's main company and its spare were swapped: Hyperscale Data's price is far below $1, while
  PDS Biotechnology's is close to it.

## If the app fails

Say so in one sentence and show the backup screenshot of each step in the same order; the talk's
time does not change.
