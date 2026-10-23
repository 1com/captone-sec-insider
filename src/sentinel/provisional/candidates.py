"""Assemble, rank and write the provisional delisted-candidate list and its summary.

Look-ahead by design: "likely delisted" uses today's SEC ticker map. The outputs prioritise the
delisted-price pull and must never feed events, features or labels.
Contract: specs/001-skeleton-sec-ingest/contracts/provisional-outputs.md
"""

import csv
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from sentinel.config import Paths, params_sha256, registered_value
from sentinel.ingest import manifest
from sentinel.ingest.sec_bulk import SOURCE, quarters_in_range, tool_version
from sentinel.ingest.sec_reference import latest_snapshot, load_snapshot
from sentinel.provisional import tiingo_list
from sentinel.provisional.events import Event, Filing, detect_events
from sentinel.provisional.gates import a1_counts, apply_gates
from sentinel.provisional.load import build_scratch

STATUS = "PROVISIONAL"
START_YEARS = (2006, 2009, 2011, 2012, 2014, 2016)
SECTION_TOLERANCE = 0.15  # SC-006
FUNNEL_TOLERANCE = 0.01  # SC-005
CANDIDATE_COLUMNS = [
    "status",
    "rank",
    "tier",
    "issuer_cik",
    "issuer_name",
    "last_ticker",
    "all_tickers",
    "n_events_a",
    "n_events_b1",
    "n_events_labelled",
    "first_signal_date",
    "last_signal_date",
    "tiingo_match",
    "tiingo_matched_ticker",
]
FUNNEL_COLUMNS = [
    "status",
    "quarter",
    "step",
    "gate",
    "unit",
    "rows_in",
    "rows_out",
    "rows_removed",
]


class InputsMissing(Exception):
    pass


@dataclass(frozen=True)
class IssuerInfo:
    name: str
    last_ticker: str
    all_tickers: tuple[str, ...]


def issuer_info(con: duckdb.DuckDBPyConnection) -> dict[str, IssuerInfo]:
    """Name and tickers per company; the last ticker comes from its latest filing of any form."""
    order = "coalesce(strftime(filing_date, '%Y-%m-%d'), '') || accession"
    names = dict(
        con.execute(
            f"select issuer_cik, arg_max(issuer_name, {order}) from p_submission "
            "where issuer_cik is not null group by issuer_cik"
        ).fetchall()
    )
    symbols = con.execute(
        f"select issuer_cik, symbol_raw, max({order}) from p_submission "
        "where issuer_cik is not null and symbol_raw is not null group by all"
    ).fetchall()
    latest: dict[str, dict[str, str]] = defaultdict(dict)
    for cik, raw, order_key in symbols:
        ticker = tiingo_list.normalise(raw)
        if ticker and order_key > latest[cik].get(ticker, ""):
            latest[cik][ticker] = order_key
    return {
        cik: IssuerInfo(
            name=name or "",
            last_ticker=max(latest[cik], key=latest[cik].get) if latest[cik] else "",
            all_tickers=tuple(sorted(latest[cik])),
        )
        for cik, name in names.items()
    }


def _tickers(info: IssuerInfo) -> list[str]:
    rest = [t for t in info.all_tickers if t != info.last_ticker]
    return ([info.last_ticker] if info.last_ticker else []) + rest


def _by_issuer(events: list[Event]) -> dict[str, list[Event]]:
    grouped: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        grouped[e.issuer_cik].append(e)
    return grouped


