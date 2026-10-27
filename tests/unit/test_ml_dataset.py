"""The ML dataset: folds, slices, purging, weights, version (feature 006 research R11)."""

import math
from datetime import date

import pytest
from conftest import REPO, market_sessions

from sentinel import warehouse
from sentinel.config import Paths, load_params
from sentinel.core import prices
from sentinel.ml import dataset

H = 63


@pytest.fixture(scope="module")
def params():
    return load_params(REPO / "config" / "params.yaml")


def _session_after(days, d):
    return next(x for x in days if x >= d)


@pytest.fixture(scope="module")
def built(tmp_path_factory, params):
    paths = Paths.from_root(tmp_path_factory.mktemp("ml"))
    con = warehouse.connect(paths)
    days = market_sessions(con, date(2011, 1, 3), 3200)
    no = {d: i + 1 for i, d in enumerate(days)}
    signals = {
        "fit_2016": date(2016, 3, 1),
        "cross_2018": date(2018, 11, 15),  # window ends in February 2019
        "tune_2018": date(2018, 3, 1),     # fold 2019 tuning slice (2018-01 … 2018-06)
        "late_tune": date(2018, 5, 15),    # tuning slice, window ends inside calibration: purged
        "cal_2018": date(2018, 7, 2),      # fold 2019 calibration slice
        "test_2019": date(2019, 5, 1),
        "overlap_a": date(2017, 3, 1),
        "overlap_b": None,                 # ten sessions after overlap_a
        "no_cost": date(2017, 10, 2),      # no target
        "b1_2017": date(2017, 9, 1),       # not a cluster
    }  # fmt: skip
    a = _session_after(days, signals["overlap_a"])
    signals["overlap_b"] = days[no[a] - 1 + 10]
    signals = {k: _session_after(days, v) for k, v in signals.items()}
    con.execute(
        'create table evt.event (event_id VARCHAR, "group" VARCHAR, priced BOOLEAN, '
        "signal_date DATE, t_session DATE)"
    )
    groups = {k: "B1" if k == "b1_2017" else "A" for k in signals}
    con.executemany("insert into evt.event values (?, ?, true, ?, ?)",
                    [(k, groups[k], d, d) for k, d in signals.items()])  # fmt: skip
    con.execute(
        "create table feat.event_features (event_id VARCHAR, issuer_cik VARCHAR, "
        '"group" VARCHAR, signal_date DATE, t_session DATE, '
        + ", ".join(f"f{i} VARCHAR" if i == 24 else f"f{i} DOUBLE" for i in range(1, 30))
        + ", price_source VARCHAR)"
    )
    for k, d in signals.items():
        values = [float(i) for i in range(1, 30)]
        values[23] = "BusEq"
        values[11] = 0.0  # F12: no sales
        con.execute(
            f"insert into feat.event_features values (?, '1', ?, ?, ?, {', '.join(['?'] * 29)}, "
            "'yahoo')",
            [k, "B1" if k == "b1_2017" else "A", d, d, *values],
        )
    con.execute(
        "create table lab.event_label (event_id VARCHAR, horizon INTEGER, measure VARCHAR, "
        "exit_session DATE, gross DOUBLE, net DOUBLE)"
    )
    for i, (k, d) in enumerate(signals.items()):
        net = None if k == "no_cost" else (0.05 if i % 2 else -0.05)
        for horizon in (21, 63, 126):
            con.execute("insert into lab.event_label values (?, ?, 'ind_ew', ?, 0.07, ?)",
                        [k, horizon, days[no[d] - 1 + horizon], net])  # fmt: skip
    con.execute(f"create table stg.price_yahoo ({prices.YAHOO_COLUMNS})")
    con.executemany(
        "insert into stg.price_yahoo values ('SPY', ?, 1, 1, 1, 400, 1e6, 400, 0, 1, '')",
        [(d,) for d in days],
    )
    report = dataset.build(con, params, paths)
    yield con, report, signals, days, no, paths
    con.close()


def part(con, fold, event):
    hit = con.execute(
        "select part from ml.dataset_fold where fold = ? and event_id = ?", [fold, event]
    ).fetchone()
    return hit[0] if hit else None


def test_only_clusters_with_a_target_are_rows(built):
    con, report, signals, *_ = built
    ids = {r[0] for r in con.execute("select event_id from ml.dataset").fetchall()}
    assert ids == set(signals) - {"no_cost", "b1_2017"}
    assert report.rows == len(ids)


def test_slices_and_purging_of_fold_2019(built):
    con, *_ = built
    assert part(con, 2019, "fit_2016") == "fit"
    assert part(con, 2019, "tune_2018") == "tune"
    assert part(con, 2019, "late_tune") == "purged"  # window reaches the calibration slice
    assert part(con, 2019, "cal_2018") == "calibrate"
    assert part(con, 2019, "cross_2018") == "purged"  # window crosses into the test year
    assert part(con, 2019, "test_2019") == "test"


