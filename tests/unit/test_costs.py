import pandas as pd
import pytest
from transaction_cost.config import EngineConfig as TransactionCostConfig

from execution_oms.costs.expected_vs_realized import compute_expected_cost, compute_expected_vs_realized, compute_realized_cost
from execution_oms.orders.schemas import Fill, OrderSide

TC_CFG = TransactionCostConfig()


def _fill(price, quantity, side=OrderSide.BUY):
    return Fill(fill_id="f", order_id="o", security_id="A", side=side, sim_time=0.0, price=price, quantity=quantity, is_maker=False)


def test_realized_cost_is_zero_when_filled_exactly_at_the_decision_price():
    _, avg_price, cost = compute_realized_cost([_fill(100.0, 50.0)], OrderSide.BUY, decision_price=100.0)
    assert avg_price == pytest.approx(100.0)
    assert cost == pytest.approx(0.0)


def test_buy_filled_above_decision_price_is_a_positive_real_cost():
    _, _, cost = compute_realized_cost([_fill(101.0, 50.0)], OrderSide.BUY, decision_price=100.0)
    assert cost > 0


def test_sell_filled_below_decision_price_is_a_positive_real_cost():
    _, _, cost = compute_realized_cost([_fill(99.0, 50.0)], OrderSide.SELL, decision_price=100.0)
    assert cost > 0


def test_sell_filled_above_decision_price_is_a_negative_real_cost_a_real_gain():
    _, _, cost = compute_realized_cost([_fill(101.0, 50.0)], OrderSide.SELL, decision_price=100.0)
    assert cost < 0


def test_realized_cost_with_no_fills_is_zero_not_fabricated():
    qty, avg_price, cost = compute_realized_cost([], OrderSide.BUY, decision_price=100.0)
    assert qty == 0.0
    assert avg_price is None
    assert cost == 0.0


def test_expected_cost_is_a_real_positive_fraction_for_a_normal_trade():
    expected = compute_expected_cost(
        "A", OrderSide.BUY, 1000.0, 100.0, pd.Timestamp("2020-01-01"), adv_usd=5_000_000.0, daily_volatility=0.02,
        portfolio_value=1.0e8, transaction_cost_cfg=TC_CFG,
    )
    assert expected > 0


def test_expected_vs_realized_combines_both_independently():
    result = compute_expected_vs_realized(
        "A", OrderSide.BUY, 100.0, 100.0, pd.Timestamp("2020-01-01"), adv_usd=5_000_000.0, daily_volatility=0.02,
        portfolio_value=1.0e8, transaction_cost_cfg=TC_CFG, fills=[_fill(100.5, 100.0)],
    )
    assert result.expected_cost_fraction > 0
    assert result.realized_cost_fraction == pytest.approx(0.005)
    assert result.fill_rate == pytest.approx(1.0)
