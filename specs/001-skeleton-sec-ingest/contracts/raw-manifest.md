# Contract: Raw Data Layout and Manifest

## Layout

```text
data/raw/
├── manifest.jsonl                         # append-only; one JSON object per stored file
├── .lock                                  # held while any fetch command runs
└── sec/
    ├── insider/
    │   ├── 2006q1_form345.zip             # mode 0444 once stored
    │   ├── …
    │   ├── 2026q3_form345.zip
    │   └── 2026q3_form345__refetch_20261105T101500Z.zip   # only after an explicit --refetch
    └── reference/
        └── company_tickers_exchange_20261022.json
```

- **No Tiingo files.** Nothing from Tiingo is ever written under `data/raw/` in this feature.
- **Partial downloads** are named `<final name>.part` and sit in the same folder. They are removed on failure and at the start of the next run.

## `manifest.jsonl` line

```json
{"path": "sec/insider/2019q1_form345.zip",
 "source": "sec_insider_bulk",
 "key": "2019q1",
 "role": "original",
 "url": "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2019q1_form345.zip",
 "fetched_at": "2026-10-22T11:11:04Z",
 "bytes": 13745081,
 "sha256": "<64 hex>",
 "http_last_modified": "<as sent by server or null>",
 "http_etag": "<as sent by server or null>",
 "tool": "sentinel 0.1.0+abc1234"}
```

## Rules

1. **Path**: relative to `data/raw/`, using forward slashes. It is unique across the file.
2. **When a line is written**: only after the file has been renamed to its final name and made read-only. The write is a single append, flushed and fsynced.
3. **No edits**: lines are never rewritten or deleted. A corrected file is a new line with `role: "refetch"`.
4. **One original per key**: each (`source`, `key`) has exactly one `original` line. Readers use the `original` copy.
5. **Validation before a quarter is accepted**: the zip opens, every member passes its CRC check (`testzip()` returns `None`), and every table in `ops.required_archive_tables` is present as `<TABLE>.tsv`.
6. **Locking**: two fetch commands cannot run at the same time. The second exits 1 with "another fetch is running".
7. **No request data**: no request headers, User-Agent or keys are ever written to the manifest.
