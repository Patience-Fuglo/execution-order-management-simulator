import pytest

from execution_oms.orders.schemas import Fill, InvalidStateTransitionError, Order, OrderSide, OrderState, OrderType, TimeInForce


def _order(**overrides):
    defaults = dict(
        order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=100.0,
        time_in_force=TimeInForce.DAY, created_at=0.0, limit_price=10.0,
    )
    defaults.update(overrides)
    return Order(**defaults)


def test_new_order_starts_in_new_state_with_history():
    order = _order()
    assert order.state == OrderState.NEW
    assert order.history == [(0.0, OrderState.NEW)]


def test_limit_order_requires_a_limit_price():
    with pytest.raises(ValueError):
        _order(order_type=OrderType.LIMIT, limit_price=None)


def test_valid_transition_sequence():
    order = _order()
    order.transition(OrderState.ACKNOWLEDGED, 0.5)
    order.transition(OrderState.CANCEL_PENDING, 1.0)
    order.transition(OrderState.CANCELLED, 1.5)
    assert order.state == OrderState.CANCELLED
    assert order.is_terminal


def test_invalid_transition_from_new_directly_to_filled_is_rejected():
    order = _order()
    with pytest.raises(InvalidStateTransitionError):
        order.transition(OrderState.FILLED, 1.0)


def test_terminal_state_cannot_transition_further():
    order = _order()
    order.transition(OrderState.REJECTED, 1.0)
    with pytest.raises(InvalidStateTransitionError):
        order.transition(OrderState.ACKNOWLEDGED, 2.0)


def test_partial_fill_then_full_fill_reaches_filled_with_correct_average_price():
    order = _order(quantity=100.0)
    order.transition(OrderState.ACKNOWLEDGED, 0.5)
    order.apply_fill(40.0, 10.0, 1.0)
    assert order.state == OrderState.PARTIALLY_FILLED
    assert order.remaining_quantity == 60.0
    order.apply_fill(60.0, 11.0, 2.0)
    assert order.state == OrderState.FILLED
    assert order.remaining_quantity == 0.0
    assert order.avg_fill_price == pytest.approx((40 * 10.0 + 60 * 11.0) / 100.0)


def test_fill_exceeding_remaining_quantity_is_rejected():
    order = _order(quantity=50.0)
    order.transition(OrderState.ACKNOWLEDGED, 0.5)
    with pytest.raises(ValueError):
        order.apply_fill(60.0, 10.0, 1.0)


def test_fill_rejects_non_positive_order_quantity():
    with pytest.raises(ValueError):
        _order(quantity=0.0)


def test_fill_object_rejects_non_positive_price_or_quantity():
    with pytest.raises(ValueError):
        Fill(fill_id="f1", order_id="o1", security_id="A", side=OrderSide.BUY, sim_time=0.0, price=0.0, quantity=10.0, is_maker=False)
    with pytest.raises(ValueError):
        Fill(fill_id="f1", order_id="o1", security_id="A", side=OrderSide.BUY, sim_time=0.0, price=10.0, quantity=0.0, is_maker=False)


def test_fill_notional_is_price_times_quantity():
    fill = Fill(fill_id="f1", order_id="o1", security_id="A", side=OrderSide.BUY, sim_time=0.0, price=10.0, quantity=5.0, is_maker=True)
    assert fill.notional == 50.0
