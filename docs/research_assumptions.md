# Research assumptions

Every field below is a real modeling judgment call, not a safe
engineering default, and needs the researcher's explicit sign-off
before being relied on for any real analysis. Each lives in
`configs/default.yaml`, tagged `# RESEARCH ASSUMPTION` at the point of
definition, and in each module's own inline comments -- this document
consolidates both into one reference, matching the other six engines'
own convention.

## Simulation (`simulation:` in `configs/default.yaml`)

**`market_step_size: 0.1`**
The real sim-time interval between successive synthetic counterparty
market-flow steps (`market/venue.py`). Smaller values give the
synthetic market more, finer-grained chances to replenish liquidity
within a given horizon.

**`post_schedule_horizon: 20.0`**
The real sim-time the background counterparty flow keeps running
after the last real child order has been submitted, so resting limit
orders still get a real chance to fill rather than being judged the
instant the schedule ends.

**`staleness_threshold: 5.0`**
Beyond this many real sim-time units without a market-data update, a
venue is flagged stale (`Venue.is_stale`).

## Venue (`venue:`)

**`tick_size: 0.01`**, **`n_price_levels: 5`**,
**`level_spacing_in_ticks: 1`**, **`base_level_size: 500.0`**
The real synthetic book's seeded structure: how many price levels of
real liquidity exist on each side at simulation start, how far apart
they sit, and how much size rests at the best level (tapering toward
zero at the furthest seeded level).

**`counterparty_aggressive_fraction: 0.3`**
The real fraction of each synthetic counterparty arrival that is an
AGGRESSIVE market order (can trade through our own resting orders)
rather than a PASSIVE new resting limit order. Calibrated as a round,
moderate value -- a specific real market's own trade/quote ratio
should override this.

**`counterparty_order_size: 100.0`**
The real mean size (exponential distribution) of one synthetic
counterparty arrival.

## Latency (`latency:`)

**`ack_latency: 0.5`**, **`cancel_latency: 0.5`**
The real simulated delay between submitting an order/cancel and it
actually reaching the book -- a round, illustrative value, not derived
from any real exchange's own measured latency.

**`spike_probability: 0.0`**, **`spike_multiplier: 10.0`**
The real probability any one latency draw is a "spike" (the failure
scenario), and the real multiplier applied when it is. `0.0` by
default (no spikes) -- set explicitly to exercise the real latency-
spike failure scenario.

## Risk limits (`risk_limits:`)

**`max_position_per_security: 100000.0`**, **`max_gross_notional: 5000000.0`**,
**`max_order_notional: 1000000.0`**
Real, illustrative risk-gate thresholds -- calibrated to this engine's
own default demonstration scale, not any specific real mandate's
actual limits. A researcher applying this engine to a real portfolio
must resize these to that portfolio's own real scale (see
`docs/STATUS.md`'s own worked example, where the default limits
correctly rejected an oversized demo trade).

## Execution algorithms (`algos/execution_algos.py`, not config-driven)

These are not global config fields -- each real execution is given
its own real schedule parameters (`start_time`, `end_time`,
`n_slices`, `volume_profile`, `max_participation_rate`,
`expected_volume_per_step`) explicitly by the caller, since they are
properties of ONE specific real trade, not a standing engine-wide
assumption.

**A deliberate design choice, not a defect:**
`participation_constrained_algo` RAISES if the given
`expected_volume_per_step` forecast cannot absorb the full real order
at the configured `max_participation_rate`, rather than silently
truncating the schedule and trading less than intended. A researcher
who wants a smaller real trade should ask for one explicitly, not
discover it was truncated after the fact.

## Not a research assumption (real engineering defaults)

`run.output_dir`, `run.random_seed` are safe engineering defaults, not
modeling choices, and are not listed here.

## Reused real inputs, not re-estimated here

This engine makes no independent research assumptions about
price-time-priority matching mechanics (reused directly from
`orderbook-priority-sim`), latency-driven adverse-selection cost
(reused directly from `market-making-sim`), transaction-cost
estimation (reused directly from `transaction-cost-engine`), or
portfolio construction (reused directly from
`portfolio-construction-engine`) -- those real judgment calls live in
each of those repos' own `docs/research_assumptions.md` files and are
consumed here as given.
