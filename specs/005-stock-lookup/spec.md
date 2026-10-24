# Feature Specification: Stock Lookup (Product v1, page 2)

**Feature Branch**: `005-stock-lookup`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "Feature 005: product v1 stock lookup (plan §8.6 page 2 and API; planning task 8.1, due Wed 4 Nov 2026; user-research row 11, presentation rules P6 freshness and P7 plain-English labels from docs/planning/06-user-research-response.md). A small read-only web app on the warehouse. A user searches by ticker or company name and opens a company page showing: every insider transaction with each code explained in plain English, date, insider, role at the time, shares, price, value, direct or indirect holding, and a link to the filing on EDGAR; holdings over time for each insider; the company's insider-buying events (A, B1, B2) with signal date, buyers and total value, without realised outcomes; a data-as-of date and a glossary. API endpoints: search, and a company's transactions. No Yahoo or Tiingo prices or price-derived values; SEC data only; never writes to the warehouse; runs locally on a free port; endpoint tests on a synthetic warehouse; one test per applicable presentation rule (P6, P7). Out of scope: screener, scores, model card, daily ingestion, public deployment, charts."

## User Scenarios & Testing *(mandatory)*

The users are the retail investors described in the plan (§8.6) and the user research (docs/planning/06): people who know a company and want to see what its insiders have done, without knowing what a Form 4 is. In the user research, long-term investors valued this page most (row 11).

### User Story 1 - Find a company and read its insider transactions (Priority: P1)

A user types a ticker ("PYPL"), a company name ("paypal") or a CIK, picks the company from the matches, and sees every insider transaction at that company, newest first. Each row says, in plain words, what happened ("Bought shares on the open market", "Received shares as pay", "Exercised options"), when it was traded and filed, who did it and their role at the time (director, CEO …), how many shares, at what reported price and value, whether the shares are held directly or through a trust or fund, and links to the filing on EDGAR. The page states how current the data is.

**Why this priority**: This is the page's purpose and the part users asked for. It needs only SEC insider data that already exists, so it delivers value on its own.

**Independent Test**: With a small synthetic warehouse, search for a company by ticker, by name and by CIK; open its page; check that every transaction appears with its plain-English description, role, values, holding type, filing link and the data-as-of date.

**Acceptance Scenarios**:

1. **Given** the warehouse holds PayPal's filings, **When** the user searches "PYPL", **Then** PayPal Holdings, Inc. is listed with its CIK, and opening it shows its insider transactions, newest filing first.
2. **Given** a transaction with code P, **When** it is shown, **Then** it reads as an open-market purchase in plain English, never only as "P".
3. **Given** David Dorman's purchase of 23 November 2021, **When** it is shown, **Then** the row gives 23 Nov 2021, "DORMAN DAVID W", director, 495 shares at $186.47, $92,302.65, held indirectly by "2021 Family Trust 1", and a working link to accession 0001633917-21-000185 on EDGAR.
4. **Given** any page of the lookup, **When** it is shown, **Then** it states the data-as-of date (the newest filing date in the data and the SEC data set it comes from).
5. **Given** a company with thousands of transactions, **When** its page opens, **Then** the newest transactions appear first and the rest can be reached page by page.

---

### User Story 2 - See each insider's holdings over time (Priority: P2)

On the company page, the user sees, for each insider, how many shares they held after each of their filings, so they can tell whether an insider has been building or cutting a stake.

**Why this priority**: Holdings put single trades in context (a $100,000 purchase means more if it doubles a stake). The plan lists it on the lookup page, but transactions come first.

**Independent Test**: In the synthetic warehouse, an insider with several filings, including holdings split across direct and trust accounts, shows one holding figure per filing date that equals the sum over their accounts.

**Acceptance Scenarios**:

1. **Given** an insider with filings on several dates, **When** the user views their holdings, **Then** one row per filing date shows the shares held afterwards, oldest to newest.
2. **Given** a filing in which the insider holds shares directly and through trusts, **When** holdings are shown, **Then** the figure for that date adds up all of the insider's holdings reported in that filing, and the split by account is visible.

---

### User Story 3 - See the company's insider-buying events (Priority: P2)

