import pytest

from execution_oms.market import Venue, VenueConfig


def test_venue_rejects_non_positive_reference_price():
    with pytest.raises(ValueError):
        Venue("A", 0.0, VenueConfig())


def test_venue_config_rejects_bad_aggressive_fraction():
    with pytest.raises(ValueError):
        VenueConfig(counterparty_aggressive_fraction=1.5)


def test_seeded_book_has_a_real_spread_around_the_reference_price():
    venue = Venue("A", 100.0, VenueConfig(tick_size=0.01, n_price_levels=3, base_level_size=100.0))
    assert venue.book.best_bid() < 100.0 < venue.book.best_ask()
    assert venue.book.spread() > 0


def test_same_seed_produces_identical_deterministic_step_sequences():
    cfg = VenueConfig(random_seed=42)
    venue_a = Venue("A", 100.0, cfg)
    venue_b = Venue("A", 100.0, cfg)
    fills_a = [venue_a.step(float(t)) for t in range(20)]
    fills_b = [venue_b.step(float(t)) for t in range(20)]
    assert fills_a == fills_b


def test_different_seeds_produce_different_step_sequences():
    venue_a = Venue("A", 100.0, VenueConfig(random_seed=1))
    venue_b = Venue("A", 100.0, VenueConfig(random_seed=2))
    fills_a = [venue_a.step(float(t)) for t in range(30)]
    fills_b = [venue_b.step(float(t)) for t in range(30)]
    assert fills_a != fills_b


def test_is_stale_reflects_real_elapsed_time_since_last_update():
    venue = Venue("A", 100.0, VenueConfig())
    venue.step(10.0)
    assert not venue.is_stale(12.0, staleness_threshold=5.0)
    assert venue.is_stale(20.0, staleness_threshold=5.0)
