"""Company profiles for the lookup tab: insider buying and selling, events and scores.

Covers every company with at least one provisional event (plan decision M2). Data is split into
shards by CIK so the page loads only what a search needs. Insider data is public SEC data; no
Yahoo prices are included.
"""

import json
from pathlib import Path

import duckdb
import pandas as pd

from mvp.config import WORK
from mvp.util import json_safe, text_or_empty

SHARD_COUNT_KEY = "shards"


def shard_of(cik: str, shards: int) -> int:
    return int(cik) % shards


def build(
    events: pd.DataFrame,
    companies: pd.DataFrame,
    scores: pd.DataFrame,
    settings,
    out_dirs: list[Path],
) -> dict:
    shards = settings.mvp["company"][SHARD_COUNT_KEY]
    keep_tx = settings.mvp["company"]["recent_tx"]
    con = duckdb.connect()
    ciks = pd.DataFrame({"issuer_cik": companies["issuer_cik"]})
    con.register("ciks", ciks)
    tx = f"'{WORK / 'insider_tx.parquet'}'"
    quarterly = con.execute(f"""
        select issuer_cik, year(filing_date) || 'Q' || quarter(filing_date) q,
               round(sum(value_usd) filter (where code = 'P' and acq_disp = 'A')) buy_v,
               count(distinct accession) filter (where code = 'P' and acq_disp = 'A') buy_n,
               round(sum(value_usd) filter (where code = 'S' and acq_disp = 'D')) sell_v,
               count(distinct accession) filter (where code = 'S' and acq_disp = 'D') sell_n
        from {tx} where issuer_cik in (select issuer_cik from ciks) and filing_date is not null
        group by all order by issuer_cik, q""").df()
    filings = con.execute(f"""
        with f as (
            select issuer_cik, accession, code, any_value(filing_date) d,
                   any_value("role") insider_role,
                   any_value(owner_names) owners, sum(shares) shares, sum(value_usd) v
            from {tx}
            where issuer_cik in (select issuer_cik from ciks)
              and ((code = 'P' and acq_disp = 'A') or (code = 'S' and acq_disp = 'D'))
            group by issuer_cik, accession, code
        )
        select * from f
        qualify row_number() over (
            partition by issuer_cik order by d desc, accession desc) <= {keep_tx}
        order by issuer_cik, d desc""").df()
    totals = con.execute(f"""
        select issuer_cik,
               count(distinct accession) filter (where code = 'P' and acq_disp = 'A') buys,
               round(sum(value_usd) filter (where code = 'P' and acq_disp = 'A')) buy_v,
               count(distinct accession) filter (where code = 'S' and acq_disp = 'D') sells,
               round(sum(value_usd) filter (where code = 'S' and acq_disp = 'D')) sell_v,
               max(filing_date) last_date
        from {tx} where issuer_cik in (select issuer_cik from ciks) group by issuer_cik""").df()
    con.close()

    score_map = dict(zip(scores["event_id"], scores["score"], strict=True)) if len(scores) else {}
    ev_by = {k: g for k, g in events.groupby("issuer_cik")}
    q_by = {k: g for k, g in quarterly.groupby("issuer_cik")}
    f_by = {k: g for k, g in filings.groupby("issuer_cik")}
    t_by = totals.set_index("issuer_cik").to_dict("index")

    def num(x):
        return None if pd.isna(x) else (int(x) if float(x).is_integer() else round(float(x), 2))

    out = [dict() for _ in range(shards)]
    index = []
    for c in companies.itertuples(index=False):
        tot = t_by.get(c.issuer_cik, {})
        ev = ev_by.get(c.issuer_cik)
        prof = {
            "cik": c.issuer_cik,
            "name": text_or_empty(c.name),
            "ticker": text_or_empty(c.ticker) or None,
            "reported": text_or_empty(c.last_reported_ticker),
            "exchange": text_or_empty(c.exchange) or None,
            "listed": bool(c.listed),
            "totals": {
                k: num(v) if k != "last_date" else (str(v)[:10] if pd.notna(v) else None)
                for k, v in tot.items()
            },
            "quarters": [
                [r.q, num(r.buy_v) or 0, int(r.buy_n), num(r.sell_v) or 0, int(r.sell_n)]
                for r in q_by[c.issuer_cik].itertuples(index=False)
            ]
            if c.issuer_cik in q_by
            else [],
            "filings": [
                [
                    str(r.d)[:10],
                    r.code,
                    r.insider_role,
                    (r.owners or "")[:60],
                    num(r.shares),
                    num(r.v),
                    r.accession,
                ]
                for r in f_by[c.issuer_cik].itertuples(index=False)
            ]
            if c.issuer_cik in f_by
            else [],
            "events": [
                [
                    str(r.signal_date),
                    r.group,
                    int(r.n_buyers),
                    num(r.total_value_usd),
                    (round(float(score_map[r.event_id]), 4) if r.event_id in score_map else None),
                ]
                for r in ev.sort_values("signal_date", ascending=False).itertuples(index=False)
            ]
            if ev is not None
            else [],
        }
        out[shard_of(c.issuer_cik, shards)][c.issuer_cik] = prof
        index.append(
            [
                c.issuer_cik,
                text_or_empty(c.name),
                text_or_empty(c.ticker) or text_or_empty(c.last_reported_ticker),
            ]
        )

    for d in out_dirs:
        folder = d / "data"
        folder.mkdir(parents=True, exist_ok=True)
        for k, shard in enumerate(out):
            (folder / f"companies-{k}.json").write_text(
                json.dumps(
                    json_safe(shard), separators=(",", ":"), ensure_ascii=False, allow_nan=False
                ),
                encoding="utf-8",
            )
    return {"index": index, "shards": shards, "count": len(index)}
