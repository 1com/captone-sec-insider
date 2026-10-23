"""The Tiingo deletion register (feature 004, FR-005; constitution VI; Tiingo ToS §1.6).

Tiingo data may be stored only while the paid plan is active, and must be deleted everywhere when
it ends. Per-security values derived from Tiingo prices count as Tiingo data. The register is
(1) every manifest line with `source = tiingo`, all under `data/raw/tiingo/`, and (2) the warehouse
tables below with the predicate selecting their Tiingo-derived rows.
Contract: specs/004-market-data-events/contracts/tiingo-register.md
"""

from datetime import date

SOURCE = "tiingo"
WHOLE_TABLE = None

# (table, predicate); WHOLE_TABLE drops the table. Every warehouse table with a `price_source`
# column must be listed (tests/unit/test_tiingo_register.py).
TIINGO_DERIVED: list[tuple[str, str | None]] = [
    ("stg.price_tiingo", WHOLE_TABLE),
    ("core.tiingo_listing", WHOLE_TABLE),
    ("core.price_series", "price_source = 'tiingo'"),
    ("core.price_daily", "price_source = 'tiingo'"),
    ("core.price_check", "price_source = 'tiingo'"),
    ("evt.event_candidate", "price_source = 'tiingo'"),
    ("evt.event", "price_source = 'tiingo'"),
    ("evt.event_cost", "price_source = 'tiingo'"),
    ("core.delisting", "price_source = 'tiingo'"),
]


class OutsidePaidWindow(Exception):
    """Tiingo data would be written outside [ops.tiingo_paid_from, ops.tiingo_paid_until)."""


def paid_window_open(params: dict, today: date) -> bool:
    ops = params["ops"]
    until = ops.get("tiingo_paid_until")
    return until is not None and ops["tiingo_paid_from"] <= today < until


def require_paid_window(params: dict, today: date | None = None) -> None:
    today = today or date.today()
    if paid_window_open(params, today):
        return
    ops = params["ops"]
    if ops.get("tiingo_paid_until") is None:
        raise OutsidePaidWindow(
            "Tiingo data can be stored only during the paid month: set ops.tiingo_paid_until in "
            "config/params.yaml to the day the plan ends"
        )
    raise OutsidePaidWindow(
        f"today ({today}) is outside the paid Tiingo window "
        f"[{ops['tiingo_paid_from']}, {ops['tiingo_paid_until']}); Tiingo data cannot be written"
    )
