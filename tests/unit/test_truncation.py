"""Constitution I, the truncation test: deleting every record dated after day D leaves every
feature as of D or earlier unchanged (no feature looks ahead). On the synthetic market of
`conftest.build_world`."""

from datetime import date

import pandas as pd
import pytest
from conftest import REPO, build_world

from sentinel import build, db
from sentinel.config import Paths
from sentinel.features.snapshot import feature_columns

D = date(2021, 6, 30)
# what a rebuild from files truncated at D would hold: every record dated after D removed
AFTER_D = {
    "ref.calendar": "session", "core.price_daily": "session", "stg_yahoo.price": "session",
    "core.short_volume": "session", "core.filing": "filing_date",
    "core.results_release": "confirmed", "core.financial_fact": "filed",
    "core.shares_outstanding": "filed", "core.insider_trade": "filing_date",
    "core.insider_activity": "filing_date", "core.insider_filing": "filing_date",
    "core.insider_cluster": "cluster_date", "core.macro_observation": "available",
}  # fmt: skip


@pytest.fixture
def features(tmp_path_factory):
    """features(deleted): the features as of D or earlier after deleting, per table, the rows
    whose given column is after D (or, for a control, on or before it)."""

    def run(deleted: dict[str, str], after: bool = True) -> pd.DataFrame:
        root = tmp_path_factory.mktemp("project")
        (root / "config").mkdir()
        for f in ("sources.yaml", "risk_params.yaml", "tracker.yaml"):
            (root / "config" / f).write_bytes((REPO / "config" / f).read_bytes())
        p = Paths.from_root(root)
        con = db.connect(p)
        try:
            build_world(con)
            for table, column in deleted.items():
                con.execute(f"delete from {table} where {column} {'>' if after else '<='} ?", [D])
            build.run(con, p, "features", echo=lambda s: None)
            cols = ", ".join(["cik", "as_of", *feature_columns(p)])
            return con.execute(
                f"select {cols} from feature.snapshot where as_of <= ? order by cik, as_of", [D]
            ).df()
        finally:
            con.close()

    return run


def _common(a: pd.DataFrame, b: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = a[["cik", "as_of"]].merge(b[["cik", "as_of"]])
    return (a.merge(keys).reset_index(drop=True), b.merge(keys).reset_index(drop=True))


def test_features_up_to_a_day_do_not_change_when_later_records_are_removed(features):
    full, truncated = _common(features({}), features(AFTER_D))
    assert len(full) > 40  # month-ends and release eves of both companies up to D
    assert pd.Timestamp(full["as_of"].max()) == pd.Timestamp(D)
    pd.testing.assert_frame_equal(full, truncated)


def test_the_comparison_does_see_a_change_in_earlier_records(features):
    full, control = _common(features({}), features({"core.insider_trade": "filing_date"}, False))
    with pytest.raises(AssertionError):  # removing June's insider trades changes D's features
        pd.testing.assert_frame_equal(full, control)
