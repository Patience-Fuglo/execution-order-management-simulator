import pytest

from execution_oms.algos.execution_algos import (
    limit_algo,
    market_algo,
    participation_constrained_algo,
    twap_algo,
    vwap_algo,
)
from execution_oms.orders.schemas import OrderType, TimeInForce


def test_market_algo_is_a_single_immediate_order():
    schedule = market_algo(100.0, start_time=5.0)
    assert len(schedule) == 1
    assert schedule[0].sim_time == 5.0
    assert schedule[0].quantity == 100.0
    assert schedule[0].order_type == OrderType.MARKET


def test_limit_algo_carries_the_real_limit_price_and_default_tif():
    schedule = limit_algo(50.0, start_time=0.0, limit_price=9.99)
    assert schedule[0].limit_price == 9.99
    assert schedule[0].time_in_force == TimeInForce.GTC


def test_twap_slices_evenly_in_both_quantity_and_time():
    schedule = twap_algo(100.0, start_time=0.0, end_time=10.0, n_slices=5)
    assert len(schedule) == 5
    assert all(s.quantity == pytest.approx(20.0) for s in schedule)
    assert [s.sim_time for s in schedule] == [0.0, 2.5, 5.0, 7.5, 10.0]


def test_twap_total_quantity_is_conserved():
    schedule = twap_algo(137.0, start_time=0.0, end_time=10.0, n_slices=7)
    assert sum(s.quantity for s in schedule) == pytest.approx(137.0)


def test_twap_rejects_end_before_start():
    with pytest.raises(ValueError):
        twap_algo(10.0, start_time=5.0, end_time=1.0, n_slices=3)


def test_vwap_slices_proportional_to_real_volume_share():
    profile = [(0.0, 0.2), (1.0, 0.5), (2.0, 0.3)]
    schedule = vwap_algo(1000.0, volume_profile=profile)
    assert [s.quantity for s in schedule] == [200.0, 500.0, 300.0]


def test_vwap_rejects_shares_not_summing_to_one():
    with pytest.raises(ValueError):
        vwap_algo(1000.0, volume_profile=[(0.0, 0.5), (1.0, 0.3)])


def test_participation_constrained_respects_the_real_rate_each_step():
    schedule = participation_constrained_algo(
        total_quantity=150.0, start_time=0.0, step=1.0, max_participation_rate=0.1,
        expected_volume_per_step=[1000.0, 1000.0, 1000.0],
    )
    assert [s.quantity for s in schedule] == [100.0, 50.0]
    assert [s.sim_time for s in schedule] == [0.0, 1.0]


def test_participation_constrained_raises_when_volume_forecast_is_insufficient():
    with pytest.raises(ValueError):
        participation_constrained_algo(
            total_quantity=1000.0, start_time=0.0, step=1.0, max_participation_rate=0.1,
            expected_volume_per_step=[100.0, 100.0],
        )


def test_participation_constrained_rejects_bad_rate():
    with pytest.raises(ValueError):
        participation_constrained_algo(100.0, 0.0, 1.0, 1.5, [1000.0])