def rank_candidates(
    events: list[Event],
    info: dict[str, IssuerInfo],
    active_ciks: set[str],
    tiingo: tiingo_list.TiingoIndex | None,
    labelled_start: date,
) -> list[dict]:
    rows = []
    for cik, evs in _by_issuer(events).items():
        if cik in active_ciks:
            continue
        inf = info.get(cik, IssuerInfo("", "", ()))
        first = min(e.signal_date for e in evs)
        last = max(e.signal_date for e in evs)
        n_a = sum(e.group == "A" for e in evs)
        flag, matched = tiingo_list.match(tiingo, _tickers(inf), first, last)
        rows.append(
            {
                "status": STATUS,
                "rank": 0,
                "tier": 1 if n_a else 2,
                "issuer_cik": cik,
                "issuer_name": inf.name,
                "last_ticker": inf.last_ticker,
                "all_tickers": "|".join(inf.all_tickers),
                "n_events_a": n_a,
                "n_events_b1": sum(e.group == "B1" for e in evs),
                "n_events_labelled": sum(e.signal_date >= labelled_start for e in evs),
                "first_signal_date": first,
                "last_signal_date": last,
                "tiingo_match": flag,
                "tiingo_matched_ticker": matched or "",
            }
        )
    rows.sort(key=lambda r: (r["tier"], -r["last_signal_date"].toordinal(), int(r["issuer_cik"])))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def start_year_table(events, info, active_ciks, tiingo, years=START_YEARS) -> list[dict]:
    """Plan §5.2 layout: per start year, events, companies and delisted companies."""
    out = []
    for year in years:
        evs = [e for e in events if e.signal_date.year >= year]
        grouped = _by_issuer(evs)
        delisted = [c for c in grouped if c not in active_ciks]
        matched = unmatched = None
        if tiingo is not None:
            flags = [
                tiingo_list.match(
                    tiingo,
                    _tickers(info.get(c, IssuerInfo("", "", ()))),
                    min(e.signal_date for e in grouped[c]),
                    max(e.signal_date for e in grouped[c]),
                )[0]
                for c in delisted
            ]
            matched = flags.count("matched")
            unmatched = len(flags) - matched
        out.append(
            {
                "start_year": year,
                "events": len(evs),
                "companies": len(grouped),
                "delisted": len(delisted),
                "delisted_in_tiingo": matched,
                "unmatched": unmatched,
            }
        )
    return out


def gap_mark(ours, pilot, tolerance: float) -> str:
    if ours is None or not pilot:
        return ""
    return "CHECK" if abs(ours - pilot) / pilot > tolerance else ""


def _fmt(ours, pilot, tolerance) -> str:
    if ours is None:
        return "n/a"
    if not pilot:
        return f"{ours:,}"
    return (
        f"{ours:,} vs {pilot:,} ({(ours - pilot) / pilot:+.1%}) {gap_mark(ours, pilot, tolerance)}"
    )


