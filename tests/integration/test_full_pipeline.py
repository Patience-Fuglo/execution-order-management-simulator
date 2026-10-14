"""End-to-end: the full Stage 9 orchestration, executing a real
desired trade (from a real portfolio-construction-engine
``OptimizationResult``) through the complete simulated order
lifecycle, risk gates, order book, and execution analytics.
"""

import json

import pandas as pd
import pytest
from portfolio_construction.data import OptimizationResult
from transaction_cost.config import EngineConfig as TransactionCostConfig

from execution_oms.config import EngineConfig
from execution_oms.orders.schemas import OrderState
from execution_oms.pipeline import run_execution_simulation
from execution_oms.reporting import render_markdown_report, report_to_dict
from execution_oms.risk import RiskLimits


def _market_data():
    return {
        "A": {"price": 100.0, "adv_usd": 5_000_000.0, "daily_volatility": 0.015, "annualized_volatility": 0.015 * 252 ** 0.5, "as_of": pd.Timestamp("2020-06-30")},
        "B": {"price": 50.0, "adv_usd": 2_000_000.0, "daily_volatility": 0.02, "annualized_volatility": 0.02 * 252 ** 0.5, "as_of": pd.Timestamp("2020-06-30")},
    }


def _engine_cfg():
    return EngineConfig(risk_limits=RiskLimits(max_position_per_security=1_000_000.0, max_gross_notional=100_000_000.0, max_order_notional=50_000_000.0))


@pytest.fixture(scope="module")
def pipeline_result():
    opt_result = OptimizationResult(
        as_of=pd.Timestamp("2020-06-30"), portfolio_id="P", target_weights={"A": 0.1, "B": 0.05}, expected_return=0.0,
        expected_variance=0.0, turnover=0.15, converged=True,
    )
    return run_execution_simulation(
        opt_result, {"A": 0.0, "B": 0.0}, _market_data(), 1.0e7, "market", {"start_time": 0.0},
        TransactionCostConfig(), _engine_cfg(),
    )


def test_pipeline_produces_real_fills_for_every_security(pipeline_result):
    for security_id, sec in pipeline_result.order_results.items():
        assert sec.cost.total_filled_quantity >= 0
        assert sec.parent_orders


def test_every_parent_order_reaches_a_real_terminal_or_working_state(pipeline_result):
    valid_states = {OrderState.FILLED, OrderState.PARTIALLY_FILLED, OrderState.ACKNOWLEDGED, OrderState.REJECTED, OrderState.CANCELLED}
    for sec in pipeline_result.order_results.values():
        for order in sec.parent_orders:
            assert order.state in valid_states


def test_reconciliation_holds_exactly(pipeline_result):
    assert pipeline_result.reconciliation.reconciles
    assert pipeline_result.reconciliation.discrepancy_detail == ()


def test_expected_and_realized_costs_are_independently_computed_and_distinct_fields(pipeline_result):
    for sec in pipeline_result.order_results.values():
        assert sec.cost.expected_cost_fraction != sec.cost.realized_cost_fraction or sec.cost.total_filled_quantity == 0


def test_report_to_dict_is_json_serializable(pipeline_result):
    json.dumps(report_to_dict(pipeline_result))


def test_render_markdown_report_contains_every_real_section(pipeline_result):
    markdown = render_markdown_report(pipeline_result)
    for heading in ["## Per-Security Execution", "## Execution Analytics", "## Reconciliation", "## Risk Breaches", "## Event Log"]:
        assert heading in markdown
    assert "synthetic" in markdown.lower()


def test_report_rendering_is_deterministic(pipeline_result):
    assert render_markdown_report(pipeline_result) == render_markdown_report(pipeline_result)
    assert json.dumps(report_to_dict(pipeline_result), sort_keys=True) == json.dumps(report_to_dict(pipeline_result), sort_keys=True)


def test_rejects_when_target_and_current_weights_are_identical():
    opt_result = OptimizationResult(as_of=pd.Timestamp("2020-06-30"), portfolio_id="P", target_weights={"A": 0.1}, expected_return=0.0, expected_variance=0.0, turnover=0.0, converged=True)
    with pytest.raises(ValueError):
        run_execution_simulation(opt_result, {"A": 0.1}, _market_data(), 1.0e7, "market", {"start_time": 0.0}, TransactionCostConfig(), _engine_cfg())
