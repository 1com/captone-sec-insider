"""Layer 5: Scoring and Live Outcomes.

Generates daily scores across covered stocks for all three questions and tracks
realized outcomes on closed forecast windows.
"""

from sentinel.scoring.daily import score_snapshot
from sentinel.scoring.outcomes import evaluate_outcomes
from sentinel.scoring.schema import create_tables

__all__ = [
    "create_tables",
    "evaluate_outcomes",
    "score_snapshot",
]
