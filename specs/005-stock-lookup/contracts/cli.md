# Contract: Commands

Exit codes as in the rest of the CLI: 0 OK, 1 failed, 2 usage, 3 configuration or missing input.

| Command | Reads | Writes | Behaviour |
|---|---|---|---|
| `sentinel lookup` | `data/warehouse.duckdb`, read-only: the tables in research R2 only | `data/lookup.duckdb` (via a shadow file, then rename) | Builds every `lookup.*` table and `lookup.meta`; prints row counts and the data-as-of date. Missing warehouse tables → exit 3 naming the step to run. Under the 3 GB DuckDB limit |
| `sentinel serve [--port 8766] [--host 127.0.0.1]` | `data/lookup.duckdb`, read-only | nothing | Starts the app with uvicorn. Missing lookup file → exit 3 ("run `sentinel lookup` first"). Port in use → exit 1 with the port named. Warns, without stopping, when the warehouse was rebuilt after the lookup file (`warehouse_built_at`) |

- Neither command touches the network.
- `sentinel lookup` is not part of `sentinel build`: the lookup is a product artifact derived from the warehouse, rebuilt when the warehouse changes.
- README: both commands in the command table, with the URL.
