"""Provisional event detection with the pilot's definitions (Appendix A.3; data-model.md §8–9).

At each clean-filing date T, the window is [T − (window_days − 1), T]. Filings whose owner sets
overlap are one buyer. A cluster (A) needs ≥ min_buyers buyers; a solo CEO/CFO event (B1) needs a
single buyer that includes a CEO or CFO. Both need ≥ min_value in the window. After an event, the
same issuer cannot produce another event in the same group for cooldown_days.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Filing:
    accession: str
    issuer_cik: str
    filing_date: date
    owner_ciks: frozenset[str]
    has_ceo_cfo: bool
    value_usd: float


@dataclass(frozen=True)
class Event:
    issuer_cik: str
    group: str
    signal_date: date
    n_buyers: int
    total_value_usd: float
    member_accessions: tuple[str, ...]
    in_labelled_window: bool


def _buyers(filings: list[Filing]) -> list[list[Filing]]:
    """Group filings whose owner sets overlap (connected components)."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys = [f.owner_ciks or frozenset({f"accession:{f.accession}"}) for f in filings]
    for owners in keys:
        first, *rest = sorted(owners)
        for other in rest:
            parent[find(other)] = find(first)
    groups: dict[str, list[Filing]] = defaultdict(list)
    for f, owners in zip(filings, keys, strict=True):
        groups[find(min(owners))].append(f)
    return list(groups.values())


def detect_events(
    filings: Iterable[Filing],
    *,
    window_days: int,
    min_value: float,
    min_buyers: int,
    cooldown_days: int,
    labelled_start: date,
) -> list[Event]:
    by_issuer: dict[str, list[Filing]] = defaultdict(list)
    for f in filings:
        by_issuer[f.issuer_cik].append(f)

    events = []
    span = timedelta(days=window_days - 1)
    cooldown = timedelta(days=cooldown_days)
    for cik in sorted(by_issuer):
        fs = sorted(by_issuer[cik], key=lambda f: (f.filing_date, f.accession))
        dates = [f.filing_date for f in fs]
        next_allowed: dict[str, date] = {}
        for t in sorted(set(dates)):
            window = fs[bisect_left(dates, t - span) : bisect_right(dates, t)]
            buyers = _buyers(window)
            total = sum(f.value_usd for f in window)
            if total < min_value:
                continue
            if len(buyers) >= min_buyers:
                group = "A"
            elif len(buyers) == 1 and any(f.has_ceo_cfo for f in buyers[0]):
                group = "B1"
            else:
                continue
            if group in next_allowed and t < next_allowed[group]:
                continue
            next_allowed[group] = t + cooldown
            events.append(
                Event(
                    issuer_cik=cik,
                    group=group,
                    signal_date=t,
                    n_buyers=len(buyers),
                    total_value_usd=total,
                    member_accessions=tuple(sorted(f.accession for f in window)),
                    in_labelled_window=t >= labelled_start,
                )
            )
    return events