The company page lists the dates on which the company's insiders bought in a way the study counts as an event: a cluster (two or more separate buyers, at least one an officer or director, $100,000 or more within 14 days), a CEO or CFO buying alone, or another officer or director buying alone. Each event shows its date, kind, buyers with their roles, and total value, explained in plain English.

**Why this priority**: It connects the lookup to the research, and the screener will reuse it. It depends on the transaction view being right.

**Independent Test**: In the synthetic warehouse, a company with a two-director cluster and a solo CEO purchase shows both events with the right kind, date, buyers and value.

**Acceptance Scenarios**:

1. **Given** PayPal's cluster of 23 November 2021, **When** the user views PayPal's events, **Then** it appears as a cluster of 2 buyers (both directors) worth $2,287,696.69, with the two filings listed.
2. **Given** any event, **When** it is shown, **Then** no return, outcome or "did it work" figure appears.
3. **Given** a company with no insider-buying events, **When** its page opens, **Then** the events section says so in plain words.

---

### User Story 4 - Understand the words (Priority: P3)

A user who meets an unfamiliar term (Form 4, open-market purchase, 10% owner, indirect holding, cluster, signal date) can read a short plain-English explanation from the page.

**Why this priority**: The user research found jargon to be a barrier (row 6, rule P7). The code descriptions in Story 1 cover most of it; the glossary covers the rest.

**Independent Test**: Every term the pages use from a fixed list has a glossary entry reachable from the page.

**Acceptance Scenarios**:

1. **Given** the company page, **When** the user opens the glossary, **Then** it explains every transaction code that can appear, the roles, direct and indirect holdings, the three event kinds and the data-as-of date.

---

### User Story 5 - Get the same data programmatically (Priority: P3)

A technically minded user or the later screener asks the app for matching companies and for a company's transactions as structured data instead of a web page.

**Why this priority**: The plan names these two endpoints (§8.6), and the screener and tests use them; most users will use the pages.

**Independent Test**: Requests for a search and for a company's transactions return the same companies and transactions as the pages, with the plain-English code description included.

**Acceptance Scenarios**:

1. **Given** the search endpoint, **When** asked for "paypal", **Then** it returns PayPal's CIK, name and tickers.
2. **Given** the transactions endpoint for CIK 1633917, **When** called, **Then** it returns the company's transactions with the same fields as the page, newest first, a page at a time.

### Edge Cases

- **A ticker used by several companies over time** (tickers are reused): every match is listed, with name, CIK and the years each used the ticker, so the user picks the right one.
- **Companies that no longer trade** can be found by their old ticker (for example SIVB) or name.
- **A company with no insider transactions** in the data, or a CIK that does not exist: a plain message, not an error page.
- **Very short or empty searches**: no search below 2 characters; a hint is shown instead.
- **Amended, Form 3 and Form 5 filings**: shown with their form type, so a correction is not mistaken for a new trade.
- **Missing or implausible reported values**: shown exactly as filed ("not reported" when empty), with a note that prices and values are as reported by the filer and can contain errors. No market price is used to check or correct them.
- **Transactions with footnotes**: the footnote text is available from the row, because it often explains the price (weighted average) or the holding.
- **Very large histories** (up to about 76,000 transaction lines for one company): shown in pages, newest first, without slowing the page.
- **Insiders with several roles** (director and 10% owner): the role at the time of each filing is shown, with every flag.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to search companies by ticker (current or past, as recorded in the SEC data), by part of the company name, and by CIK, and see the matching companies with name, CIK and tickers.
- **FR-002**: The company page MUST list every non-derivative insider transaction at the company in the SEC data (all forms and transaction codes), newest filing first, in pages.
- **FR-003**: Every transaction row MUST show: trade date, filing date, form type, insider name, the insider's role(s) at the filing date, the plain-English description of the transaction code, acquired or disposed, shares, reported price, value (shares × reported price), shares held afterwards, direct or indirect holding with the holder's description, and a link to the filing on EDGAR.
- **FR-004**: Every transaction code that occurs in the data MUST have a plain-English description; a raw code MUST NOT appear without its description (rule P7).
- **FR-005**: The footnotes a transaction cites MUST be readable from its row.
- **FR-006**: The company page MUST show each insider's shares held after each filing, summed over all their holdings in that filing, with the split by holding available.
- **FR-007**: The company page MUST list the company's insider-buying events defined from SEC filings alone (clusters, solo CEO/CFO purchases, solo officer or director purchases), each with signal date, kind, buyers and roles, total value and member filings.
- **FR-008**: No returns, outcomes, labels, scores or hit rates of any event MUST be shown or served.
- **FR-009**: No market price, and no value computed from market prices (Yahoo or Tiingo), MUST be shown or served; prices shown MUST be those reported on the filings.
- **FR-010**: Every page and every structured response MUST state the data-as-of date: the newest filing date in the data and the SEC data set it belongs to (rule P6).
- **FR-011**: A glossary MUST explain, in plain English, every transaction code that can appear, the roles, direct and indirect holdings, form types, the three event kinds and the data-as-of date.
- **FR-012**: The app MUST provide a company search and a company-transactions endpoint returning structured data with the same content as the pages, including code descriptions and the data-as-of date.
- **FR-013**: The app MUST open the warehouse read-only and never change it.
- **FR-014**: The app MUST start with one command on this machine, on a port that does not clash with the other local app on port 8000.
- **FR-015**: Searches and pages MUST behave sensibly for edge cases: no results, unknown CIK, short queries and very long histories, with plain messages instead of errors.

