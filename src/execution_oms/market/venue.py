"""Stage 3 -- market-data and order-book simulation. Wraps
``orderbook_sim.orderbook.OrderBook`` directly for every real matching
mechanic (price-time priority, multi-level walking, queue position,
partial fills) -- none of that is reimplemented here. This module's
own real addition is a DETERMINISTIC, seeded synthetic counterparty
order-flow generator: our own orders alone can never match each
other, so a real market needs real opposing liquidity and real
incoming aggressive flow for our resting orders to fill against.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from orderbook_sim.orderbook import OrderBook


@dataclass(frozen=True)
class VenueConfig:
    # RESEARCH ASSUMPTION -- the real minimum price increment
    tick_size: float = 0.01
    # RESEARCH ASSUMPTION -- how many real price levels of synthetic
    # counterparty liquidity seed each side of the book
    n_price_levels: int = 5
    # RESEARCH ASSUMPTION -- real spacing between seeded levels, in ticks
    level_spacing_in_ticks: int = 1
    # RESEARCH ASSUMPTION -- the real resting size at the best seeded level
    base_level_size: float = 500.0
    # RESEARCH ASSUMPTION -- the real fraction of synthetic counterparty
    # arrivals that are AGGRESSIVE (a market order, which can trade
    # through our own resting orders) rather than passive (a new
    # resting limit order, which only adds liquidity)
    counterparty_aggressive_fraction: float = 0.3
    # RESEARCH ASSUMPTION -- the real mean size (exponential
    # distribution) of one synthetic counterparty arrival
    counterparty_order_size: float = 100.0
    random_seed: int = 1337

    def __post_init__(self) -> None:
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.n_price_levels < 1:
            raise ValueError("n_price_levels must be >= 1")
        if not 0.0 <= self.counterparty_aggressive_fraction <= 1.0:
            raise ValueError("counterparty_aggressive_fraction must be in [0, 1]")
        if self.counterparty_order_size <= 0:
            raise ValueError("counterparty_order_size must be positive")


class Venue:
    """One real instrument's simulated market: a real ``OrderBook``
    plus deterministic synthetic counterparty flow seeded around a
    real reference price. ``last_update_sim_time`` tracks the real
    sim_time of the last market-data change, for the stale-data
    failure scenario.
    """

    def __init__(self, security_id: str, reference_price: float, venue_cfg: VenueConfig) -> None:
        if reference_price <= 0:
            raise ValueError(f"{security_id}: reference_price must be positive")
        self.security_id = security_id
        self.reference_price = reference_price
        self.cfg = venue_cfg
        self.book = OrderBook()
        self._rng = np.random.default_rng(venue_cfg.random_seed)
        self.last_update_sim_time = 0.0
        self._counterparty_seq = 0
        self._seed_book()

    def _next_counterparty_id(self) -> str:
        self._counterparty_seq += 1
        return f"CP-{self.security_id}-{self._counterparty_seq}"

    def _seed_book(self) -> None:
        tick = self.cfg.tick_size
        mid = round(self.reference_price / tick) * tick
        for level in range(1, self.cfg.n_price_levels + 1):
            bid_price = round(mid - level * self.cfg.level_spacing_in_ticks * tick, 10)
            ask_price = round(mid + level * self.cfg.level_spacing_in_ticks * tick, 10)
            size = self.cfg.base_level_size * (self.cfg.n_price_levels - level + 1) / self.cfg.n_price_levels
            self.book.add_limit_order(self._next_counterparty_id(), "bid", bid_price, size)
            self.book.add_limit_order(self._next_counterparty_id(), "ask", ask_price, size)

    def step(self, sim_time: float) -> list[dict]:
        """Advances the real synthetic counterparty flow by exactly
        one real arrival: with the configured, seeded probability,
        either an AGGRESSIVE counterparty market order trades through
        the book (which may fill our own real resting orders, via the
        real ``OrderBook.market_order``), or a PASSIVE counterparty
        limit order joins the book (adding liquidity, never trading).
        Returns the real fills from an aggressive arrival (``[]`` for
        a passive one).
        """
        self.last_update_sim_time = sim_time
        if self._rng.random() < self.cfg.counterparty_aggressive_fraction:
            side = str(self._rng.choice(["buy", "sell"]))
            size = float(self._rng.exponential(self.cfg.counterparty_order_size))
            if size <= 0:
                return []
            return self.book.market_order(side, size)

        side = "bid" if self._rng.random() < 0.5 else "ask"
        best = self.book.best_bid() if side == "bid" else self.book.best_ask()
        tick = self.cfg.tick_size
        if best is not None:
            price = best - tick if side == "bid" else best + tick
        else:
            price = self.reference_price
        size = float(self._rng.exponential(self.cfg.counterparty_order_size))
        if size > 0:
            self.book.add_limit_order(self._next_counterparty_id(), side, round(price, 10), size)
        return []

    def is_stale(self, sim_time: float, staleness_threshold: float) -> bool:
        """A real, direct check for the stale-market-data failure
        scenario: has this venue's own book gone this many real
        sim-time units without an update.
        """
        return (sim_time - self.last_update_sim_time) > staleness_threshold
