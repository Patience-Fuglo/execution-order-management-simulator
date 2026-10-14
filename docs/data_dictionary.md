# Data dictionary

Every schema field this engine actually defines, plus the real
formula each build stage computes -- matching the other six engines'
own `docs/data_dictionary.md` convention. Fields reused directly from
upstream engines/libraries (e.g. `orderbook_sim.Order`,
`OptimizationResult`, `TradeOrder`) are not re-documented here; see
their own dictionaries.

## `Event` / `SimulationClock` (`events/schemas.py`)

- `Event.sim_time`, `Event.seq` -- the real, total ordering key: a
  binary heap pops strictly in `(sim_time, seq)` order, so the same
  scheduled events always process in the same real order regardless
  of insertion order.
- `Event.event_id` -- the real idempotency key;
  `SimulationClock.is_duplicate`/`mark_processed` track which ids have
  already been acted on.
- `SimulationClock.event_log` -- the real, append-only, reproducible
  record of every event actually processed, in the order processed.

## `OrderState` / `Order` / `Fill` (`orders/schemas.py`)

- `OrderState` -- `NEW`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`,
  `CANCEL_PENDING`, `CANCELLED`, `REJECTED`. `VALID_TRANSITIONS` is the
  one real, explicit table every change is checked against.
- `Order.remaining_quantity` = `quantity - filled_quantity`;
  `Order.avg_fill_price` = `total_fill_notional / filled_quantity`
  (`None` if unfilled) -- both DERIVED, never independently stored, so
  they can never desync from the real fills actually applied.
- `Order.apply_fill(quantity, price, sim_time)` -- updates the real
  derived totals, then transitions to `FILLED` (if
  `remaining_quantity <= 0`) or `PARTIALLY_FILLED`.
- `Fill` -- one real, immutable fill: `security_id`, `side`,
  `sim_time`, `price`, `quantity`, `is_maker` (did we provide
  liquidity passively, or take it aggressively). `notional = price *
  quantity`.

## `VenueConfig` / `Venue` (`market/venue.py`)

See `docs/research_assumptions.md` for every field. `Venue.step(sim_time)`:
with probability `counterparty_aggressive_fraction`, a real aggressive
counterparty `market_order` call (may fill our own resting orders);
otherwise a real passive counterparty `add_limit_order` one tick
inside the current best quote. `Venue.is_stale(sim_time, threshold)` =
`(sim_time - last_update_sim_time) > threshold`.

## `LatencyConfig` / `OrderManager` (`orders/order_manager.py`)

`OrderManager.submit_order` schedules a real `ORDER_ACK` event at
`clock.now + ack_latency` (or `* spike_multiplier` with probability
`spike_probability`). `_route_to_book`:

```
MARKET order:  fills = venue.book.market_order(side, quantity)   # real, direct
LIMIT order:   marketable_qty = sum(opposing depth at prices crossing our limit)
               immediate_qty  = min(quantity, marketable_qty)
               fills = venue.book.market_order(side, immediate_qty)   # real crossing fix
               remainder rests via venue.book.add_limit_order(...)
```

`OrderManager.request_cancel` schedules a real `ORDER_CANCEL_ACK`
event at `clock.now + cancel_latency`; a cancel racing an
already-terminal order is a real, documented no-op.
`OrderManager.on_counterparty_fills` records any real fill against one
of OUR resting orders as a real MAKER fill.

## `RiskLimits` / `RiskState` / `RiskBreach` (`risk/gates.py`)

See `docs/research_assumptions.md` for threshold defaults.
`RiskState.apply_fill`: `position += sign(side) * quantity`;
`realized_cash -= sign(side) * notional`. `check_pre_trade` projects
this proposed order's effect onto the real CURRENT state before
allowing submission; `check_runtime` re-checks the real state after
every fill, catching a combined breach pre-trade checks alone cannot.
`engage_kill_switch` sets `RiskState.kill_switch_engaged = True`,
after which every future `check_pre_trade` call returns a `kill_switch`
breach regardless of order size.

## `ChildOrderSpec` (`algos/execution_algos.py`)

`sim_time`, `quantity`, `order_type`, `limit_price`, `time_in_force`
-- one real child order's full real specification, produced by one of
the five real scheduling functions (see `docs/STATUS.md` for each
formula).

## `ExpectedVsRealizedCost` (`costs/expected_vs_realized.py`)

- `expected_cost_fraction` -- real, from
  `transaction_cost.execution.total_cost.compute_total_execution_cost`,
  computed ONCE at decision time from reference price/ADV/volatility.
- `realized_cost_fraction` -- real, `sign(side) * (avg_fill_price -
  decision_price) / decision_price`, measured purely from actual
  simulated fills. Kept as a SEPARATE field from the expected figure
  -- never summed, never double-counted.
- `fill_rate` -- `total_filled_quantity / ordered_quantity`.

## `ExecutionAnalyticsResult` / `ReconciliationResult` (`analytics/execution_analytics.py`)

- `implementation_shortfall` -- real, `sign(side) * (avg_fill_price -
  decision_price) / decision_price` (the same real formula as
  `realized_cost_fraction` above, computed per-ORDER here rather than
  per-security).
- `maker_fill_quantity`/`taker_fill_quantity`/`maker_notional_fraction`
  -- real split by `Fill.is_maker`.
- `realized_adverse_selection` -- real, `sign(side) * (post_fill_price
  - avg_fill_price) / avg_fill_price`: did the real price keep moving
  against us after we filled.
- `theoretical_adverse_selection` -- `market_making_sim.
  expected_adverse_move(annualized_volatility, latency_seconds)`,
  reused directly, as the real comparator for the realized figure
  above.
- `ReconciliationResult.reconciles` -- `True` only when an
  INDEPENDENT recomputation of cash/position from the raw real fill
  log matches the incrementally-maintained `RiskState` exactly (within
  `1e-6`) -- a real check that can and does fail on a deliberately
  desynced ledger (see its own unit test), never a tautology.

## Stage 9 -- pipeline (`pipeline/pipeline.py`)

`build_desired_trades(optimization_result, current_weights,
market_data, portfolio_value)`:

```
trade_weight = target_weights[sid] - current_weights[sid]
quantity     = |trade_weight| * portfolio_value / price
side         = BUY if trade_weight > 0 else SELL
```

`run_execution_simulation(...)` builds one real `Venue` per security,
schedules each real child order's `SUBMIT_ORDER` event (after a real
pre-trade risk check -- a breach REJECTS the order and never schedules
it), schedules each venue's own recurring `MARKET_STEP` events, then
drains the real event queue in strict `(sim_time, seq)` order until
`simulation_end`. Every real fill updates `RiskState` immediately and
triggers a real runtime risk check.

## Stage 10 -- reporting (`reporting/report.py`)

`report_to_dict(result)` / `render_markdown_report(result)` both
derive from the same real `ExecutionSimulationResult` -- never
recomputed separately, so they cannot silently disagree.