### Key Entities

- **Company (issuer)**: identified by its CIK; has a name and the tickers it has used, with the years each was used.
- **Insider (reporting owner)**: identified by their CIK; has a name, and at each filing date one or more roles at the company (director, officer with title, CEO/CFO, 10% owner, other).
- **Filing**: one SEC form (3, 4, 5 or an amendment) with an accession number, filing date and link to EDGAR.
- **Transaction**: one line of a filing: trade date, code, shares, reported price, acquired or disposed, shares held afterwards, holding type and holder, cited footnotes.
- **Holding snapshot**: an insider's shares held after a filing, per holding and in total.
- **Insider-buying event**: a date on which the company's clean purchases meet one of the three event definitions, with its member filings, buyers and total value.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from typing a ticker to reading that company's newest insider transactions in under 10 seconds, with search results appearing within 1 second of typing.
- **SC-002**: A company page with the largest history in the data (about 76,000 transaction lines) opens in under 2 seconds on this machine.
- **SC-003**: 100% of the transaction codes in the data have a plain-English description, checked by an automated test against every code present.
- **SC-004**: 100% of pages and structured responses state the data-as-of date, checked by an automated test.
- **SC-005**: Zero market prices or price-derived values are served: an automated test confirms that no page or response contains market-price data.
- **SC-006**: Every transaction shown links to its filing on EDGAR; a sample of 20 links checked by hand all open the right filing.
- **SC-007**: For the PayPal example (CIK 1633917), the page shows the two filings of the 23 November 2021 cluster, the event itself, and Dorman's holdings of 44,890 before and 46,437 after, matching the original filings.

## Assumptions

- **Events shown are the SEC-only (preliminary) events.** The study's final events also depend on price floors computed from Yahoo and Tiingo prices; showing them would put price-derived, and for delisted companies Tiingo-derived, values in the product (constitution VI). The page explains that the research applies further checks.
- **Derivative transactions** (options, warrants: Table II of Form 4) are not listed in this feature; option exercises still appear on the share side (code M). Listing Table II is a later addition.
- **Roles** are those of the insider at the filing date, as already built for the study (point-in-time roles); entities (merged co-filers) are used only inside the events section.
- **Data freshness** is that of the quarterly SEC data sets (currently through 30 September 2026); daily ingestion is a separate *Should* item.
- **Local use only**: one user on this machine, no sign-in, no public deployment (licensing review comes before any launch, plan §8.6). The default port is 8766: 8000 belongs to another local app and the MVP uses 8765 (research R10).
- **Performance targets** assume the warehouse on this machine's local disk and the memory limits already used for the project.
- **No testing with real people** (researcher's decision, 23 Oct): the presentation rules are checked by automated tests.
- **Dependency**: the warehouse tables built by features 002 and 004 (filings, transactions, roles, entities, preliminary events, footnotes, issuer profiles); the web stack named in the constitution (server-rendered pages, read-only).
