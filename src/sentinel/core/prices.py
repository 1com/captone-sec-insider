"""Step 7: one price series per issuer (feature 004, research R2–R5; data-model.md "Prices").

`core.price_daily` holds **as-traded** open, high, low, close and volume (what printed that day),
the split- and dividend-adjusted close, and `cum_split_after`, the product of the split ratios dated
after the session (split-adjusted price = as-traded ÷ `cum_split_after`). `core.session` is the
market calendar: SPY's sessions, numbered.

Yahoo's prices are split-adjusted, so as-traded values are rebuilt by undoing later splits; Tiingo's
unprefixed prices are already as traded. Tiingo files may be read only in the paid month.
"""

import contextlib
import csv
import gzip
import io
from dataclasses import dataclass, field
from datetime import date

import duckdb
import pyarrow as pa

from sentinel.config import Paths, registered_value
from sentinel.core.tiingo_register import require_paid_window
from sentinel.ingest import manifest, tiingo, yahoo
from sentinel.warehouse import MissingInput

SESSION_COLUMNS = "session DATE, session_no INTEGER"
SERIES_COLUMNS = (
    "issuer_cik VARCHAR, price_source VARCHAR, ticker VARCHAR, role VARCHAR, first_session DATE, "
    "last_session DATE, n_sessions INTEGER, identity VARCHAR, chosen BOOLEAN, reason VARCHAR"
)
DAILY_COLUMNS = (
    "issuer_cik VARCHAR, session DATE, price_source VARCHAR, ticker VARCHAR, open DOUBLE, "
    "high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, adj_close DOUBLE, "
    "cum_split_after DOUBLE, split_ratio DOUBLE, dividend DOUBLE, dollar_volume DOUBLE"
)
TABLES = {
    "core.session": SESSION_COLUMNS,
    "core.price_series": SERIES_COLUMNS,
    "core.price_daily": DAILY_COLUMNS,
}

YAHOO_COLUMNS = (
    "ticker VARCHAR, session DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, "
    "volume DOUBLE, adj_close DOUBLE, dividend DOUBLE, split_ratio DOUBLE, raw_path VARCHAR"
)
TIINGO_FIELDS = [
    ("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"), ("volume", "volume"),
    ("adjOpen", "adj_open"), ("adjHigh", "adj_high"), ("adjLow", "adj_low"),
    ("adjClose", "adj_close"), ("adjVolume", "adj_volume"), ("divCash", "dividend"),
    ("splitFactor", "split_ratio"),
]  # fmt: skip
ISSUE_COLUMNS = "price_source VARCHAR, ticker VARCHAR, session DATE, issue VARCHAR, detail VARCHAR"
LISTING_COLUMNS = (
    "ticker VARCHAR, list_exchange VARCHAR, list_start DATE, list_end DATE, meta_name VARCHAR, "
    "meta_exchange VARCHAR, meta_start DATE, meta_end DATE"
)
CROSSCHECK_COLUMNS = (
    "issuer_cik VARCHAR, ticker VARCHAR, overlap_days INTEGER, disagree_days INTEGER, "
    "disagree_share DOUBLE, tiingo_name VARCHAR, tiingo_identity VARCHAR, verdict VARCHAR"
)
SHADOW = "_new_"
CHUNK = 250  # raw files per transaction
SIGNIFICANT_DIGITS = 10
# Yahoo-versus-Tiingo check of a listed company's price series (audit.price_crosscheck): a day
# disagrees when the two adjusted daily returns differ by more than 2 points. A right pair differs
# only through dividend adjustment and data glitches; a reused ticker (another company) differs on
# most days. Only days when Tiingo's as-traded close is at least the registered price floor count:
# below it the vendors' closing prints differ by a few percent (a $0.20 stock), which says nothing
# about identity and which no event can use. Fewer than 20 such days is too few to judge.
CROSSCHECK_RETURN_GAP = 0.02
CROSSCHECK_MIN_DAYS = 20
CROSSCHECK_AGREE_MAX = 0.02  # at most 2% of shared days disagree: agree
CROSSCHECK_MISMATCH_MIN = 0.10  # at least 10% disagree: probably different companies


