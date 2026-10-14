"""Stage 7 -- transaction-cost and market-impact analysis: distinguishes
the ESTIMATED cost (from ``transaction-cost-engine``'s own real cost
model, computed once at decision time from reference price/ADV/
volatility -- never reimplemented here) from the SIMULATED REALIZED
cost (measured directly from this engine's own actual fills against
the real decision price). The two are never blended into one number
and never double-counted: the realized figure below comes purely from
real fill prices actually produced by the simulated order book; the
estimated figure is kept as a separate, independent benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd
from transaction_cost.config import EngineConfig as TransactionCostConfig
from transaction_cost.data.schemas import TradeOrder
from transaction_cost.execution.total_cost import compute_total_execution_cost

from ..orders.schemas import Fill, OrderSide


@dataclass(frozen=True)
class ExpectedVsRealizedCost:
    security_id: str
    decision_price: float
    expected_cost_fraction: float
    realized_cost_fraction: float
    realized_avg_fill_price: float | None
    total_filled_quantity: float
    fill_rate: float


def compute_expected_cost(
    security_id: str,
    side: OrderSide,
    quantity: float,
    decision_price: float,
    decision_timestamp: pd.Timestamp,
    adv_usd: float | None,
    daily_volatility: float | None,
    portfolio_value: float,
    transaction_cost_cfg: TransactionCostConfig,
) -> float:
    """Real ESTIMATED execution cost, reusing
    ``transaction_cost.execution.total_cost.compute_total_execution_cost``
    directly -- none of that cost math (spread, impact, slippage,
    fees) is reimplemented here.
    """
    trade_weight = quantity * decision_price / portfolio_value
    if side == OrderSide.SELL:
        trade_weight = -trade_weight
    order = TradeOrder(
        security_id=security_id, as_of=decision_timestamp, trade_weight=trade_weight, price=decision_price,
        adv_usd=adv_usd, daily_volatility=daily_volatility, portfolio_value=portfolio_value,
    )
    return compute_total_execution_cost(order, transaction_cost_cfg).total_cost_fraction


def compute_realized_cost(fills: Sequence[Fill], side: OrderSide, decision_price: float) -> tuple[float, float | None, float]:
    """Real realized execution cost, measured directly from actual
    simulated fills: the real average fill price vs. the real
    decision price, signed so a WORSE real execution (paying more to
    buy, receiving less to sell) is always a positive real cost.
    Returns ``(total_filled_quantity, avg_fill_price, realized_cost_fraction)``.
    """
    total_qty = sum(f.quantity for f in fills)
    if total_qty <= 0:
        return 0.0, None, 0.0
    avg_fill_price = sum(f.price * f.quantity for f in fills) / total_qty
    sign = 1.0 if side == OrderSide.BUY else -1.0
    realized_cost_fraction = sign * (avg_fill_price - decision_price) / decision_price
    return total_qty, avg_fill_price, realized_cost_fraction


def compute_expected_vs_realized(
    security_id: str,
    side: OrderSide,
    ordered_quantity: float,
    decision_price: float,
    decision_timestamp: pd.Timestamp,
    adv_usd: float | None,
    daily_volatility: float | None,
    portfolio_value: float,
    transaction_cost_cfg: TransactionCostConfig,
    fills: Sequence[Fill],
) -> ExpectedVsRealizedCost:
    expected = compute_expected_cost(
        security_id, side, ordered_quantity, decision_price, decision_timestamp, adv_usd, daily_volatility, portfolio_value,
        transaction_cost_cfg,
    )
    total_qty, avg_fill_price, realized = compute_realized_cost(fills, side, decision_price)
    return ExpectedVsRealizedCost(
        security_id=security_id,
        decision_price=decision_price,
        expected_cost_fraction=expected,
        realized_cost_fraction=realized,
        realized_avg_fill_price=avg_fill_price,
        total_filled_quantity=total_qty,
        fill_rate=total_qty / ordered_quantity if ordered_quantity > 0 else 0.0,
    )
