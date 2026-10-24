# Contract: HTTP pages and JSON endpoints

Served by `sentinel serve` at `http://127.0.0.1:8766`. All routes are `GET`; nothing changes server state. Every HTML page shows the data-as-of line; every JSON body has `data_as_of` (rule P6).

## Pages

| Route | Returns | Notes |
|---|---|---|
| `/` | Search page | A GET form `q`; with HTMX, results update as the user types (`/search`) |
| `/search?q=` | Result list | HTML fragment for HTMX requests (`HX-Request` header); the full page otherwise. `q` shorter than 2 characters → a hint, no query |
| `/company/{cik}` | Company page | Header (name, CIK, tickers with years), data-as-of, events, insiders, first page of transactions, glossary link. Unknown CIK → 404 page with a plain message |
| `/company/{cik}/transactions?page=N` | Transactions page N | Fragment for HTMX, full page otherwise. 100 rows per page, newest filing first; page out of range → empty list with a message |
| `/company/{cik}/insider/{owner_cik}` | One insider's holdings over time | Fragment for HTMX, full page otherwise; one row per filing date and security title (direct, indirect, total), joint co-filers named |
| `/filing/{accession}/footnotes?ids=F1,F2` | Footnote text | Fragment; unknown ids are skipped |
| `/glossary` | Glossary | Every code, form type, role, holding type, event kind and the data-as-of date |
| `/static/…` | CSS and the vendored `htmx.min.js` | |

**Transaction row (page and JSON)**: trade date, filing date, form (with description), insider name(s) with role(s) at the filing date, code with its plain-English description, acquired or disposed, shares, reported price, value, shares held afterwards, direct or indirect (with the holder), footnote marker, EDGAR link.

**Wording rules**: a transaction code is never shown without its description (rule P7). Prices and values carry the note "as reported by the filer". No page shows a market price, a return, an outcome or a score.

## JSON

### `GET /api/issuers/search?q=`

```json
{
  "data_as_of": {"date": "2026-09-30", "dataset": "2026q3"},
  "query": "paypal",
  "results": [
    {"cik": "1633917", "name": "PayPal Holdings, Inc.",
     "tickers": [{"ticker": "PYPL", "first_year": 2015, "last_year": 2026}],
     "n_transactions": 1234, "first_filing": "2015-06-29", "last_filing": "2026-09-15"}
  ]
}
```

- At most 25 results, ordered as in research R7. `q` under 2 characters → `400` with `{"detail": "query too short"}`.

### `GET /api/issuers/{cik}/transactions?page=1&page_size=100`

```json
{
  "data_as_of": {"date": "2026-09-30", "dataset": "2026q3"},
  "issuer": {"cik": "1633917", "name": "PayPal Holdings, Inc."},
  "page": 1, "page_size": 100, "total": 1234,
  "transactions": [
    {"accession": "0001633917-21-000185", "line_sk": "5917963",
     "filing_date": "2021-11-23", "trade_date": "2021-11-23",
     "form": "4", "form_description": "Report of a change in holdings",
     "code": "P", "code_description": "Bought shares on the open market or privately",
     "acquired_disposed": "A", "security_title": "Common Stock",
     "shares": 495.0, "price": 186.47, "value_usd": 92302.65,
     "shares_after": 495.0, "holding": "indirect", "holder": "2021 Family Trust 1",
     "owners": [{"cik": "1082870", "name": "DORMAN DAVID W", "role": "director", "title": null}],
     "footnote_ids": [],
     "edgar_url": "https://www.sec.gov/Archives/edgar/data/1633917/000163391721000185/"}
  ]
}
```

- `page_size` between 1 and 500 (default 100); unknown CIK → `404`.
- Fields are exactly the page's columns; `code_description` is always present (`"No code reported"` for a blank code).

## Errors

`404` for an unknown company or insider, `400` for a bad parameter, each with a plain-English message on pages and `{"detail": …}` in JSON. A missing `data/lookup.duckdb` stops `sentinel serve` before it starts (see [cli.md](cli.md)).
