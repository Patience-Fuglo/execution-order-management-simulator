"""Stage 9 -- the end-to-end orchestration: runs Stages 1-8 once, in
deterministic simulated time, for one real portfolio's desired trades
(from ``portfolio-construction-engine``'s own real
``OptimizationResult``). Every step reuses the exact function/class
that stage already built -- nothing here re-derives any real
computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from portfolio_construction.data import OptimizationResult
from transaction_cost.config import EngineConfig as TransactionCostConfig

from ..algos import ChildOrderSpec, limit_algo, market_algo, participation_constrained_algo, twap_algo, vwap_algo
from ..analytics import ExecutionAnalyticsResult, ReconciliationResult, compute_execution_analytics, reconcile
from ..config import EngineConfig
from ..costs import ExpectedVsRealizedCost, compute_expected_vs_realized
from ..events import SimulationClock
from ..market import Venue
from ..orders import Fill, Order, OrderManager, OrderSide, OrderState
from ..risk import RiskBreach, RiskState, check_pre_trade, check_runtime, engage_kill_switch

_ALGO_REGISTRY: dict[str, Callable[..., list[ChildOrderSpec]]] = {
    "market": market_algo,
    "limit": limit_algo,
    "twap": twap_algo,
    "vwap": vwap_algo,
    "participation": participation_constrained_algo,
}


@dataclass
class SecurityExecutionResult:
    security_id: str
    parent_orders: list[Order]
    fills: list[Fill]
    cost: ExpectedVsRealizedCost
    analytics: list[ExecutionAnalyticsResult]


@dataclass
class ExecutionSimulationResult:
    order_results: dict[str, SecurityExecutionResult]
    reconciliation: ReconciliationResult
    risk_breaches: list[RiskBreach] = field(default_factory=list)
    event_log_length: int = 0


def build_desired_trades(
    optimization_result: OptimizationResult, current_weights: dict[str, float], market_data: dict[str, dict], portfolio_value: float
) -> dict[str, tuple[OrderSide, float, float]]:
    """Real desired trade per security -- ``(side, quantity,
    decision_price)`` -- derived from ``portfolio-construction-
    engine``'s own real ``OptimizationResult`` (target weights) vs.
    real ``current_weights``, the same real convention
    ``transaction-cost-engine``'s own trade-building already uses:
    ``trade_weight = target - current``.
    """
    trades: dict[str, tuple[OrderSide, float, float]] = {}
    security_ids = set(optimization_result.target_weights) | set(current_weights)
    for security_id in security_ids:
        target = optimization_result.target_weights.get(security_id, 0.0)
        current = current_weights.get(security_id, 0.0)
        trade_weight = target - current
        if abs(trade_weight) < 1e-9:
            continue
        price = market_data[security_id]["price"]
        quantity = abs(trade_weight) * portfolio_value / price
        side = OrderSide.BUY if trade_weight > 0 else OrderSide.SELL
        trades[security_id] = (side, quantity, price)
    return trades


def _mid_or_fallback(venue: Venue, fallback: float) -> float:
    bid, ask = venue.book.best_bid(), venue.book.best_ask()
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return bid if bid is not None else (ask if ask is not None else fallback)


def run_execution_simulation(
    optimization_result: OptimizationResult,
    current_weights: dict[str, float],
    market_data: dict[str, dict],
    portfolio_value: float,
    algo_name: str,
    algo_kwargs: dict,
    transaction_cost_cfg: TransactionCostConfig,
    engine_cfg: EngineConfig,
) -> ExecutionSimulationResult:
    """``market_data[security_id]`` must carry ``price``, ``adv_usd``,
    ``daily_volatility``, ``annualized_volatility``, and ``as_of``
    (a real ``pd.Timestamp``, used only for the real EXPECTED-cost
    estimate's own point-in-time record, never for simulated time).
    """
    trades = build_desired_trades(optimization_result, current_weights, market_data, portfolio_value)
    if not trades:
        raise ValueError("no real desired trades to execute -- target and current weights are identical")
    if algo_name not in _ALGO_REGISTRY:
        raise ValueError(f"unknown algo {algo_name!r}, must be one of {sorted(_ALGO_REGISTRY)}")

    clock = SimulationClock(start_time=0.0)
    venues: dict[str, Venue] = {sid: Venue(sid, price, engine_cfg.venue) for sid, (_, _, price) in trades.items()}
    order_manager = OrderManager(clock, venues, engine_cfg.latency, random_seed=engine_cfg.run.random_seed)
    risk_state = RiskState()
    risk_breaches: list[RiskBreach] = []
    price_by_security = {sid: price for sid, (_, _, price) in trades.items()}
    parent_orders_by_security: dict[str, list[Order]] = {sid: [] for sid in trades}

    order_counter = 0
    max_sim_time = 0.0
    algo_fn = _ALGO_REGISTRY[algo_name]

    for security_id, (side, quantity, decision_price) in trades.items():
        schedule = algo_fn(total_quantity=quantity, **algo_kwargs)
        for child in schedule:
            order_counter += 1
            order_id = f"order-{security_id}-{order_counter}"
            order = Order(
                order_id=order_id, security_id=security_id, side=side, order_type=child.order_type, quantity=child.quantity,
                time_in_force=child.time_in_force, created_at=child.sim_time, limit_price=child.limit_price,
            )
            parent_orders_by_security[security_id].append(order)

            order_notional = child.quantity * decision_price
            breaches = check_pre_trade(security_id, side, child.quantity, order_notional, risk_state, price_by_security, engine_cfg.risk_limits)
            if breaches:
                risk_breaches.extend(breaches)
                order.transition(OrderState.REJECTED, child.sim_time)
                order_manager.orders[order_id] = order  # recorded for audit; never actually submitted
                continue

            clock.schedule(child.sim_time, "SUBMIT_ORDER", {"order": order}, event_id=f"submit-{order_id}")
            max_sim_time = max(max_sim_time, child.sim_time)

    simulation_end = max_sim_time + engine_cfg.simulation.post_schedule_horizon
    for security_id in trades:
        clock.schedule(0.0, "MARKET_STEP", {"security_id": security_id}, event_id=f"market-step-{security_id}-0")

    while clock.has_pending_events():
        event = clock.pop_next()
        if event.sim_time > simulation_end:
            break
        if clock.is_duplicate(event.event_id):
            continue

        if event.event_type == "SUBMIT_ORDER":
            clock.mark_processed(event.event_id)
            order_manager.submit_order(event.payload["order"])
            continue

        if event.event_type == "MARKET_STEP":
            clock.mark_processed(event.event_id)
            security_id = event.payload["security_id"]
            venue = venues[security_id]
            raw_fills = venue.step(event.sim_time)
            new_fills = order_manager.on_counterparty_fills(raw_fills)
            next_step_time = event.sim_time + engine_cfg.simulation.market_step_size
            if next_step_time <= simulation_end:
                clock.schedule(next_step_time, "MARKET_STEP", {"security_id": security_id})
        else:
            new_fills = order_manager.process_event(event)

        for fill in new_fills:
            risk_state.apply_fill(fill)
        if new_fills:
            breaches = check_runtime(risk_state, price_by_security, engine_cfg.risk_limits)
            if breaches:
                risk_breaches.extend(breaches)
                engage_kill_switch(risk_state, "real runtime risk breach detected after a fill")

    order_results: dict[str, SecurityExecutionResult] = {}
    for security_id, (side, quantity, decision_price) in trades.items():
        own_fills = [f for f in order_manager.fills if f.security_id == security_id]
        venue = venues[security_id]
        cost = compute_expected_vs_realized(
            security_id, side, quantity, decision_price, market_data[security_id]["as_of"],
            market_data[security_id].get("adv_usd"), market_data[security_id].get("daily_volatility"), portfolio_value,
            transaction_cost_cfg, own_fills,
        )
        post_fill_price = _mid_or_fallback(venue, decision_price)
        analytics = [
            compute_execution_analytics(
                order, [f for f in own_fills if f.order_id == order.order_id], decision_price, post_fill_price,
                market_data[security_id].get("annualized_volatility"), engine_cfg.latency.ack_latency,
            )
            for order in parent_orders_by_security[security_id]
        ]
        order_results[security_id] = SecurityExecutionResult(
            security_id=security_id, parent_orders=parent_orders_by_security[security_id], fills=own_fills, cost=cost, analytics=analytics,
        )

    reconciliation = reconcile(risk_state, order_manager.fills, price_by_security)

    return ExecutionSimulationResult(
        order_results=order_results, reconciliation=reconciliation, risk_breaches=risk_breaches, event_log_length=len(clock.event_log)
    )
