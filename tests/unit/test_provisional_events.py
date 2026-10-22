from datetime import date, timedelta

from sentinel.provisional.events import Filing, detect_events

D0 = date(2019, 3, 1)


def f(acc, day_offset, owners, value=60_000, ceo=False, cik="100", start=D0):
    return Filing(acc, cik, start + timedelta(days=day_offset), frozenset(owners), ceo, value)


def detect(filings):
    return detect_events(
        filings,
        window_days=14,
        min_value=100_000,
        min_buyers=2,
        cooldown_days=91,
        labelled_start=date(2016, 1, 1),
    )


def test_two_buyers_13_days_apart_make_a_cluster_on_the_later_date():
    events = detect([f("a", 0, {"X"}), f("b", 13, {"Y"})])
    assert [(e.group, e.signal_date, e.n_buyers) for e in events] == [("A", D0 + timedelta(13), 2)]
    assert events[0].total_value_usd == 120_000
    assert events[0].member_accessions == ("a", "b")


def test_14_days_apart_is_outside_the_window():
    assert detect([f("a", 0, {"X"}), f("b", 14, {"Y"})]) == []


def test_joint_filing_is_one_buyer():
    assert detect([f("a", 0, {"X", "Y"}, value=200_000)]) == []


def test_overlapping_owner_sets_are_one_buyer():
    assert detect([f("a", 0, {"X", "Y"}), f("b", 5, {"Y"})]) == []


def test_ceo_alone_is_b1_and_with_another_buyer_is_a():
    solo = detect([f("a", 0, {"C"}, value=100_000, ceo=True)])
    assert [e.group for e in solo] == ["B1"]
    same_day = detect([f("a", 0, {"C"}, value=100_000, ceo=True), f("b", 0, {"X"}, value=10_000)])
    assert [e.group for e in same_day] == ["A"]
    later = detect([f("a", 0, {"C"}, value=100_000, ceo=True), f("b", 2, {"X"}, value=10_000)])
    assert [e.group for e in later] == ["B1", "A"]
    assert later[1].signal_date == D0 + timedelta(2)


def test_b1_needs_ceo_or_cfo_and_minimum_value():
    assert detect([f("a", 0, {"D"}, value=150_000)]) == []
    assert detect([f("a", 0, {"C"}, value=99_999, ceo=True)]) == []


def test_cooldown_91_days_per_group():
    base = [f("a", 0, {"X"}), f("b", 1, {"Y"})]
    blocked = detect(base + [f("c", 90, {"X"}), f("d", 91, {"Y"})])  # qualifies 90 days later
    assert len(blocked) == 1
    allowed = detect(base + [f("c", 91, {"X"}), f("d", 92, {"Y"})])
    assert [e.signal_date for e in allowed] == [D0 + timedelta(1), D0 + timedelta(92)]


def test_cooldown_is_separate_per_group():
    events = detect(
        [f("a", 0, {"X"}), f("b", 1, {"Y"}), f("c", 30, {"C"}, value=100_000, ceo=True)]
    )
    assert [e.group for e in events] == ["A", "B1"]


def test_pre_2016_event_starts_a_cooldown_into_2016():
    start = date(2015, 12, 1)
    events = detect(
        [
            f("a", 0, {"X"}, start=start),
            f("b", 1, {"Y"}, start=start),
            f("c", 45, {"X"}, start=start),
            f("d", 46, {"Y"}, start=start),
        ]
    )
    assert [e.signal_date for e in events] == [date(2015, 12, 2)]
    assert events[0].in_labelled_window is False


def test_labelled_window_flag():
    events = detect([f("a", 0, {"X"}), f("b", 1, {"Y"})])
    assert events[0].in_labelled_window is True


def test_issuers_are_independent():
    events = detect([f("a", 0, {"X"}, cik="1"), f("b", 1, {"Y"}, cik="2")])
    assert events == []
