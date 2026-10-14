"""Engine configuration: every ambiguous research decision lives here,
with a recommended default and reasoning in
``docs/research_assumptions.md`` -- never hardcoded in source. Same
plain-``@dataclass`` house style as the other six engines in this
build. Composes the real config dataclasses each module already
defines (``VenueConfig``, ``LatencyConfig``, ``RiskLimits``) rather
than redefining them here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .market.venue import VenueConfig
from .orders.order_manager import LatencyConfig
from .risk.gates import RiskLimits


@dataclass(frozen=True)
class RunConfig:
    output_dir: str = "outputs"
    random_seed: int = 1337


@dataclass(frozen=True)
class SimulationConfig:
    # RESEARCH ASSUMPTION -- real sim-time units between successive
    # synthetic counterparty market-flow steps
    market_step_size: float = 0.1
    # RESEARCH ASSUMPTION -- the real sim-time horizon the background
    # counterparty flow continues to run for after the last real child
    # order has been submitted, so resting limit orders still get a
    # real chance to fill
    post_schedule_horizon: float = 20.0
    # RESEARCH ASSUMPTION -- beyond this many real sim-time units
    # without a market-data update, a venue's data is flagged stale
    staleness_threshold: float = 5.0

    def __post_init__(self) -> None:
        if self.market_step_size <= 0:
            raise ValueError("market_step_size must be positive")
        if self.post_schedule_horizon < 0:
            raise ValueError("post_schedule_horizon cannot be negative")
        if self.staleness_threshold <= 0:
            raise ValueError("staleness_threshold must be positive")


@dataclass(frozen=True)
class EngineConfig:
    run: RunConfig = field(default_factory=RunConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    venue: VenueConfig = field(default_factory=VenueConfig)
    latency: LatencyConfig = field(default_factory=LatencyConfig)
    risk_limits: RiskLimits = field(default_factory=RiskLimits)


def load_config(path: str) -> EngineConfig:
    """Load a real YAML config file into a validated EngineConfig.
    Missing sections fall back to each dataclass's own documented
    default -- never a silent empty/zero value."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    return EngineConfig(
        run=RunConfig(**raw.get("run", {})),
        simulation=SimulationConfig(**raw.get("simulation", {})),
        venue=VenueConfig(**raw.get("venue", {})),
        latency=LatencyConfig(**raw.get("latency", {})),
        risk_limits=RiskLimits(**raw.get("risk_limits", {})),
    )
