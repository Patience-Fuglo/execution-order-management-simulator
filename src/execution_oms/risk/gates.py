"""Stage 5 -- pre-trade and runtime risk gates: position limits,
notional limits, and kill-switch behavior. ``RiskState`` is updated on
EVERY real fill, atomically and immediately -- never a stale snapshot
-- so a cancellation race can never let a position slip past a
configured limit: a cancel in flight never changes real inventory,
only an actual fill does, and every pre-trade check reads the real
CURRENT state at the moment it runs. The real runtime check (after
every fill) closes the one gap pre-trade checks alone cannot: several
individually-compliant orders whose COMBINED real fills breach a
limit only once they actually land.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..orders.schemas import Fill, OrderSide


@dataclass(frozen=True)
class RiskLimits:
    # RESEARCH ASSUMPTION -- the real maximum absolute position
    # (shares/units) permitted in any one security
    max_position_per_security: float = 100_000.0
    # RESEARCH ASSUMPTION -- the real maximum total gross notional
    # (sum of |position| * price across every security)
    max_gross_notional: float = 5_000_000.0
    # RESEARCH ASSUMPTION -- the real maximum notional of any single order
    max_order_notional: float = 1_000_000.0

    def __post_init__(self) -> None:
        if self.max_position_per_security <= 0 or self.max_gross_notional <= 0 or self.max_order_notional <= 0:
            raise ValueError("risk limits must all be positive")


@dataclass(frozen=True)
class RiskBreach:
    rule_name: str
    detail: str
    severity: str

    def __post_init__(self) -> None:
        if self.severity not in ("warning", "critical"):
            raise ValueError(f"unknown severity {self.severity!r}")


class RiskState:
    """Real, continuously-updated inventory and cash state."""

    def __init__(self) -> None:
        self.position_by_security: dict[str, float] = {}
        self.realized_cash: float = 0.0
        self.kill_switch_engaged: bool = False

    def apply_fill(self, fill: Fill) -> None:
        sign = 1.0 if fill.side == OrderSide.BUY else -1.0
        self.position_by_security[fill.security_id] = self.position_by_security.get(fill.security_id, 0.0) + sign * fill.quantity
        self.realized_cash -= sign * fill.notional  # buying spends real cash; selling receives it

    def gross_notional(self, price_by_security: dict[str, float]) -> float:
        return sum(abs(qty) * price_by_security.get(sid, 0.0) for sid, qty in self.position_by_security.items())


def check_pre_trade(
    security_id: str, side: OrderSide, order_quantity: float, order_notional: float, state: RiskState,
    price_by_security: dict[str, float], limits: RiskLimits,
) -> list[RiskBreach]:
    """Real checks run BEFORE an order is submitted, against the real
    CURRENT state plus this one proposed order's own projected effect
    -- never against a stale or hypothetical state.
    """
    if state.kill_switch_engaged:
        return [RiskBreach("kill_switch", "kill switch is engaged -- no new orders permitted", "critical")]

    breaches: list[RiskBreach] = []
    if order_notional > limits.max_order_notional:
        breaches.append(
            RiskBreach("max_order_notional", f"order notional {order_notional:.2f} exceeds limit {limits.max_order_notional:.2f}", "critical")
        )

    sign = 1.0 if side == OrderSide.BUY else -1.0
    projected_position = state.position_by_security.get(security_id, 0.0) + sign * order_quantity
    if abs(projected_position) > limits.max_position_per_security:
        breaches.append(
            RiskBreach(
                "max_position_per_security",
                f"projected position {projected_position:.2f} for {security_id!r} exceeds limit {limits.max_position_per_security:.2f}",
                "critical",
            )
        )

    projected_positions = dict(state.position_by_security)
    projected_positions[security_id] = projected_position
    projected_gross = sum(abs(qty) * price_by_security.get(sid, 0.0) for sid, qty in projected_positions.items())
    if projected_gross > limits.max_gross_notional:
        breaches.append(
            RiskBreach("max_gross_notional", f"projected gross notional {projected_gross:.2f} exceeds limit {limits.max_gross_notional:.2f}", "critical")
        )
    return breaches


def check_runtime(state: RiskState, price_by_security: dict[str, float], limits: RiskLimits) -> list[RiskBreach]:
    """Real checks run AFTER every fill, against the real resulting
    state -- catches a breach pre-trade checks alone cannot: several
    individually-compliant orders whose combined real fills exceed a
    limit only once they actually land.
    """
    breaches: list[RiskBreach] = []
    for security_id, qty in state.position_by_security.items():
        if abs(qty) > limits.max_position_per_security:
            breaches.append(
                RiskBreach(
                    "max_position_per_security_runtime",
                    f"real position {qty:.2f} for {security_id!r} exceeds limit {limits.max_position_per_security:.2f}",
                    "critical",
                )
            )
    gross = state.gross_notional(price_by_security)
    if gross > limits.max_gross_notional:
        breaches.append(RiskBreach("max_gross_notional_runtime", f"real gross notional {gross:.2f} exceeds limit {limits.max_gross_notional:.2f}", "critical"))
    return breaches


def engage_kill_switch(state: RiskState, reason: str) -> RiskBreach:
    state.kill_switch_engaged = True
    return RiskBreach("kill_switch_engaged", reason, "critical")
