"""Stage 1 -- a real, deterministic event-driven architecture. Every
event carries a real simulation time plus a monotonic sequence number
(the same real tiebreaker convention ``orderbook-priority-sim``'s own
``Order.seq`` already uses, reused here for the same reason: wall-
clock time is ambiguous when multiple real events happen "at the same
instant" in a replay, a monotonic counter is not).

Events are processed strictly in ``(sim_time, seq)`` order via a real
binary heap -- deterministic regardless of insertion order, and
reproducible: the SAME sequence of scheduled events, processed through
the SAME heap discipline, always yields the SAME processing order and
the SAME append-only ``event_log``.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field


@dataclass(frozen=True, order=True)
class Event:
    """One real, ordered simulation event. ``sim_time``/``seq`` are the
    real sort keys (heap/tiebreak order); ``event_type``/``event_id``
    break further ties only in the vanishingly rare case two events
    share both (impossible in practice, since ``seq`` is a real
    monotonic counter -- kept anyway for a total, deterministic order).
    ``payload`` is never compared (a ``dict`` has no real ordering) and
    carries this event's own real data.
    """

    sim_time: float
    seq: int
    event_type: str
    event_id: str
    payload: dict = field(default_factory=dict, compare=False)


class DuplicateEventError(ValueError):
    """Raised when a caller tries to schedule an event whose real
    ``event_id`` has already been scheduled -- a duplicate submission,
    never silently re-processed."""


class SimulationClock:
    """A real, deterministic discrete-event clock: a priority queue of
    scheduled events, a monotonic sequence counter, an append-only
    ``event_log`` (the real, reproducible record of everything that
    was actually processed, in the order it was processed), and a set
    of already-processed real event ids for idempotent handling.
    """

    def __init__(self, start_time: float = 0.0) -> None:
        self.now = start_time
        self._heap: list[Event] = []
        self._seq_counter = itertools.count(1)
        self._scheduled_event_ids: set[str] = set()
        self._processed_event_ids: set[str] = set()
        self.event_log: list[Event] = []

    def schedule(self, sim_time: float, event_type: str, payload: dict | None = None, event_id: str | None = None) -> Event:
        """Schedules a real event no earlier than the clock's current
        real time -- scheduling into the past is a real look-ahead/
        causality violation, never silently clamped.
        """
        if sim_time < self.now:
            raise ValueError(f"cannot schedule {event_type!r} in the past: sim_time={sim_time} < now={self.now}")
        seq = next(self._seq_counter)
        resolved_id = event_id or f"{event_type}-{seq}"
        if resolved_id in self._scheduled_event_ids:
            raise DuplicateEventError(f"event id {resolved_id!r} already scheduled")
        self._scheduled_event_ids.add(resolved_id)
        event = Event(sim_time=sim_time, seq=seq, event_type=event_type, event_id=resolved_id, payload=payload or {})
        heapq.heappush(self._heap, event)
        return event

    def has_pending_events(self) -> bool:
        return bool(self._heap)

    def pop_next(self) -> Event | None:
        """Pops the real next event in strict ``(sim_time, seq)`` order,
        advances ``now`` to that event's real time, and appends it to
        the real, reproducible event log.
        """
        if not self._heap:
            return None
        event = heapq.heappop(self._heap)
        self.now = event.sim_time
        self.event_log.append(event)
        return event

    def is_duplicate(self, event_id: str) -> bool:
        """Real idempotency check: has this exact event id already
        been marked processed -- a duplicate real event (the same
        message replayed twice, e.g. an exchange retransmit) should
        never be acted on a second time.
        """
        return event_id in self._processed_event_ids

    def mark_processed(self, event_id: str) -> None:
        self._processed_event_ids.add(event_id)
