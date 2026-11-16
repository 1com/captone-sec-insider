# Demo path (about 5 minutes)

The live part of the presentation (019, User Story 2). Every step names what to point at, never an
exact chance or price: the data change every weekday. Numbers quoted aloud come from the number
sheet (`docs/presentation/numbers.md`) by id.

## Before the talk

- Open http://localhost:8100 in the browser that will be shown, sign in, and reload with Ctrl+F5
  so the newest page script is used. Zoom so the page reads from the back of the room (125%).
- Check the landing page's "Data current to" date, then open each company below once.
- The day before and the morning of the presentation, walk the path with a clock; a company that
  no longer shows what its step needs is replaced by its spare.
- Keep the backup screenshots (`data/handin/backup/`, this computer only: the price charts use
  the private price source) open in a second window.
- The daily update runs on weekdays from 10:00 for about 50 minutes; the app keeps serving, but
  check it is up before starting if the talk falls in that hour.

## The path

| Step | Time | Company (spare) | Open | Point at | Say |
|---|---|---|---|---|---|
| 1 | 0:30 | Landing page | http://localhost:8100 | "Data current to", the list of the highest chances, the search box | Every weekday at 10:00 the platform reads the new filings and prices and makes a forecast for each company still trading: these are today's highest chances of a 10%+ rise in shares within six months. |
| 2 | 1:30 | Alaunos Therapeutics, TCRT, CIK 1107421 (BioVie, BIVI, CIK 1580149) | search "Alaunos" | the chance and its band; "How often companies in this band diluted": the test years and the one-time test; "Main reasons"; the share-sale markers on the price chart | A small biotech that recently sold shares: band 5. On the one-time test, band 5 companies diluted 42% of the time (`dil.band5.real`). The reasons are the model's own: each input's push up or down. |
| 3 | 1:00 | Apple, AAPL, CIK 320193 (Microsoft, MSFT, CIK 789019) | search "Apple" | band 1; the insider chart with pre-planned sales hidden and shown; the filings with their plain-English names | A large company in the lowest band. Insiders sell often, mostly under pre-planned programmes; every filing is explained in plain words. |
| 4 | 0:30 | PDS Biotechnology, PDSB, CIK 1472091 (Hyperscale Data, GPUS, CIK 896493) | search "PDS" | the dilution panel's reason | No forecast, and the page says why: a rule fixed before any model was built leaves out shares below $1. |
| 5 | 0:45 | MGP Ingredients, CASK, formerly MGPI, CIK 835011 (Viavi, VIAV, formerly JDSU, CIK 912093) | search "MGP" | the price chart over all years: the history from 2010 runs across the ticker change of 5 Nov 2026 | Before our repair a ticker change cut the history: this company kept two days of sixteen years. |
| 6 | 0:45 | step 2's company | Diagnostics: "How the dilution forecast works" | the one-time test's table and its calibration | The same frozen model, scored once on the answers from 2023 on, which it had never seen: these are the numbers from the slides. |

## If the app fails

Say so in one sentence and show the backup screenshot of each step in the same order; the talk's
time does not change.
