# Quickstart: Stock Lookup

Validation guide for feature 005. Contracts: [http.md](contracts/http.md), [cli.md](contracts/cli.md); tables: [data-model.md](data-model.md).

## Prerequisites

- The warehouse built through feature 002 (filings, transactions, roles, footnotes, preliminary events). Feature 004's company profiles (`core.issuer`) are used when present. No prices are needed.
- No network access is needed at any step.

## Build and run

```bash
# build the lookup file (about 35 s; under the memory ceiling like other data steps)
systemd-run --user --wait --pipe -p MemoryMax=5G -p MemorySwapMax=1G --working-directory="$PWD" \
    uv run sentinel lookup

# start the app, then open http://127.0.0.1:8766
uv run sentinel serve
```

Rebuild the lookup file after every warehouse rebuild; `sentinel serve` warns when it is older than the warehouse.

## Checks by hand (SC-001, SC-006, SC-007)

1. **Search**: type `PYPL`, then `paypal`, then `1633917`. PayPal Holdings, Inc. is the first result each time, within a second of typing.
2. **Old tickers**: type `SIVB`. SVB Financial Group is found although it no longer trades.
3. **Transactions**: open PayPal. The page shows the data-as-of line ("Data as of 30 Sep 2026, SEC data set 2026 Q3"), newest filings first, and every code with its description. Find 23 Nov 2021: five lines for DORMAN DAVID W, director, "Bought shares on the open market or privately", 495, 605, 150, 72 and 225 shares at $186.47, held indirectly by "2021 Family Trust 1" to "5". The EDGAR link opens accession 0001633917-21-000185.
4. **Holdings**: open Dorman's holdings. On 23 Nov 2021: 44,890 shares held directly, 1,547 indirectly, 46,437 in total.
5. **Events**: the events list shows a cluster on 23 Nov 2021 (2 buyers, both directors, $2,287,696.69) with both member filings, and no return or outcome.
6. **Paging**: open a company with a long history (CIK with the most lines, about 76,500). The first page appears in under 2 seconds; the next pages load in place.
7. **Glossary**: every code on the PayPal page has an entry.
8. **EDGAR links**: open 20 links from different companies; each opens the right filing.

## API

```bash
curl -s 'http://127.0.0.1:8766/api/issuers/search?q=paypal' | python -m json.tool
curl -s 'http://127.0.0.1:8766/api/issuers/1633917/transactions?page=1&page_size=5' | python -m json.tool
```

Both responses carry `data_as_of`; every transaction has `code_description`.

## Tests

```bash
uv run pytest tests/unit/test_lookup_build.py tests/unit/test_api.py tests/guards/test_lookup_no_prices.py
systemd-run --user --wait --pipe -p MemoryMax=5G -p MemorySwapMax=1G --working-directory="$PWD" \
    uv run pytest -m slow tests/integration/test_lookup_real.py
```

Expected: all pass. The slow tests check every real transaction code against the glossary (SC-003), the largest company's page time (SC-002) and the PayPal example (SC-007).
