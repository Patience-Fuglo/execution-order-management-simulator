import pytest

from execution_oms.orders.schemas import Fill, OrderSide
from execution_oms.risk.gates import RiskLimits, RiskState, check_pre_trade, check_runtime, engage_kill_switch

LIMITS = RiskLimits(max_position_per_security=1000.0, max_gross_notional=100_000.0, max_order_notional=20_000.0)


def _fill(security_id="A", side=OrderSide.BUY, quantity=100.0, price=10.0):
    return Fill(fill_id="f", order_id="o", security_id=security_id, side=side, sim_time=0.0, price=price, quantity=quantity, is_maker=False)


def test_risk_limits_reject_non_positive_values():
    with pytest.raises(ValueError):
        RiskLimits(max_position_per_security=0.0)


def test_pre_trade_allows_a_compliant_order():
    state = RiskState()
    breaches = check_pre_trade("A", OrderSide.BUY, 100.0, 1000.0, state, {"A": 10.0}, LIMITS)
    assert breaches == []


def test_pre_trade_rejects_an_order_exceeding_order_notional():
    state = RiskState()
    breaches = check_pre_trade("A", OrderSide.BUY, 5000.0, 25_000.0, state, {"A": 5.0}, LIMITS)
    assert any(b.rule_name == "max_order_notional" for b in breaches)


def test_pre_trade_rejects_an_order_exceeding_position_limit():
    state = RiskState()
    breaches = check_pre_trade("A", OrderSide.BUY, 1500.0, 1000.0, state, {"A": 1.0}, LIMITS)
    assert any(b.rule_name == "max_position_per_security" for b in breaches)


def test_pre_trade_accounts_for_the_real_existing_position_not_just_the_new_order():
    state = RiskState()
    state.apply_fill(_fill(quantity=900.0))
    breaches = check_pre_trade("A", OrderSide.BUY, 200.0, 2000.0, state, {"A": 10.0}, LIMITS)
    assert any(b.rule_name == "max_position_per_security" for b in breaches)


def test_kill_switch_blocks_every_new_order_regardless_of_size():
    state = RiskState()
    engage_kill_switch(state, "test")
    breaches = check_pre_trade("A", OrderSide.BUY, 1.0, 10.0, state, {"A": 10.0}, LIMITS)
    assert breaches[0].rule_name == "kill_switch"


def test_runtime_check_catches_a_combined_breach_from_multiple_fills():
    state = RiskState()
    state.apply_fill(_fill(quantity=600.0))
    state.apply_fill(_fill(quantity=600.0))  # each individually compliant, combined breaches max_position_per_security
    breaches = check_runtime(state, {"A": 10.0}, LIMITS)
    assert any(b.rule_name == "max_position_per_security_runtime" for b in breaches)


def test_sell_fills_reduce_cash_correctly_signed():
    state = RiskState()
    state.apply_fill(_fill(side=OrderSide.SELL, quantity=100.0, price=10.0))
    assert state.position_by_security["A"] == -100.0
    assert state.realized_cash == pytest.approx(1000.0)


def test_buy_fills_spend_cash_correctly_signed():
    state = RiskState()
    state.apply_fill(_fill(side=OrderSide.BUY, quantity=100.0, price=10.0))
    assert state.position_by_security["A"] == 100.0
    assert state.realized_cash == pytest.approx(-1000.0)