def render_summary(
    meta: dict,
    years: list[dict],
    per_year: dict,
    funnels: dict,
    otc: dict,
    notes: list[str],
    pilot: dict,
) -> str:
    lines = [
        "# Provisional delisted-candidate summary",
        "",
        "> **PROVISIONAL — look-ahead.** Uses today's SEC ticker map and the pilot's simplified "
        "gates. Only for prioritising the delisted-price pull; never for events, features, "
        "labels or returns.",
        "",
        f"- Run: {meta['finished_at']} · commit `{meta['tool']}` · "
        f"params `{meta['params_sha256'][:12]}`",
        f"- SEC ticker snapshot: `{meta['tickers_snapshot']}`",
        f"- Tiingo list: {meta['tiingo']['status']}"
        + (
            f" (Last-Modified {meta['tiingo']['last_modified']}, sha256 "
            f"`{meta['tiingo']['sha256'][:12]}`)"
            if meta["tiingo"]["status"] == "checked"
            else ""
        ),
        "",
        "## 1. Plan §5.2 table (ours vs pilot; CHECK = gap beyond ±15%)",
        "",
        "| Start year | Events (A+B1) | Companies | Delisted, in Tiingo's list "
        "| Delisted, not matched | Likely delisted (all) |",
        "|---|---|---|---|---|---|",
    ]
    ref = pilot["by_start_year"]
    for r in years:
        p = ref.get(r["start_year"], {})
        lines.append(
            f"| {r['start_year']} | {_fmt(r['events'], p.get('events'), SECTION_TOLERANCE)} "
            f"| {_fmt(r['companies'], p.get('companies'), SECTION_TOLERANCE)} "
            f"| {_fmt(r['delisted_in_tiingo'], p.get('delisted_in_tiingo'), SECTION_TOLERANCE)} "
            f"| {_fmt(r['unmatched'], p.get('unmatched'), SECTION_TOLERANCE)} "
            f"| {r['delisted']:,} |"
        )
    lines += [
        "",
        "## 2. Events per signal year (ours vs Appendix A.3)",
        "",
        "| Year | Clusters (A) | Solo CEO/CFO (B1) |",
        "|---|---|---|",
    ]
    for year in sorted(set(per_year) | set(pilot["by_year"])):
        a, b1 = per_year.get(year, (0, 0))
        pa_, pb = pilot["by_year"].get(year, (None, None))
        lines.append(
            f"| {year} | {_fmt(a, pa_, SECTION_TOLERANCE)} | {_fmt(b1, pb, SECTION_TOLERANCE)} |"
        )
    lines += ["", "## 3. Funnel vs Appendix A.1 (CHECK = gap beyond 1%)", ""]
    labels = {
        "purchase_lines": "Purchase lines (code P, acquired)",
        "original_form4": "— on an original Form 4",
        "common": "— common stock",
        "plan_fn": "— flagged by plan footnotes",
        "offering_fn": "— flagged by offering footnotes",
        "filings_g1_g5": "Filings passing G1–G5",
        "clean_filings": "Clean filings after all pilot gates",
    }
    quarters = list(funnels)
    lines += ["| Measure | " + " | ".join(quarters) + " |", "|---|" + "---|" * len(quarters)]
    for key, label in labels.items():
        cells = [
            _fmt(funnels[q].get(key), pilot.get(f"funnel_{q}", {}).get(key), FUNNEL_TOLERANCE)
            for q in quarters
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 4. Companies now on OTC or with no exchange in the SEC map",
        "",
        "Not candidates (still in the map), but counted because the pilot may have treated them as "
        "delisted (research.md R5).",
        "",
        f"- With an event from 2006: {otc['all']:,}",
        f"- With an event from the labelled-window start ({otc['start_year']}): "
        f"{otc['labelled']:,}",
        "",
        "## 5. Data notes",
        "",
        *[f"- {n}" for n in notes],
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    out_dir: Path,
    candidates: list[dict],
    events: list[Event],
    funnel_rows: list[tuple],
    summary_md: str,
    run_meta: dict,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(
        out_dir / "delisted_candidates_PROVISIONAL.csv", "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in candidates:
            w.writerow({k: v.isoformat() if isinstance(v, date) else v for k, v in r.items()})

    evs = sorted(events, key=lambda e: (int(e.issuer_cik), e.signal_date, e.group))
    pq.write_table(
        pa.table(
            {
                "status": [STATUS] * len(evs),
                "issuer_cik": [e.issuer_cik for e in evs],
                "group": [e.group for e in evs],
                "signal_date": pa.array([e.signal_date for e in evs], pa.date32()),
                "n_buyers": [e.n_buyers for e in evs],
                "total_value_usd": [e.total_value_usd for e in evs],
                "member_accessions": [list(e.member_accessions) for e in evs],
                "in_labelled_window": [e.in_labelled_window for e in evs],
            }
        ),
        out_dir / "events_PROVISIONAL.parquet",
    )

    with open(out_dir / "funnel_PROVISIONAL.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FUNNEL_COLUMNS)
        w.writerows((STATUS, *row) for row in funnel_rows)

    (out_dir / "summary_PROVISIONAL.md").write_text(summary_md, encoding="utf-8")
    (out_dir / "run_PROVISIONAL.json").write_text(
        json.dumps(run_meta, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _check_inputs(paths: Paths, params: dict, snapshot: Path | None) -> Path:
    period = registered_value(params, "insider_data_period")
    keys = quarters_in_range(str(period["start"]), str(period["end"]))
    report = manifest.verify(paths, prefix="sec/insider/")
    stored = {
        e.key
        for e in manifest.read_all(paths.manifest)
        if e.source == SOURCE and e.role == "original"
    }
    problems = [f"quarter {k} not downloaded" for k in keys if k not in stored]
    problems += [f"{p} differs from manifest" for p in report.mismatch]
    problems += [f"{p} missing" for p in report.missing]
    snapshot = snapshot or latest_snapshot(paths)
    if snapshot is None or not snapshot.exists():
        problems.append("no SEC ticker snapshot (run `sentinel fetch-sec-tickers`)")
    if problems:
        raise InputsMissing("; ".join(problems))
    return snapshot


def run(
    paths: Paths,
    params: dict,
    *,
    tickers_snapshot: Path | None = None,
    use_tiingo: bool = True,
    rebuild: bool = False,
    echo: Callable[[str], None] = print,
) -> list[dict]:
    started = datetime.now(UTC).replace(microsecond=0)
    snapshot = _check_inputs(paths, params, tickers_snapshot)
    prov = params["provisional"]
    labelled_start = date.fromisoformat(str(registered_value(params, "labelled_window_start")))

    echo("loading archives into the scratch database (reused when inputs are unchanged)…")
    con = build_scratch(paths, params, rebuild=rebuild)
    echo("applying the pilot gates…")
    apply_gates(con, params)
    filings = [
        Filing(acc, cik, d, frozenset(owners or ()), ceo, value)
        for acc, cik, d, owners, ceo, value in con.execute(
            "select accession, issuer_cik, filing_date, owner_ciks, has_ceo_cfo, value_usd "
            "from p_clean_filing where filing_date is not null"
        ).fetchall()
    ]
    echo(f"detecting events over {len(filings):,} clean filings…")
    events = detect_events(
        filings,
        window_days=registered_value(params, "cluster_window"),
        min_value=registered_value(params, "cluster_min_value"),
        min_buyers=prov["min_buyers_cluster"],
        cooldown_days=prov["cooldown_calendar_days"],
        labelled_start=labelled_start,
    )
    info = issuer_info(con)
    snap = load_snapshot(snapshot)
    active = set(snap)

    tiingo_index, tiingo_meta = None, {"status": "not checked (--no-tiingo)"}
    if use_tiingo:
        echo("matching against Tiingo's public ticker list (in memory only)…")
        body, last_modified, digest = tiingo_list.fetch_list(
            params["ops"]["tiingo_supported_tickers_url"], params["ops"]["http_timeout_seconds"]
        )
        tiingo_index = tiingo_list.parse_supported(body, prov["tiingo_us_exchanges"])
        del body
        tiingo_meta = {"status": "checked", "last_modified": last_modified, "sha256": digest}

    candidates = rank_candidates(events, info, active, tiingo_index, labelled_start)
    years = start_year_table(events, info, active, tiingo_index)
    per_year: dict[int, tuple[int, int]] = {}
    for e in events:
        a, b1 = per_year.get(e.signal_date.year, (0, 0))
        per_year[e.signal_date.year] = (a + (e.group == "A"), b1 + (e.group == "B1"))
    funnels = {q: a1_counts(con, q) for q in ("2019q1", "2023q1")}

    def otc_only(cik):
        exchanges = {x for _, x in snap.get(cik, [])}
        return cik in snap and exchanges <= {"OTC", None}

    issuers_all = {e.issuer_cik for e in events}
    issuers_lab = {e.issuer_cik for e in events if e.in_labelled_window}
    otc = {
        "all": sum(map(otc_only, issuers_all)),
        "labelled": sum(map(otc_only, issuers_lab)),
        "start_year": labelled_start.year,
    }
    stats = con.execute(
        "select count(*), sum(submissions_read - submissions_kept), sum(purchase_lines) "
        "from p_load_stats"
    ).fetchone()
    notes = [
        f"Quarters read: {stats[0]}",
        f"Duplicate or repeated submission rows dropped (by accession): {stats[1]:,}",
        f"Code-P purchase lines loaded: {stats[2]:,}",
        f"Clean filings: {len(filings):,}; provisional events: {len(events):,}",
        f"Likely-delisted candidates: {len(candidates):,} "
        f"(tier 1: {sum(c['tier'] == 1 for c in candidates):,})",
    ]
    funnel_rows = con.execute(
        "select quarter, step, gate, unit, rows_in, rows_out, rows_removed from p_funnel "
        "order by quarter, step"
    ).fetchall()
    con.close()

    meta = {
        "status": STATUS,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "tool": tool_version(),
        "params_sha256": params_sha256(paths.params_file),
        "tickers_snapshot": snapshot.relative_to(paths.data_raw).as_posix(),
        "archives": {
            e.key: e.sha256
            for e in manifest.read_all(paths.manifest)
            if e.source == SOURCE and e.role == "original"
        },
        "tiingo": tiingo_meta,
    }
    summary = render_summary(meta, years, per_year, funnels, otc, notes, prov["pilot_reference"])
    write_outputs(paths.provisional, candidates, events, funnel_rows, summary, meta)
    return years
