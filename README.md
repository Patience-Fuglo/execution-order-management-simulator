# execution-order-management-simulator

Answers: "if this portfolio's desired trade were actually routed to a
market, what would really happen -- order by order, fill by fill --
and how much would it really cost after risk checks, latency, and
real execution quality are accounted for?" A deterministic, event-
driven order lifecycle simulator: a real state machine (NEW ->
ACKNOWLEDGED -> PARTIALLY_FILLED/FILLED, with CANCEL_PENDING/
CANCELLED/REJECTED), a real price-time-priority order book, pre-trade
and runtime risk gates that cannot be bypassed by a cancellation race
or a partial fill, five execution algorithms (market, limit, TWAP,
VWAP, participation-constrained), execution analytics
(implementation shortfall, fill rate, slippage, adverse selection,
maker/taker cost), and an exact cash/inventory P&L reconciliation.

This engine reuses `orderbook-priority-sim`'s own real
`OrderBook` (price-time priority FIFO matching, multi-level walking,
queue position) directly for every real matching mechanic, and
`market-making-sim`'s own real `expected_adverse_move` (square-root-
of-time latency cost) for the theoretical adverse-selection
comparator -- neither is reimplemented. It consumes
`portfolio-construction-engine`'s own real `OptimizationResult` for
desired trades and `transaction-cost-engine`'s own real cost model for
the ESTIMATED cost baseline, kept strictly separate from this engine's
own SIMULATED REALIZED cost (measured directly from actual fills) --
never blended, never double-counted.

A real gap in `orderbook-priority-sim` (it never checks whether a new
limit order actually crosses the book) is worked around here using
only that engine's own existing primitives -- see
[`docs/STATUS.md`](docs/STATUS.md) -- without modifying that repo.

**All 10 stages are complete.** A deterministic event clock with
reproducible event logs; the full order lifecycle state machine with
idempotent event handling; order-book simulation with deterministic
synthetic counterparty flow; order management with simulated
acknowledgment/cancellation latency and time-in-force; pre-trade and
runtime risk gates with kill-switch behavior; five execution
algorithms; expected-vs-realized cost analysis; execution analytics
and P&L reconciliation; and a comprehensive hardening pass covering
every required failure scenario. See [`docs/STATUS.md`](docs/STATUS.md)
for the full stage-by-stage build history, final architecture/formula
summary, test evidence, and an honest list of limitations.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
python -m pytest tests/ -v
python scripts/run_execution_simulation.py
```

## Repository layout

```
src/execution_oms/
  events/schemas.py                 # Event, SimulationClock -- deterministic heap-ordered processing
  orders/
    schemas.py                       # OrderState, Order (state machine), Fill
    order_manager.py                  # OrderManager -- submission, cancel, TIF, latency, idempotency
  market/venue.py                     # Venue -- wraps the real OrderBook + synthetic counterparty flow
  risk/gates.py                        # RiskLimits, RiskState, pre-trade/runtime checks, kill switch
  algos/execution_algos.py              # market/limit/TWAP/VWAP/participation-constrained scheduling
  costs/expected_vs_realized.py          # expected (transaction-cost-engine) vs. simulated realized cost
  analytics/execution_analytics.py        # implementation shortfall, maker/taker split, reconciliation
  pipeline/pipeline.py                     # run_execution_simulation() -- Stages 1-8, end to end
  reporting/report.py                       # report_to_dict()/render_markdown_report()

tests/
  unit/           # one file per module, including the marketable-limit-order crossing fix
  integration/     # full pipeline, reproducibility, TWAP-vs-market fill-rate property,
                    # every required failure scenario, real CLI subprocess test

scripts/
  run_execution_simulation.py   # end-to-end: OptimizationResult -> simulate -> execution report
```
