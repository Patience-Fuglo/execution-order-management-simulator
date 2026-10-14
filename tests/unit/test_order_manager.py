from execution_oms.events import SimulationClock
from execution_oms.market import Venue, VenueConfig
from execution_oms.orders.order_manager import LatencyConfig, OrderManager
from execution_oms.orders.schemas import Order, OrderSide, OrderState, OrderType, TimeInForce


def _setup(ack_latency=0.5, cancel_latency=0.5):
    clock = SimulationClock()
    venue = Venue("A", 100.0, VenueConfig(n_price_levels=1, base_level_size=1000.0, counterparty_aggressive_fraction=0.0, random_seed=1))
    manager = OrderManager(clock, {"A": venue}, LatencyConfig(ack_latency=ack_latency, cancel_latency=cancel_latency))
    return clock, venue, manager


def _drain(clock, manager):
    while clock.has_pending_events():
        event = clock.pop_next()
        manager.process_event(event)


def test_market_order_fills_against_real_resting_counterparty_liquidity():
    clock, venue, manager = _setup()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=50.0, time_in_force=TimeInForce.DAY, created_at=0.0)
    manager.submit_order(order)
    _drain(clock, manager)
    assert order.state == OrderState.FILLED
    assert len(manager.fills) >= 1


def test_marketable_limit_order_crosses_the_book_immediately():
    clock, venue, manager = _setup()
    best_ask = venue.book.best_ask()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=10.0, time_in_force=TimeInForce.DAY, created_at=0.0, limit_price=best_ask + 1.0)
    manager.submit_order(order)
    _drain(clock, manager)
    assert order.state == OrderState.FILLED
    assert order.avg_fill_price <= best_ask + 1.0 + 1e-9


def test_non_marketable_limit_order_rests_on_the_book():
    clock, venue, manager = _setup()
    best_bid = venue.book.best_bid()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=10.0, time_in_force=TimeInForce.DAY, created_at=0.0, limit_price=best_bid - 1.0)
    manager.submit_order(order)
    _drain(clock, manager)
    assert order.state == OrderState.ACKNOWLEDGED
    assert order.filled_quantity == 0.0
    assert order.order_id in venue.book._order_index


def test_ioc_limit_order_cancels_its_unfilled_remainder():
    clock, venue, manager = _setup()
    best_ask = venue.book.best_ask()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=10_000.0, time_in_force=TimeInForce.IOC, created_at=0.0, limit_price=best_ask + 1.0)
    manager.submit_order(order)
    _drain(clock, manager)
    assert order.state == OrderState.CANCELLED
    assert order.order_id not in venue.book._order_index


def test_cancel_request_on_a_resting_order_eventually_cancels_it():
    clock, venue, manager = _setup(cancel_latency=0.3)
    best_bid = venue.book.best_bid()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=10.0, time_in_force=TimeInForce.GTC, created_at=0.0, limit_price=best_bid - 1.0)
    manager.submit_order(order)
    _drain(clock, manager)
    assert order.state == OrderState.ACKNOWLEDGED
    manager.request_cancel("o1")
    _drain(clock, manager)
    assert order.state == OrderState.CANCELLED
    assert order.order_id not in venue.book._order_index


def test_cancel_racing_an_already_filled_order_is_a_real_no_op():
    clock, venue, manager = _setup()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0, time_in_force=TimeInForce.DAY, created_at=0.0)
    manager.submit_order(order)
    _drain(clock, manager)
    assert order.state == OrderState.FILLED
    manager.request_cancel("o1")  # must not raise or change state
    assert order.state == OrderState.FILLED


def test_duplicate_event_processing_never_double_applies_a_fill():
    clock, venue, manager = _setup()
    order = Order(order_id="o1", security_id="A", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0, time_in_force=TimeInForce.DAY, created_at=0.0)
    manager.submit_order(order)
    ack_event = clock.pop_next()
    manager.process_event(ack_event)
    filled_qty_after_first = order.filled_quantity
    manager.process_event(ack_event)  # replay the exact same event
    assert order.filled_quantity == filled_qty_after_first
