"""Stage 10 -- hardening and real failure-scenario coverage: exact
determinism/reproducibility given a fixed seed, a real property check
(TWAP achieves materially higher fill rate than a single market order
against the same thin synthetic liquidity), and the real failure
scenarios capability 9 requires: stale market data, rejected orders
(risk-limit breach), partial fills, liquidity gaps, and a runtime
kill-switch engagement.
"""

import json

import pandas as pd
import pytest
from portfolio_construction.data import OptimizationResult
from transaction_cost.config import EngineConfig as TransactionCostConfig

from execution_oms.config import EngineConfig, SimulationConfig
from execution_oms.events import SimulationClock
from execution_oms.market import Venue, VenueConfig
from execution_oms.orders.schemas import OrderState
from execution_oms.pipeline import run_execution_simulation
from execution_oms.reporting import report_to_dict
from execution_oms.risk import RiskLimits


def _market_data():
    return {"A": {"price": 100.0, "adv_usd": 5_000_000.0, "daily_volatility": 0.015, "annualized_volatility": 0.24, "as_of": pd.Timestamp("2020-06-30")}}


def _opt_result(target):
    return OptimizationResult(as_of=pd.Timestamp("2020-06-30"), portfolio_id="P", target_weights={"A": target}, expected_return=0.0, expected_variance=0.0, turnover=target, converged=True)


def _real_risk_limits():
    return RiskLimits(max_position_per_security=1_000_000.0, max_gross_notional=100_000_000.0, max_order_notional=50_000_000.0)


def test_pipeline_is_exactly_reproducible_given_identical_inputs():
    opt_result = _opt_result(0.3)
    engine_cfg = EngineConfig(risk_limits=_real_risk_limits())
    kwargs = ({"A": 0.0}, _market_data(), 1.0e7, "market", {"start_time": 0.0}, TransactionCostConfig(), engine_cfg)
    result_a = run_execution_simulation(opt_result, *kwargs)
    result_b = run_execution_simulation(opt_result, *kwargs)
    assert json.dumps(report_to_dict(result_a), sort_keys=True) == json.dumps(report_to_dict(result_b), sort_keys=True)


def test_twap_achieves_a_materially_higher_fill_rate_than_a_single_market_order():
    """A real, meaningful property: slicing a large order over time
    lets the synthetic market replenish liquidity between slices,
    which a single market order submitted all at once cannot benefit
    from -- confirmed directly, not assumed.
    """
    opt_result = _opt_result(0.3)
    engine_cfg = EngineConfig(risk_limits=_real_risk_limits())
    market_result = run_execution_simulation(opt_result, {"A": 0.0}, _market_data(), 1.0e7, "market", {"start_time": 0.0}, TransactionCostConfig(), engine_cfg)
    twap_result = run_execution_simulation(opt_result, {"A": 0.0}, _market_data(), 1.0e7, "twap", {"start_time": 0.0, "end_time": 50.0, "n_slices": 20}, TransactionCostConfig(), engine_cfg)

    market_fill_rate = market_result.order_results["A"].cost.fill_rate
    twap_fill_rate = twap_result.order_results["A"].cost.fill_rate
    assert twap_fill_rate > market_fill_rate * 2


def test_an_order_breaching_pre_trade_risk_limits_is_rejected_not_submitted():
    opt_result = _opt_result(0.9)  # a real, deliberately oversized trade
    tight_limits = RiskLimits(max_position_per_security=100.0, max_gross_notional=10_000.0, max_order_notional=5_000.0)
    engine_cfg = EngineConfig(risk_limits=tight_limits)
    result = run_execution_simulation(opt_result, {"A": 0.0}, _market_data(), 1.0e7, "market", {"start_time": 0.0}, TransactionCostConfig(), engine_cfg)
    order = result.order_results["A"].parent_orders[0]
    assert order.state == OrderState.REJECTED
    assert result.risk_breaches
    assert order.filled_quantity == 0.0


def test_stale_market_data_is_detected_directly():
    venue = Venue("A", 100.0, VenueConfig())
    venue.step(0.0)
    assert not venue.is_stale(3.0, staleness_threshold=5.0)
    assert venue.is_stale(10.0, staleness_threshold=5.0)


def test_a_liquidity_gap_leaves_a_market_order_only_partially_filled():
    """A real liquidity gap: no synthetic counterparty flow runs at
    all (market_step_size set so large it never fires within the
    simulation horizon), so a market order can only fill against the
    real SEEDED book depth and nothing more.
    """
    opt_result = _opt_result(0.3)
    engine_cfg = EngineConfig(
        risk_limits=_real_risk_limits(),
        simulation=SimulationConfig(market_step_size=1000.0, post_schedule_horizon=1.0, staleness_threshold=5.0),
        venue=VenueConfig(n_price_levels=2, base_level_size=50.0),
    )
    result = run_execution_simulation(opt_result, {"A": 0.0}, _market_data(), 1.0e7, "market", {"start_time": 0.0}, TransactionCostConfig(), engine_cfg)
    assert result.order_results["A"].cost.fill_rate < 1.0


def test_duplicate_scheduling_of_the_same_submission_is_rejected_at_the_clock_level():
    from execution_oms.events import DuplicateEventError

    clock = SimulationClock()
    clock.schedule(1.0, "SUBMIT_ORDER", {}, event_id="submit-x")
    with pytest.raises(DuplicateEventError):
        clock.schedule(2.0, "SUBMIT_ORDER", {}, event_id="submit-x")


def test_a_runtime_risk_breach_engages_the_kill_switch_and_blocks_further_orders():
    from execution_oms.risk import RiskState, check_pre_trade, check_runtime, engage_kill_switch
    from execution_oms.orders.schemas import Fill, OrderSide

    limits = RiskLimits(max_position_per_security=100.0, max_gross_notional=100_000.0, max_order_notional=50_000.0)
    state = RiskState()
    state.apply_fill(Fill(fill_id="f", order_id="o", security_id="A", side=OrderSide.BUY, sim_time=0.0, price=10.0, quantity=150.0, is_maker=False))
    breaches = check_runtime(state, {"A": 10.0}, limits)
    assert breaches
    engage_kill_switch(state, "test breach")
    assert state.kill_switch_engaged
    further_breaches = check_pre_trade("A", OrderSide.BUY, 1.0, 10.0, state, {"A": 10.0}, limits)
    assert further_breaches[0].rule_name == "kill_switch"