def _significant(expr: str) -> str:
    """SQL that rounds `expr` to SIGNIFICANT_DIGITS significant digits (0 and null unchanged).
    Rounding to fixed decimals would zero the tiny split factors and early prices of stocks with
    stacked reverse splits (cum_split_after down to 1e-12)."""
    return (
        f"case when coalesce({expr}, 0) = 0 then {expr} else round({expr}, "
        f"{SIGNIFICANT_DIGITS - 1} - cast(floor(log10(abs({expr}))) as integer)) end"
    )


@dataclass
class PriceReport:
    yahoo_rows: int = 0
    tiingo_rows: int = 0
    universe: int = 0
    chosen: dict[str, int] = field(default_factory=dict)
    unpriced: int = 0
    daily_rows: int = 0
    issues: dict[str, int] = field(default_factory=dict)


def create_price_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Empty price tables in the data-model layout, if absent (tests and first builds)."""
    for name, columns in TABLES.items():
        con.execute(f"create table if not exists {name} ({columns})")


@contextlib.contextmanager
def _transaction(con: duckdb.DuckDBPyConnection):
    con.execute("begin transaction")
    try:
        yield
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


def _stored(paths: Paths, source: str, prefix: str = "") -> list[tuple[str, str]]:
    """(key, absolute path) of stored originals of `source` whose key starts with `prefix`."""
    out = []
    for e in manifest.read_all(paths.manifest):
        if e.source == source and e.role == "original" and e.key.startswith(prefix):
            path = paths.data_raw / e.path
            if path.exists():
                out.append((e.key, str(path)))
    return sorted(out)


def _swap(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> None:
    con.execute(f"drop table if exists {schema}.{table}")
    con.execute(f"alter table {schema}.{SHADOW}{table} rename to {table}")


def _load_yahoo(con: duckdb.DuckDBPyConnection, paths: Paths) -> int:
    """`stg.price_yahoo`: every stored Yahoo file, duplicate sessions resolved to the last row in
    file order (counted in `_issue`)."""
    files = [p for key, p in _stored(paths, yahoo.SOURCE) if "/" not in key]
    prefix = str(paths.data_raw) + "/"
    con.execute(f"create or replace table stg.{SHADOW}price_yahoo ({YAHOO_COLUMNS})")
    for i in range(0, len(files), CHUNK):
        with _transaction(con):
            con.execute(
                """
                create or replace temp table _raw as
                select regexp_extract(filename, '([^/]+)\\.parquet$', 1) as ticker,
                       cast("Date" as DATE) as session, "Open" as open, "High" as high,
                       "Low" as low, "Close" as close, "Volume" as volume,
                       "Adj Close" as adj_close, "Dividends" as dividend,
                       "Stock Splits" as split, file_row_number as src_row,
                       replace(filename, $prefix, '') as raw_path
                from read_parquet($files, filename = true, file_row_number = true,
                                  union_by_name = true)
                """,
                {"files": files[i : i + CHUNK], "prefix": prefix},
            )
            con.execute(
                "insert into _issue select 'yahoo', ticker, session, 'duplicate_session', "
                "'kept the last row in file order' from _raw "
                "where close is not null group by ticker, session having count(*) > 1"
            )
            con.execute(
                f"""
                insert into stg.{SHADOW}price_yahoo
                select ticker, session, open, high, low, close, volume, adj_close,
                       coalesce(dividend, 0), case when coalesce(split, 0) = 0 then 1.0
                                                   else split end, raw_path
                from _raw where close is not null
                qualify row_number() over (partition by ticker, session order by src_row desc) = 1
                """
            )
    con.execute("drop table if exists _raw")
    with _transaction(con):
        _swap(con, "stg", "price_yahoo")
    return con.execute("select count(*) from stg.price_yahoo").fetchone()[0]


def _number(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def _load_tiingo(con: duckdb.DuckDBPyConnection, paths: Paths, params: dict, today) -> int:
    """`stg.price_tiingo` and `core.tiingo_listing`; both are Tiingo data (registered)."""
    files = _stored(paths, tiingo.SOURCE, "prices/")
    listed = (paths.tiingo / tiingo.LIST_FILE).exists()
    if files or listed:
        require_paid_window(params, today)
    columns = ", ".join(f"{name} DOUBLE" for _, name in TIINGO_FIELDS)
    con.execute(
        f"create or replace table stg.{SHADOW}price_tiingo (ticker VARCHAR, session DATE, "
        f"{columns}, raw_path VARCHAR)"
    )
    names = ["ticker", "session"] + [n for _, n in TIINGO_FIELDS] + ["raw_path"]
    for i in range(0, len(files), CHUNK):
        cols: dict[str, list] = {n: [] for n in names}
        for key, path in files[i : i + CHUNK]:
            ticker = key.removeprefix("prices/")
            rows: dict[str, dict] = {}
            with open(path, "rb") as f:
                text = gzip.decompress(f.read()).decode()
            for row in csv.DictReader(io.StringIO(text)):
                session = row["date"][:10]
                if session in rows:
                    con.execute(
                        "insert into _issue values ('tiingo', ?, ?, 'duplicate_session', "
                        "'kept the last row in file order')",
                        [ticker, session],
                    )
                rows[session] = row
            for session, row in rows.items():
                cols["ticker"].append(ticker)
                cols["session"].append(date.fromisoformat(session))
                for src, name in TIINGO_FIELDS:
                    cols[name].append(_number(row.get(src, "")))
                cols["raw_path"].append(path.removeprefix(str(paths.data_raw) + "/"))
        types = {"ticker": pa.string(), "session": pa.date32(), "raw_path": pa.string()}
        table = pa.table({n: pa.array(cols[n], types.get(n, pa.float64())) for n in names})
        con.register("_tiingo_chunk", table)
        try:
            with _transaction(con):
                con.execute(f"insert into stg.{SHADOW}price_tiingo select * from _tiingo_chunk")
        finally:
            con.unregister("_tiingo_chunk")
    _build_listing(con, paths, params, [k.removeprefix("prices/") for k, _ in files], listed)
    with _transaction(con):
        _swap(con, "stg", "price_tiingo")
        _swap(con, "core", "tiingo_listing")
    return con.execute("select count(*) from stg.price_tiingo").fetchone()[0]


def _build_listing(con, paths: Paths, params: dict, tickers: list[str], listed: bool) -> None:
    """`core.tiingo_listing`: Tiingo's list rows and meta answer for every ticker tried."""
    tried = sorted(
        set(tickers) | {k.removeprefix("meta/") for k, _ in _stored(paths, "tiingo", "meta/")}
    )
    listing = tiingo.stored_listing(paths, params) if listed else {}
    rows = []
    for t in tried:
        meta = tiingo.read_meta(paths, t) or {}
        found = (
            meta.get("name"),
            meta.get("exchangeCode"),
            tiingo._date(meta.get("startDate")),
            tiingo._date(meta.get("endDate")),
        )
        for start, end, exchange in listing.get(t, [(None, None, None)]):
            rows.append((t, exchange, start, end, *found))
    con.execute(f"create or replace table core.{SHADOW}tiingo_listing ({LISTING_COLUMNS})")
    if rows:
        con.executemany(
            f"insert into core.{SHADOW}tiingo_listing values (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def _sessions(con: duckdb.DuckDBPyConnection, params: dict) -> int:
    n = con.execute(
        "select count(*) from stg.price_yahoo where ticker = 'SPY' and session >= cast(? as DATE)",
        [str(params["rules"]["price_history_start"])],
    ).fetchone()[0]
    if not n:
        raise MissingInput(
            "SPY prices are needed for the market calendar: run "
            "`sentinel fetch-prices --source yahoo` first"
        )
    with _transaction(con):
        con.execute(
            """
            create or replace table core.session as
            select session, cast(row_number() over (order by session) as INTEGER) as session_no
            from stg.price_yahoo where ticker = 'SPY' and session >= cast(? as DATE)
            """,
            [str(params["rules"]["price_history_start"])],
        )
    return n


def _universe(con: duckdb.DuckDBPyConnection, params: dict, issuers=None) -> dict[str, date]:
    """Issuers with a preliminary event from `rules.final_detection_start`, with the first one."""
    rows = con.execute(
        "select issuer_cik, min(signal_date) from evt.prelim_event "
        "where signal_date >= cast(? as DATE) group by 1",
        [str(params["rules"]["final_detection_start"])],
    ).fetchall()
    return {cik: first for cik, first in rows if issuers is None or cik in issuers}


def _yahoo_stats(con) -> dict[str, tuple[date, date, int]]:
    return {
        t: (a, b, n)
        for t, a, b, n in con.execute(
            "select ticker, min(session), max(session), count(*) from stg.price_yahoo group by 1"
        ).fetchall()
    }


def _fallback_reasons(con, params: dict, universe: dict[str, date]) -> dict[str, str]:
    """Yahoo-mapped issuers whose primary Yahoo series is missing or starts after their first
    event: they are priced from Tiingo when it has them (FR-003)."""
    stats, primary = _yahoo_stats(con), yahoo.primary_tickers(con)
    reasons = {}
    for cik, ticker in primary.items():
        if cik not in universe:
            continue
        if ticker not in stats:
            reasons[cik] = "yahoo_missing"
        elif stats[ticker][0] > universe[cik]:
            reasons[cik] = "yahoo_starts_late"
    return reasons


def yahoo_fallback_issuers(con: duckdb.DuckDBPyConnection, params: dict) -> list[str]:
    """The issuers `fetch-prices --source tiingo` also resolves (needs `stg.price_yahoo`)."""
    return sorted(_fallback_reasons(con, params, _universe(con, params)))


def _choose(con, paths: Paths, params: dict, universe: dict[str, date]) -> list[tuple]:
    """Rows of `core.price_series`: every candidate series and which one is chosen (research R4)."""
    yahoo_issuers = {
        cik: sorted(
            t
            for (t,) in con.execute(
                "select ticker from core.symbol_map "
                "where issuer_cik = ? and price_source = 'yahoo'",
                [cik],
            ).fetchall()
        )  # fmt: skip
        for (cik,) in con.execute(
            "select distinct issuer_cik from core.symbol_map where price_source = 'yahoo'"
        ).fetchall()
        if cik in universe
    }
    ystats, primary = _yahoo_stats(con), yahoo.primary_tickers(con)
    reasons = _fallback_reasons(con, params, universe)
    rows: dict[tuple, list] = {}  # (cik, source, ticker) → row
    for cik, tickers in yahoo_issuers.items():
        for t in tickers:
            first, last, n = ystats.get(t, (None, None, 0))
            role = "primary" if t == primary.get(cik) else "other_class"
            rows[(cik, "yahoo", t)] = [
                cik,
                "yahoo",
                t,
                role,
                first,
                last,
                n,
                "not_checked",
                False,
                "",
            ]
    if (paths.tiingo / tiingo.LIST_FILE).exists():
        listing = tiingo.stored_listing(paths, params)
        tstats = {
            t: (a, b, n)
            for t, a, b, n in con.execute(
                "select ticker, min(session), max(session), count(*) "
                "from stg.price_tiingo group by 1"
            ).fetchall()
        }
        names: dict[str, list[str]] = {}
        for cik, name in con.execute(
            "select distinct issuer_cik, issuer_name from core.filing where issuer_name is not null"
        ).fetchall():
            names.setdefault(cik, []).append(name)
        for target in tiingo.resolve(con, listing, params, fallback_issuers=sorted(reasons)):
            if target.issuer_cik not in universe:
                continue
            first, last, n = tstats.get(target.ticker, (None, None, 0))
            ident = tiingo.identity(
                tiingo.read_meta(paths, target.ticker),
                names.get(target.issuer_cik, []),
                (target.span_start, target.span_end),
            )
            if ident == "ok" and not n:
                ident = "no_data"
            rows[(target.issuer_cik, "tiingo", target.ticker)] = [
                target.issuer_cik, "tiingo", target.ticker, target.role, first, last, n, ident,
                False, "",
            ]  # fmt: skip
    by_issuer: dict[str, list[list]] = {}
    for row in rows.values():
        by_issuer.setdefault(row[0], []).append(row)
    for cik, series in by_issuer.items():
        ok = [r for r in series if r[1] == "tiingo" and r[7] == "ok"]
        main = next((r for r in ok if r[3] in ("primary", "fallback")), None)
        if main is None and ok:
            main = max(ok, key=lambda r: (r[5], r[2]))
            main[3], main[9] = "primary", "tiingo_fill_in_promoted"
        y = next((r for r in series if r[1] == "yahoo" and r[3] == "primary"), None)
        if cik in yahoo_issuers:
            reason = reasons.get(cik)
            if reason is None and y is not None:
                y[8], y[9] = True, "yahoo_primary"
            elif main is not None:
                main[8], main[9] = True, f"{reason}→tiingo"
                if y is not None:
                    y[9] = reason
            elif y is not None and y[6]:
                y[8], y[9] = True, "yahoo_primary_late"
            elif y is not None:
                y[9] = reason or "no_data"
        elif main is not None:
            main[8] = True
            main[9] = main[9] or "tiingo_resolved"
        if main is not None and main[8]:
            for r in ok:
                if r is not main and r[3] == "fill_in" and r[4] is not None and r[4] < main[4]:
                    r[8], r[9] = True, "tiingo_fill_in"
        for r in series:
            if not r[9]:
                r[9] = "not_chosen" if r[7] in ("ok", "not_checked") else f"rejected_{r[7]}"
    return [tuple(r) for r in rows.values()]


def crosscheck_verdict(overlap: int, share: float | None, identity: str) -> str:
    """`not_in_tiingo`, `insufficient`, `agree`, `review` or `mismatch` (thresholds above)."""
    if identity == "no_data":
        return "not_in_tiingo"
    if overlap < CROSSCHECK_MIN_DAYS or share is None:
        return "insufficient"
    if share <= CROSSCHECK_AGREE_MAX:
        return "agree"
    return "mismatch" if share >= CROSSCHECK_MISMATCH_MIN else "review"


def _crosscheck(con, paths: Paths, params: dict, series: list[tuple]) -> None:
    """`audit.price_crosscheck`: for each chosen Yahoo series whose ticker Tiingo was also asked
    for, how often the two sources' adjusted daily returns disagree, and whether Tiingo's own
    record (name, dates) fits the SEC company. Tiingo prices only check Yahoo here: they never
    replace it. The table is Tiingo-derived, so it is registered with the other Tiingo tables."""
    con.execute(f"create or replace table audit.{SHADOW}price_crosscheck ({CROSSCHECK_COLUMNS})")
    tried = {k.removeprefix("meta/") for k, _ in _stored(paths, tiingo.SOURCE, "meta/")}
    tried |= {k.removeprefix("prices/") for k, _ in _stored(paths, tiingo.SOURCE, "prices/")}
    chosen = [r for r in series if r[1] == "yahoo" and r[8] and r[2] in tried]
    if not chosen:
        return
    stats = {
        t: (n, bad)
        for t, n, bad in con.execute(
            f"""
            with y as (
                select ticker, session, adj_close / lag(adj_close) over (
                           partition by ticker order by session) - 1 as r
                from stg.price_yahoo where adj_close > 0),
            t as (
                select ticker, session, close, adj_close / lag(adj_close) over (
                           partition by ticker order by session) - 1 as r
                from stg.price_tiingo where adj_close > 0)
            select y.ticker, count(*),
                   sum(cast(abs(y.r - t.r) > {CROSSCHECK_RETURN_GAP} as INTEGER))
            from y join t using (ticker, session)
            where y.r is not null and t.r is not null and t.close >= ?
            group by 1
            """,
            [registered_value(params, "price_floor")],
        ).fetchall()
    }
    names: dict[str, list[str]] = {}
    for cik, name in con.execute(
        "select distinct issuer_cik, issuer_name from core.filing where issuer_name is not null"
    ).fetchall():
        names.setdefault(cik, []).append(name)
    rows = []
    for cik, _, ticker, _, first, last, *_ in chosen:
        meta = tiingo.read_meta(paths, ticker)
        span = (first, last) if first and last else (date.min, date.max)
        ident = tiingo.identity(meta, names.get(cik, []), span)
        n, bad = stats.get(ticker, (0, 0))
        share = bad / n if n else None
        rows.append(
            (cik, ticker, n, bad, share, (meta or {}).get("name"), ident,
             crosscheck_verdict(n, share, ident))
        )  # fmt: skip
    con.executemany(
        f"insert into audit.{SHADOW}price_crosscheck values (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def _daily(con, cutoff=None) -> None:
    """`core._new_price_daily` and the price issues of the chosen series."""
    last = "(select max(session) from core.session where session <= cast($cutoff as DATE))"
    keep = f"and r.session <= {last}" if cutoff is not None else ""
    con.execute(
        f"""
        create or replace temp table _rows as
        with chosen as (select * from core.{SHADOW}price_series where chosen),
        main as (
            select issuer_cik, min(first_session) filter (where role <> 'fill_in') as main_start
            from chosen group by 1
        ),
        provider as (
            select 'yahoo' as price_source, ticker, session, open, high, low, close, volume,
                   adj_close, dividend, split_ratio, true as split_adjusted
            from stg.price_yahoo
            union all
            select 'tiingo', ticker, session, open, high, low, close, volume, adj_close,
                   coalesce(dividend, 0), coalesce(split_ratio, 1.0), false
            from stg.price_tiingo
        )
        select c.issuer_cik, cast(c.role = 'fill_in' as INTEGER) as fill_rank,
               c.n_sessions as series_sessions, r.*
        from provider r
        join chosen c on c.price_source = r.price_source and c.ticker = r.ticker
        join main m on m.issuer_cik = c.issuer_cik
        where (c.role <> 'fill_in' or r.session < m.main_start) {keep}
        """,
        {"cutoff": cutoff} if cutoff is not None else {},
    )
    con.execute(
        """
        insert into _issue
        select price_source, ticker, session,
               case when close is null or close <= 0 then 'nonpositive_close'
                    when high < low then 'high_below_low'
                    else 'not_a_session' end, null
        from _rows r
        where close is null or close <= 0 or high < low
           or session not in (select session from core.session)
        """
    )
    con.execute(
        f"""
        create or replace table core.{SHADOW}price_daily as
        with valid as (
            -- exp of an exact DECIMAL sum of logs: a window product() multiplies in an order that
            -- varies between runs, and the last bit then decides some 10-digit roundings
            select *, coalesce(exp(cast(sum(cast(ln(
                           case when split_ratio > 0 then split_ratio else 1.0 end
                       ) as DECIMAL(38, 18)))
                           over (partition by issuer_cik, price_source, ticker order by session
                                 rows between 1 following and unbounded following) as DOUBLE)),
                       1.0) as cum
            from _rows
            where close > 0 and not coalesce(high < low, false)
              and session in (select session from core.session)
        ),
        traded as (
            select issuer_cik, fill_rank, series_sessions, session, price_source, ticker,
                   case when split_adjusted then {_significant("open * cum")} else open end as open,
                   case when split_adjusted then {_significant("high * cum")} else high end as high,
                   case when split_adjusted then {_significant("low * cum")} else low end as low,
                   case when split_adjusted then {_significant("close * cum")} else close end
                       as close,
                   case when split_adjusted then round(volume / cum, 2) else volume end as volume,
                   adj_close, {_significant("cum")} as cum_split_after, split_ratio, dividend
            from valid
        )
        -- One row per issuer and session. Fill-ins of two share classes can cover the same
        -- days (LGF-A and LGF-B): the main series wins, then the fill-in with more sessions,
        -- then the ticker. Chosen after the split factors, so each series keeps its own splits.
        select issuer_cik, session, price_source, ticker, open, high, low, close, volume,
               adj_close, cum_split_after, split_ratio, dividend, close * volume as dollar_volume
        from traded
        qualify row_number() over (
            partition by issuer_cik, session order by fill_rank, series_sessions desc, ticker
        ) = 1
        """
    )
    con.execute(
        f"""
        insert into _issue
        select price_source, ticker, session,
               case when coalesce(open, 0) = 0 then 'zero_open' else 'open_outside_range' end,
               null
        from core.{SHADOW}price_daily
        where coalesce(open, 0) = 0 or open < low or open > high
        """
    )


def build(
    con: duckdb.DuckDBPyConnection,
    paths: Paths,
    params: dict,
    cutoff=None,
    issuers=None,
    today: date | None = None,
) -> PriceReport:
    """Rebuild `stg.price_yahoo`, `stg.price_tiingo`, `core.tiingo_listing`, `core.session`,
    `core.price_series`, `core.price_daily`, `audit.price_crosscheck` and `audit.price_issue`.
    `cutoff` drops price rows
    after the last session on or before it (truncation tests); the calendar is kept whole."""
    for table in ("core.symbol_map", "evt.prelim_event", "core.filing"):
        if not con.execute(
            "select count(*) from information_schema.tables "
            "where table_schema || '.' || table_name = ?",
            [table],
        ).fetchone()[0]:
            raise MissingInput(f"run `sentinel build` (feature 002) first: missing {table}")
    report = PriceReport()
    con.execute(f"create or replace temp table _issue ({ISSUE_COLUMNS})")
    report.yahoo_rows = _load_yahoo(con, paths)
    _sessions(con, params)
    report.tiingo_rows = _load_tiingo(con, paths, params, today)
    universe = _universe(con, params, issuers)
    report.universe = len(universe)
    series = _choose(con, paths, params, universe)
    con.execute(f"create or replace table core.{SHADOW}price_series ({SERIES_COLUMNS})")
    if series:
        con.executemany(
            f"insert into core.{SHADOW}price_series values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", series
        )
    _daily(con, cutoff)
    _crosscheck(con, paths, params, series)
    with _transaction(con):
        _swap(con, "core", "price_series")
        _swap(con, "core", "price_daily")
        _swap(con, "audit", "price_crosscheck")
        con.execute(
            "create or replace table audit.price_issue as "
            "select distinct * from _issue order by all"
        )
    for name in ("_rows", "_issue"):
        con.execute(f"drop table if exists {name}")
    for reason, n in con.execute(
        "select reason, count(*) from core.price_series where chosen group by 1 order by 1"
    ).fetchall():
        report.chosen[reason] = n
    priced = {
        r[0]
        for r in con.execute(
            "select distinct issuer_cik from core.price_series where chosen"
        ).fetchall()
    }
    report.unpriced = len(set(universe) - priced)
    report.daily_rows = con.execute("select count(*) from core.price_daily").fetchone()[0]
    report.issues = dict(
        con.execute(
            "select issue, count(*) from audit.price_issue group by 1 order by 1"
        ).fetchall()
    )
    return report


def check_one_series(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W14: issuers with more than one chosen main series, price rows from an unchosen one, or
    two price rows for one session."""
    several = con.execute(
        "select issuer_cik from core.price_series where chosen and role <> 'fill_in' "
        "group by 1 having count(*) > 1 order by 1"
    ).fetchall()
    stray = con.execute(
        """
        select distinct d.issuer_cik from core.price_daily d
        left join core.price_series s on s.issuer_cik = d.issuer_cik
             and s.price_source = d.price_source and s.ticker = d.ticker and s.chosen
        where s.issuer_cik is null order by 1
        """
    ).fetchall()
    doubled = con.execute(
        "select distinct issuer_cik from core.price_daily group by issuer_cik, session "
        "having count(*) > 1 order by 1"
    ).fetchall()
    return (
        [f"{c} several main series" for (c,) in several]
        + [f"{c} rows from an unchosen series" for (c,) in stray]
        + [f"{c} two price rows for one session" for (c,) in doubled]
    )


def check_valid_prices(con: duckdb.DuckDBPyConnection) -> list[str]:
    """W15: close > 0 and low ≤ high; Yahoo as-traded close ÷ cum_split_after equals Yahoo's
    split-adjusted close (relative 1e-6)."""
    bad = con.execute(
        "select issuer_cik || ' ' || session from core.price_daily "
        "where not (close > 0) or low > high order by 1 limit 10"
    ).fetchall()
    drift = con.execute(
        """
        select d.issuer_cik || ' ' || d.session from core.price_daily d
        join stg.price_yahoo y on y.ticker = d.ticker and y.session = d.session
        where d.price_source = 'yahoo'
          and abs(d.close / d.cum_split_after - y.close) > 1e-6 * y.close + 1e-6
        order by 1 limit 10
        """
    ).fetchall()
    return [f"{r} invalid price" for (r,) in bad] + [f"{r} as-traded mismatch" for (r,) in drift]
