import pytest

from execution_oms.analytics.execution_analytics import (
    compute_execution_analytics,
    compute_implementation_shortfall,
    compute_maker_taker_split,
    compute_realized_adverse_selection,
    reconcile,
)
from execution_oms.orders.schemas import Fill, Order, OrderSide, OrderState, OrderType, TimeInForce
from execution_oms.risk.gates import RiskState


def _fill(price, quantity, side=OrderSide.BUY, is_maker=False, security_id="A"):
    return Fill(fill_id="f", order_id="o1", security_id=security_id, side=side, sim_time=0.0, price=price, quantity=quantity, is_maker=is_maker)


def test_implementation_shortfall_none_when_unfilled():
    assert compute_implementation_shortfall(OrderSide.BUY, 100.0, None) is None


def test_implementation_shortfall_positive_when_buy_executes_worse():
    assert compute_implementation_shortfall(OrderSide.BUY, 100.0, 101.0) == pytest.approx(0.01)


def test_implementation_shortfall_positive_when_sell_executes_worse():
    assert compute_implementation_shortfall(OrderSide.SELL, 100.0, 99.0) == pytest.approx(0.01)


def test_maker_taker_split_separates_by_real_is_maker_flag():
    fills = [_fill(100.0, 10.0, is_maker=True), _fill(101.0, 5.0, is_maker=False)]
    maker_qty, taker_qty, maker_fraction = compute_maker_taker_split(fills)
    assert maker_qty == 10.0
    assert taker_qty == 5.0
    assert maker_fraction == pytest.approx(1000.0 / (1000.0 + 505.0))


def test_realized_adverse_selection_positive_when_price_keeps_moving_against_a_buyer():
    assert compute_realized_adverse_selection(OrderSide.BUY, avg_fill_price=100.0, post_fill_price=101.0) == pytest.approx(0.01)


def test_realized_adverse_selection_none_without_fills_or_post_price():
    assert compute_realized_adverse_selection(OrderSide.BUY, None, 101.0) is None
    assert compute_realized_adverse_selection(OrderSide.BUY, 100.0, None) is None


def test_compute_execution_analytics_end_to_end():
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100.0, time_in_force=TimeInForce.DAY, created_at=0.0)
    order.transition(OrderState.ACKNOWLEDGED, 0.1)
    order.apply_fill(100.0, 100.5, 0.2)
    fills = [_fill(100.5, 100.0)]
    result = compute_execution_analytics(order, fills, decision_price=100.0, post_fill_price=101.0, annualized_volatility=0.25, latency_seconds=0.5)
    assert result.fill_rate == pytest.approx(1.0)
    assert result.implementation_shortfall == pytest.approx(0.005)
    assert result.theoretical_adverse_selection is not None


def test_reconcile_matches_when_state_was_maintained_correctly():
    state = RiskState()
    fills = [_fill(100.0, 10.0, side=OrderSide.BUY), _fill(101.0, 5.0, side=OrderSide.SELL)]
    for f in fills:
        state.apply_fill(f)
    result = reconcile(state, fills, {"A": 100.0})
    assert result.reconciles
    assert result.discrepancy_detail == ()


def test_reconcile_catches_a_real_desync_between_ledger_and_fill_log():
    state = RiskState()
    real_fills = [_fill(100.0, 10.0, side=OrderSide.BUY)]
    for f in real_fills:
        state.apply_fill(f)
    # simulate a real bug: an extra, unaccounted fill exists in the raw log
    # that never actually hit the maintained ledger
    extra_fill = _fill(100.0, 5.0, side=OrderSide.BUY)
    result = reconcile(state, real_fills + [extra_fill], {"A": 100.0})
    assert not result.reconciles
    assert result.discrepancy_detail


def test_reconcile_total_pnl_reflects_cash_plus_mark_to_market():
    state = RiskState()
    fill = _fill(100.0, 10.0, side=OrderSide.BUY)
    state.apply_fill(fill)
    result = reconcile(state, [fill], {"A": 110.0})
    assert result.total_pnl == pytest.approx(-1000.0 + 1100.0)
