"""Stage 6 -- execution algorithms: market, limit, TWAP, VWAP, and
participation-constrained execution. Each real algo produces a
deterministic SCHEDULE of child-order specs from one parent order
intent -- the simulation loop (``pipeline``) is what actually submits
them through the ``OrderManager``; these functions only decide WHEN
and HOW MUCH.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..orders.schemas import OrderType, TimeInForce


@dataclass(frozen=True)
class ChildOrderSpec:
    sim_time: float
    quantity: float
    order_type: OrderType
    limit_price: float | None
    time_in_force: TimeInForce


def market_algo(total_quantity: float, start_time: float) -> list[ChildOrderSpec]:
    """A single real market order, submitted immediately."""
    if total_quantity <= 0:
        raise ValueError("total_quantity must be positive")
    return [ChildOrderSpec(sim_time=start_time, quantity=total_quantity, order_type=OrderType.MARKET, limit_price=None, time_in_force=TimeInForce.DAY)]


def limit_algo(
    total_quantity: float, start_time: float, limit_price: float, time_in_force: TimeInForce = TimeInForce.GTC
) -> list[ChildOrderSpec]:
    """A single real limit order, submitted immediately at a real,
    researcher-specified limit price."""
    if total_quantity <= 0:
        raise ValueError("total_quantity must be positive")
    return [
        ChildOrderSpec(sim_time=start_time, quantity=total_quantity, order_type=OrderType.LIMIT, limit_price=limit_price, time_in_force=time_in_force)
    ]


def twap_algo(
    total_quantity: float, start_time: float, end_time: float, n_slices: int,
    order_type: OrderType = OrderType.MARKET, limit_price: float | None = None,
) -> list[ChildOrderSpec]:
    """Real TIME-weighted slicing: ``n_slices`` equal-sized real child
    orders, evenly spaced across ``[start_time, end_time]``.
    """
    if total_quantity <= 0:
        raise ValueError("total_quantity must be positive")
    if n_slices < 1:
        raise ValueError("n_slices must be >= 1")
    if end_time < start_time:
        raise ValueError("end_time must be >= start_time")

    slice_qty = total_quantity / n_slices
    if n_slices == 1:
        times = [start_time]
    else:
        step = (end_time - start_time) / (n_slices - 1)
        times = [start_time + i * step for i in range(n_slices)]
    return [
        ChildOrderSpec(sim_time=t, quantity=slice_qty, order_type=order_type, limit_price=limit_price, time_in_force=TimeInForce.DAY)
        for t in times
    ]


def vwap_algo(
    total_quantity: float, volume_profile: Sequence[tuple[float, float]],
    order_type: OrderType = OrderType.MARKET, limit_price: float | None = None,
) -> list[ChildOrderSpec]:
    """Real VOLUME-weighted slicing: ``volume_profile`` is a real,
    predeclared sequence of ``(sim_time, expected_volume_share)``
    pairs whose shares must sum to 1.0. Each real child order's size
    is proportional to its real expected share of volume, not to
    elapsed time.
    """
    if total_quantity <= 0:
        raise ValueError("total_quantity must be positive")
    total_share = sum(share for _, share in volume_profile)
    if abs(total_share - 1.0) > 1e-6:
        raise ValueError(f"volume_profile shares must sum to 1.0, got {total_share}")
    return [
        ChildOrderSpec(sim_time=t, quantity=total_quantity * share, order_type=order_type, limit_price=limit_price, time_in_force=TimeInForce.DAY)
        for t, share in volume_profile
    ]


def participation_constrained_algo(
    total_quantity: float, start_time: float, step: float, max_participation_rate: float,
    expected_volume_per_step: Sequence[float], order_type: OrderType = OrderType.MARKET, limit_price: float | None = None,
) -> list[ChildOrderSpec]:
    """Real participation-rate-constrained scheduling -- the same real
    convention ``transaction-cost-engine``'s own ``SchedulingConfig``
    already uses (``max_participation_rate`` of real expected volume
    per step), reused here as a scheduling convention rather than
    duplicated pricing math. Trades at most ``max_participation_rate``
    of each real step's expected volume, continuing across as many
    real steps as needed.
    """
    if total_quantity <= 0:
        raise ValueError("total_quantity must be positive")
    if not 0 < max_participation_rate <= 1:
        raise ValueError("max_participation_rate must be in (0, 1]")

    schedule: list[ChildOrderSpec] = []
    remaining = total_quantity
    t = start_time
    for expected_volume in expected_volume_per_step:
        if remaining <= 1e-9:
            break
        max_this_step = max_participation_rate * expected_volume
        qty = min(remaining, max_this_step)
        if qty > 1e-9:
            schedule.append(ChildOrderSpec(sim_time=t, quantity=qty, order_type=order_type, limit_price=limit_price, time_in_force=TimeInForce.DAY))
            remaining -= qty
        t += step

    if remaining > 1e-9:
        raise ValueError(
            f"{remaining:.4f} real units could not be scheduled within the given expected_volume_per_step and "
            "max_participation_rate -- extend the real volume forecast or relax the rate"
        )
    return schedule
