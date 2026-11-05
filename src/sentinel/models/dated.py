"""A model that knows when it learned (the researcher, 5 Nov: "no information from the future; the
model needs to be self-aware of that"). Every model, calibration, band edge and range of 005-007 is
wrapped in `Dated`, in the notebooks and in the saved models alike.

`fit(rows, cutoff)` learns only from rows whose answers were known before `cutoff`, the start of
the period it will be judged on: the validation year when settings are chosen, the test year for
the model scored on it, 1 January 2023 for the frozen model. A dilution row dated 31 May 2018 has
its answer only on 29 November 2018, so it can teach a model judged from 2019, never one judged
from 2018. `predict(rows)` forecasts only rows dated on or after the cutoff: of an earlier row the
model may have learned the answer. Early stopping inside `fit` is refused, as it learns from the
rows it stops on; settings are chosen by fitting on one block and predicting a later one. The
cutoff, the question and the features are saved with the model, so the holdout test (010) and the
daily scores keep the same guard.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from sentinel import eda


@dataclass
class Dated:
    """`estimator`: anything with `fit(X, y)` and `predict(X)` (or `predict_proba(X)`, whose second
    column is returned); `features` are selected by name."""

    estimator: Any
    question: str
    features: list[str]
    cutoff: pd.Timestamp | None = field(default=None, init=False)

    def fit(self, rows: pd.DataFrame, cutoff, y=None, **fit_args) -> Dated:
        """Fit on `rows` (their answers known before `cutoff`); `y` defaults to the answer."""
        if "eval_set" in fit_args:
            raise ValueError("no early stopping: it learns from the rows it stops on; choose "
                             "settings by predicting a later block")  # fmt: skip
        eda.known_before(rows, self.question, cutoff)
        target = rows[eda.ANSWER[self.question]] if y is None else y
        self.estimator.fit(rows[self.features], target, **fit_args)
        self.cutoff = pd.Timestamp(cutoff)
        return self

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Forecasts for `rows`, all dated on or after the cutoff."""
        if self.cutoff is None:
            raise ValueError("not fitted")
        early = rows["as_of"] < self.cutoff
        assert not early.any(), (
            f"{int(early.sum())} rows are dated before {self.cutoff.date()}, when this model "
            "learned: it may have seen their answers"
        )
        x = rows[self.features]
        if hasattr(self.estimator, "predict_proba"):
            return self.estimator.predict_proba(x)[:, 1]
        return self.estimator.predict(x)
