"""Tiingo's public ticker list, processed in memory only.

Tiingo's Starter-plan terms (ToS §1.6(a)) forbid storing Tiingo data, so the list is downloaded into
memory, used for match flags, and discarded. Only its Last-Modified header and SHA-256 are kept, so
differences between runs can be explained (research.md R5).

The helpers live in `sentinel.core.symbols` (feature 002) and are re-exported here.
"""

from sentinel.core.symbols import (  # noqa: F401
    NO_TICKER,
    TiingoIndex,
    fetch_list,
    match,
    normalise,
    parse_supported,
)
