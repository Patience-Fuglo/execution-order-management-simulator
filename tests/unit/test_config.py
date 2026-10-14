import pytest

from execution_oms.config import EngineConfig, SimulationConfig, load_config


def test_default_engine_config_constructs_cleanly():
    cfg = EngineConfig()
    assert cfg.simulation.market_step_size == 0.1


def test_simulation_config_rejects_non_positive_step():
    with pytest.raises(ValueError):
        SimulationConfig(market_step_size=0.0)


def test_load_config_from_the_real_default_yaml():
    cfg = load_config("configs/default.yaml")
    assert cfg.venue.n_price_levels == 5
    assert cfg.risk_limits.max_order_notional == 1_000_000.0
