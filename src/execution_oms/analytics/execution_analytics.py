"""Stage 8 -- execution analytics: implementation shortfall, fill
rate, slippage, adverse selection, maker/taker cost split, and
inventory/P&L reconciliation. Adverse-selection cost reuses
``market_making_sim``'s own real ``expected_adverse_move`` (square-
root-of-time scaled from annualized volatility) as the real
theoretical comparator against the REALIZED post-fill price move this
engine's own simulation actually produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from market_making_sim.latency import expected_adverse_move

from ..orders.schemas import Fill, Order, OrderSide
from ..risk.gates import RiskState


@dataclass(frozen=True)
class ExecutionAnalyticsResult:
    order_id: str
    security_id: str
    ordered_quantity: float
    filled_quantity: float
    fill_rate: float
    decision_price: float
    avg_fill_price: float | None
    implementation_shortfall: float | None
    maker_fill_quantity: float
    taker_fill_quantity: float
    maker_notional_fraction: float
    realized_adverse_selection: float | None
    theoretical_adverse_selection: float | None


@dataclass(frozen=True)
class ReconciliationResult:
    starting_cash: float
    realized_cash: float
    position_by_security: dict[str, float]
    mark_to_market_value: float
    total_pnl: float
    reconciles: bool
    discrepancy_detail: tuple[str, ...]


def compute_implementation_shortfall(side: OrderSide, decision_price: float, avg_fill_price: float | None) -> float | None:
    """Real Perold-style implementation shortfall: the real signed
    cost of actually executing vs. the real DECISION price (the price
    at the moment the trade was decided, before any execution began)
    -- positive means execution was worse than that decision price.
    """
    if avg_fill_price is None:
        return None
    sign = 1.0 if side == OrderSide.BUY else -1.0
    return sign * (avg_fill_price - decision_price) / decision_price


def compute_maker_taker_split(fills: Sequence[Fill]) -> tuple[float, float, float]:
    maker_qty = sum(f.quantity for f in fills if f.is_maker)
    taker_qty = sum(f.quantity for f in fills if not f.is_maker)
    maker_notional = sum(f.notional for f in fills if f.is_maker)
    total_notional = sum(f.notional for f in fills)
    maker_notional_fraction = maker_notional / total_notional if total_notional > 0 else 0.0
    return maker_qty, taker_qty, maker_notional_fraction


def compute_realized_adverse_selection(side: OrderSide, avg_fill_price: float | None, post_fill_price: float | None) -> float | None:
    """Real realized adverse selection: did the real price keep
    moving AGAINST us after we filled (a real sign the counterparty we
    traded against was better informed) -- positive means yes.
    """
    if avg_fill_price is None or post_fill_price is None:
        return None
    sign = 1.0 if side == OrderSide.BUY else -1.0
    return sign * (post_fill_price - avg_fill_price) / avg_fill_price


def compute_execution_analytics(
    order: Order,
    fills: Sequence[Fill],
    decision_price: float,
    post_fill_price: float | None,
    annualized_volatility: float | None,
    latency_seconds: float,
) -> ExecutionAnalyticsResult:
    avg_fill_price = order.avg_fill_price
    maker_qty, taker_qty, maker_notional_fraction = compute_maker_taker_split(fills)

    return ExecutionAnalyticsResult(
        order_id=order.order_id,
        security_id=order.security_id,
        ordered_quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        fill_rate=order.filled_quantity / order.quantity if order.quantity > 0 else 0.0,
        decision_price=decision_price,
        avg_fill_price=avg_fill_price,
        implementation_shortfall=compute_implementation_shortfall(order.side, decision_price, avg_fill_price),
        maker_fill_quantity=maker_qty,
        taker_fill_quantity=taker_qty,
        maker_notional_fraction=maker_notional_fraction,
        realized_adverse_selection=compute_realized_adverse_selection(order.side, avg_fill_price, post_fill_price),
        theoretical_adverse_selection=(
            expected_adverse_move(annualized_volatility, latency_seconds) if annualized_volatility is not None else None
        ),
    )


def reconcile(state: RiskState, fills: Sequence[Fill], price_by_security: dict[str, float], starting_cash: float = 0.0) -> ReconciliationResult:
    """Real reconciliation: INDEPENDENTLY recomputes cash and position
    from the raw real fill log, then compares against the real,
    incrementally-maintained ``RiskState`` -- the real check that
    nothing was lost, double-counted, or desynced anywhere along the
    way, not a tautology that can never fail.
    """
    recomputed_cash = 0.0
    recomputed_positions: dict[str, float] = {}
    for fill in fills:
        sign = 1.0 if fill.side == OrderSide.BUY else -1.0
        recomputed_cash -= sign * fill.notional
        recomputed_positions[fill.security_id] = recomputed_positions.get(fill.security_id, 0.0) + sign * fill.quantity

    discrepancies: list[str] = []
    if abs(recomputed_cash - state.realized_cash) > 1e-6:
        discrepancies.append(f"cash mismatch: recomputed {recomputed_cash:.6f} vs. maintained {state.realized_cash:.6f}")
    for security_id in sorted(set(recomputed_positions) | set(state.position_by_security)):
        recomputed = recomputed_positions.get(security_id, 0.0)
        maintained = state.position_by_security.get(security_id, 0.0)
        if abs(recomputed - maintained) > 1e-6:
            discrepancies.append(f"{security_id}: recomputed position {recomputed:.6f} vs. maintained {maintained:.6f}")

    mark_to_market_value = sum(qty * price_by_security.get(sid, 0.0) for sid, qty in state.position_by_security.items())
    total_pnl = state.realized_cash + mark_to_market_value

    return ReconciliationResult(
        starting_cash=starting_cash,
        realized_cash=state.realized_cash,
        position_by_security=dict(state.position_by_security),
        mark_to_market_value=mark_to_market_value,
        total_pnl=total_pnl,
        reconciles=not discrepancies,
        discrepancy_detail=tuple(discrepancies),
    )