def test_an_event_purged_at_one_boundary_trains_later(built):
    con, *_ = built
    assert part(con, 2020, "cross_2018") == "purged"  # ends in Feb 2019, inside 2020's tuning
    assert part(con, 2021, "cross_2018") == "fit"
    assert part(con, 2020, "test_2019") == "purged"  # tuning slice; window reaches July 2019


def test_no_training_window_crosses_its_boundary(built, params):
    con, *_ = built
    for fold in params["rules"]["ml_test_years"]:
        start = date(fold, 1, 1)
        tune = date(fold - 1, 1, 1)
        calibrate = date(fold - 1, 7, 1)
        for event, part_, end in con.execute(
            "select f.event_id, f.part, d.window_end from ml.dataset_fold f "
            "join ml.dataset d using (event_id) where f.fold = ?", [fold]
        ).fetchall():  # fmt: skip
            limit = {"fit": tune, "tune": calibrate, "calibrate": start}.get(part_)
            if limit:
                assert end < limit and end <= date(2022, 12, 31), (fold, event, part_)


def test_overlapping_windows_share_their_days(built):
    con, *_ = built
    u = dict(con.execute("select event_id, uniqueness from ml.dataset").fetchall())
    shared = H - 10
    assert u["overlap_a"] == pytest.approx((10 + shared / 2) / H)
    assert u["overlap_b"] == pytest.approx((10 + shared / 2) / H)
    assert u["fit_2016"] == pytest.approx(1.0)


def test_training_weights_have_mean_one(built):
    con, *_ = built
    for fold, mean in con.execute(
        "select fold, avg(weight) from ml.dataset_fold "
        "where part in ('fit', 'tune', 'calibrate') group by 1"
    ).fetchall():
        assert mean == pytest.approx(1.0), fold


def test_dollar_features_are_scaled_by_spy_and_logged(built):
    con, *_ = built
    x2, x12, x16, x17, x3 = con.execute(
        "select x_f2, x_f12, x_f16, x_f17, x_f3 from ml.dataset limit 1"
    ).fetchone()
    assert (x2, x12, x16, x17) == pytest.approx(
        (math.log(1 + 2 / 400), 0.0, math.log(1 + 16 / 400), math.log(1 + 17 / 400))
    )
    assert x3 == 3.0


def test_the_horizon_table_has_every_horizon_of_each_cluster(built):
    con, _, signals, *_ = built
    got = con.execute(
        "select horizon, count(*) from ml.dataset_horizon group by 1 order by 1"
    ).fetchall()
    clusters = len(signals) - 2  # no cost, and the B1 event
    assert got == [(21, clusters), (63, clusters), (126, clusters)]
    primary = con.execute("select count(*) from ml.dataset").fetchone()[0]
    assert primary == clusters  # the pre-registered 63-session table is unchanged


def test_each_horizon_is_purged_by_its_own_window(built):
    con, *_ = built
    parts = dict(con.execute(
        "select horizon, part from ml.dataset_horizon_fold "
        "where fold = 2019 and event_id = 'cross_2018'"
    ).fetchall())  # fmt: skip
    # signalled 15 Nov 2018: a 21-session window ends in December and trains; 63 and 126 reach
    # into 2019 (the test year) and are purged
    assert parts == {21: "calibrate", 63: "purged", 126: "purged"}


def test_horizon_weights_use_their_own_window_length(built):
    con, *_ = built
    u = {h: x for h, x in con.execute(
        "select horizon, uniqueness from ml.dataset_horizon where event_id = 'overlap_a'"
    ).fetchall()}  # fmt: skip
    assert u[21] == pytest.approx((10 + 11 / 2) / 21)  # ten days alone, eleven shared with b
    assert u[126] == pytest.approx((10 + 116 / 2) / 126)
    for fold, horizon, mean in con.execute(
        "select fold, horizon, avg(weight) from ml.dataset_horizon_fold "
        "where part in ('fit', 'tune', 'calibrate') group by 1, 2"
    ).fetchall():
        assert mean == pytest.approx(1.0), (fold, horizon)


def test_fold_one_is_dropped_below_the_minimum_fit_size(built):
    con, *_ = built
    dropped = dict(con.execute(
        "select fold, bool_or(dropped) from ml.dataset_summary group by 1"
    ).fetchall())  # fmt: skip
    assert dropped[2019] is True and dropped[2020] is False


def test_version_row_and_parquet_copies(built):
    con, report, *_, paths = built
    assert con.execute("select version, rows from ml.dataset_version").fetchall() == [
        (report.version, report.rows)
    ]
    for name in ("dataset", "dataset_fold", "dataset_horizon", "dataset_horizon_fold"):
        assert (paths.root / "data" / "ml" / f"{name}-{report.version}.parquet").exists()


def test_a_rebuild_gives_the_same_version(built, params):
    con, report, *_, paths = built
    assert dataset.build(con, params, paths).version == report.version
