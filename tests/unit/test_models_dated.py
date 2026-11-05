"""A model that knows when it learned (`sentinel.models.dated`): it learns only from answers known
before its cutoff and forecasts only rows dated from its cutoff on."""

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from sentinel import eda
from sentinel.models.dated import Dated

FEATURES = ["x", "z"]


def _rows() -> pd.DataFrame:
    """Dilution rows at month-ends 2015-2019, each answer known 182 days after its row."""
    as_of = pd.date_range("2015-01-31", "2019-12-31", freq="ME")
    rng = np.random.default_rng(0)
    x = rng.normal(size=len(as_of))
    end, z = as_of + pd.Timedelta(days=182), rng.normal(size=len(as_of))
    return pd.DataFrame({"as_of": as_of, "window_end": end, "x": x, "z": z,
                         "dilution": (x > 0).astype(int)})  # fmt: skip


def _model() -> Dated:
    return Dated(LogisticRegression(), "dilution", FEATURES)


def test_a_walk_forward_fold_runs_and_each_model_keeps_its_cutoff():
    rows = _rows()
    fold = eda.folds(rows, "dilution", [2019])[2019]
    inner = _model().fit(rows[fold["inner"]], "2018-01-01")  # settings are judged on 2018
    assert len(inner.predict(rows[fold["valid"]])) == fold["valid"].sum() == 6
    final = _model().fit(rows[fold["inner"] | fold["gap"] | fold["valid"]], "2019-01-01")
    assert final.cutoff == pd.Timestamp("2019-01-01")
    assert len(final.predict(rows[fold["test"]])) == 12


def test_it_refuses_to_learn_an_answer_known_after_its_cutoff():
    rows = _rows()
    with pytest.raises(AssertionError, match="not known before"):  # May 2018's answer: Nov 2018
        _model().fit(rows[rows.as_of <= "2018-05-31"], "2018-01-01")
    with pytest.raises(ValueError, match="early stopping"):
        _model().fit(rows[rows.as_of <= "2017-06-30"], "2018-01-01", eval_set=[(None, None)])


def test_it_refuses_to_forecast_a_row_dated_before_its_cutoff():
    rows = _rows()
    model = _model().fit(rows[rows.as_of <= "2017-06-30"], "2018-01-01")
    with pytest.raises(AssertionError, match="dated before 2018-01-01"):
        model.predict(rows[rows.as_of >= "2017-12-31"])
    with pytest.raises(ValueError, match="not fitted"):
        _model().predict(rows)


def test_features_are_chosen_by_name():
    rows = _rows()
    model = _model().fit(rows[rows.as_of <= "2017-06-30"], "2018-01-01")
    late = rows[rows.as_of >= "2018-01-01"]
    assert np.array_equal(model.predict(late), model.predict(late[["z", "dilution", "x", "as_of"]]))
