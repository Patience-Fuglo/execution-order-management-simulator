"""Stage 4 -- order management: submission, cancellation, time-in-
force, and realistic acknowledgment/cancellation latency. All actual
matching is delegated to the real ``orderbook_sim.OrderBook`` (via
``Venue``) -- this module owns the real order lifecycle on top of it:
WHEN a submission/cancel actually reaches the book (simulated
latency, with an optional real latency-spike scenario), and the real
state-machine transitions around it.

A real gap in ``orderbook_sim.OrderBook`` this module works around
WITHOUT modifying that repo: ``add_limit_order`` never checks whether
a new limit order actually crosses the opposing book (a real
"marketable limit order" should trade immediately up to its own limit
price, the same as a real exchange). This is handled here using only
that engine's own existing real primitives: the real marketable
quantity (opposing depth at prices within our limit) is computed
directly from `book.asks`/`book.bids`, then `market_order` is called
for exactly that quantity -- since it walks price levels best-first,
giving it exactly the marketable quantity makes it stop precisely at
the real crossable boundary, correctly respecting the limit price
without any new matching logic duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..events.schemas import Event, SimulationClock
from ..market.venue import Venue
from .schemas import Fill, Order, OrderSide, OrderState, OrderType, TimeInForce


@dataclass(frozen=True)
class LatencyConfig:
    # RESEARCH ASSUMPTION -- real simulated acknowledgment/cancel delay
    ack_latency: float = 0.5
    cancel_latency: float = 0.5
    # RESEARCH ASSUMPTION -- the real probability any one latency draw
    # is a "spike" (the failure scenario), and the real multiplier
    # applied to the base latency when it is
    spike_probability: float = 0.0
    spike_multiplier: float = 10.0

    def __post_init__(self) -> None:
        if self.ack_latency < 0 or self.cancel_latency < 0:
            raise ValueError("latencies cannot be negative")
        if not 0.0 <= self.spike_probability <= 1.0:
            raise ValueError("spike_probability must be in [0, 1]")
        if self.spike_multiplier < 1.0:
            raise ValueError("spike_multiplier must be >= 1.0")


class OrderManager:
    """Owns every real order THIS engine has submitted (never a
    venue's own synthetic counterparty orders) and drives its real
    lifecycle through the simulation clock's event queue.
    """

    def __init__(self, clock: SimulationClock, venues: dict[str, Venue], latency_cfg: LatencyConfig, random_seed: int = 7) -> None:
        self.clock = clock
        self.venues = venues
        self.latency_cfg = latency_cfg
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self._rng = np.random.default_rng(random_seed)
        self._fill_seq = 0

    def _real_latency(self, base: float) -> float:
        if self._rng.random() < self.latency_cfg.spike_probability:
            return base * self.latency_cfg.spike_multiplier
        return base

    def submit_order(self, order: Order) -> None:
        if order.order_id in self.orders:
            raise ValueError(f"order id {order.order_id} already submitted")
        self.orders[order.order_id] = order
        latency = self._real_latency(self.latency_cfg.ack_latency)
        self.clock.schedule(self.clock.now + latency, "ORDER_ACK", {"order_id": order.order_id}, event_id=f"ack-{order.order_id}")

    def request_cancel(self, order_id: str) -> None:
        order = self.orders.get(order_id)
        if order is None:
            raise ValueError(f"unknown order id {order_id}")
        if order.is_terminal:
            return  # a cancel racing an already-resolved order is a real, expected no-op -- never an error
        order.transition(OrderState.CANCEL_PENDING, self.clock.now)
        latency = self._real_latency(self.latency_cfg.cancel_latency)
        self.clock.schedule(
            self.clock.now + latency, "ORDER_CANCEL_ACK", {"order_id": order_id},
            event_id=f"cancel-ack-{order_id}-{self.clock.now}-{len(order.history)}",
        )

    def process_event(self, event: Event) -> list[Fill]:
        """Dispatches one real event popped from the clock -- the one
        place every order-related event is actually acted on.
        Idempotent: an event id already marked processed is a no-op,
        the real defense against a duplicated/replayed event.
        """
        if self.clock.is_duplicate(event.event_id):
            return []
        self.clock.mark_processed(event.event_id)

        if event.event_type == "ORDER_ACK":
            return self._handle_ack(event)
        if event.event_type == "ORDER_CANCEL_ACK":
            return self._handle_cancel_ack(event)
        return []

    def _handle_ack(self, event: Event) -> list[Fill]:
        order = self.orders[event.payload["order_id"]]
        if order.is_terminal:
            return []  # a cancel raced the ack and already resolved this order first
        order.transition(OrderState.ACKNOWLEDGED, self.clock.now)
        return self._route_to_book(order)

    def _handle_cancel_ack(self, event: Event) -> list[Fill]:
        order = self.orders[event.payload["order_id"]]
        if order.is_terminal:
            return []  # already filled before the cancel caught up -- a real, expected race, not an error
        venue = self.venues[order.security_id]
        venue.book.cancel_order(order.order_id)
        order.transition(OrderState.CANCELLED, self.clock.now)
        return []

    def _record_fill(self, order: Order, price: float, quantity: float, is_maker: bool) -> Fill:
        self._fill_seq += 1
        fill = Fill(
            fill_id=f"fill-{self._fill_seq}", order_id=order.order_id, security_id=order.security_id,
            side=order.side, sim_time=self.clock.now, price=price, quantity=quantity, is_maker=is_maker,
        )
        order.apply_fill(fill.quantity, fill.price, fill.sim_time)
        self.fills.append(fill)
        return fill

    def _route_to_book(self, order: Order) -> list[Fill]:
        venue = self.venues[order.security_id]
        fills: list[Fill] = []
        book_side = "buy" if order.side == OrderSide.BUY else "sell"

        if order.order_type == OrderType.MARKET:
            raw_fills = venue.book.market_order(book_side, order.quantity)
            fills = [self._record_fill(order, r["price"], r["size"], is_maker=False) for r in raw_fills]
        else:
            opposing_book = venue.book.asks if order.side == OrderSide.BUY else venue.book.bids
            crosses = (lambda p: p <= order.limit_price) if order.side == OrderSide.BUY else (lambda p: p >= order.limit_price)
            marketable_qty = sum(sum(o.size for o in resting) for price, resting in opposing_book.items() if crosses(price))
            immediate_qty = min(order.quantity, marketable_qty)
            if immediate_qty > 1e-9:
                raw_fills = venue.book.market_order(book_side, immediate_qty)
                fills = [self._record_fill(order, r["price"], r["size"], is_maker=False) for r in raw_fills]
            if order.remaining_quantity > 1e-9 and not order.is_terminal:
                venue.book.add_limit_order(
                    order.order_id, "bid" if order.side == OrderSide.BUY else "ask", order.limit_price, order.remaining_quantity
                )

        if order.time_in_force == TimeInForce.IOC and not order.is_terminal:
            if order.order_type == OrderType.LIMIT:
                venue.book.cancel_order(order.order_id)
            order.transition(OrderState.CANCELLED, self.clock.now)
        return fills

    def on_counterparty_fills(self, raw_fills: list[dict]) -> list[Fill]:
        """Called by the simulation loop after a venue's own real
        synthetic counterparty flow trades through the book -- any
        real fill whose ``order_id`` matches one of OUR OWN resting
        orders is a real MAKER fill (we sat passively; a counterparty
        market order crossed into us).
        """
        fills: list[Fill] = []
        for raw in raw_fills:
            order = self.orders.get(raw["order_id"])
            if order is None or order.is_terminal:
                continue
            fills.append(self._record_fill(order, raw["price"], raw["size"], is_maker=True))
        return fills
