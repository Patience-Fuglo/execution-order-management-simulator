import pytest

from execution_oms.events import DuplicateEventError, SimulationClock


def test_events_pop_in_strict_sim_time_order_regardless_of_schedule_order():
    clock = SimulationClock()
    clock.schedule(5.0, "B")
    clock.schedule(1.0, "A")
    clock.schedule(3.0, "C")
    order = []
    while clock.has_pending_events():
        order.append(clock.pop_next().event_type)
    assert order == ["A", "C", "B"]


def test_equal_sim_time_events_break_ties_by_arrival_sequence():
    clock = SimulationClock()
    clock.schedule(1.0, "first")
    clock.schedule(1.0, "second")
    first = clock.pop_next()
    second = clock.pop_next()
    assert (first.event_type, second.event_type) == ("first", "second")


def test_clock_advances_now_to_each_popped_events_sim_time():
    clock = SimulationClock()
    clock.schedule(2.5, "A")
    clock.pop_next()
    assert clock.now == 2.5


def test_scheduling_into_the_past_is_rejected():
    clock = SimulationClock()
    clock.schedule(5.0, "A")
    clock.pop_next()
    with pytest.raises(ValueError):
        clock.schedule(4.0, "B")


def test_duplicate_event_id_cannot_be_scheduled_twice():
    clock = SimulationClock()
    clock.schedule(1.0, "A", event_id="x")
    with pytest.raises(DuplicateEventError):
        clock.schedule(2.0, "B", event_id="x")


def test_idempotent_processing_tracks_marked_events():
    clock = SimulationClock()
    clock.schedule(1.0, "A", event_id="x")
    event = clock.pop_next()
    assert not clock.is_duplicate(event.event_id)
    clock.mark_processed(event.event_id)
    assert clock.is_duplicate(event.event_id)


def test_event_log_is_append_only_and_reproducible():
    clock = SimulationClock()
    clock.schedule(1.0, "A")
    clock.schedule(2.0, "B")
    clock.pop_next()
    clock.pop_next()
    assert [e.event_type for e in clock.event_log] == ["A", "B"]
