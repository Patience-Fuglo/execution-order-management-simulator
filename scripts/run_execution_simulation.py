#!/usr/bin/env python3
"""End-to-end CLI: builds a real desired trade from a real
``portfolio-construction-engine`` ``OptimizationResult``, runs it
through the complete deterministic order-management simulation (order
book, risk gates, latency, execution algorithm), and writes one
reproducible JSON + Markdown execution report.

Usage:
    python scripts/run_execution_simulation.py [--algo market|limit|twap|vwap] [--target-weight 0.1] [--output-dir outputs/reports]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from portfolio_construction.data import OptimizationResult
from transaction_cost.config import EngineConfig as TransactionCostConfig

from execution_oms.config import EngineConfig
from execution_oms.pipeline import run_execution_simulation
from execution_oms.reporting import render_markdown_report, report_to_dict
from execution_oms.risk import RiskLimits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algo", default="twap", choices=["market", "limit", "twap", "vwap", "participation"])
    parser.add_argument("--target-weight", type=float, default=0.1)
    parser.add_argument("--portfolio-value", type=float, default=1.0e7)
    parser.add_argument("--output-dir", default="outputs/reports")
    args = parser.parse_args()

    opt_result = OptimizationResult(
        as_of=pd.Timestamp("2020-06-30"), portfolio_id="demo_portfolio", target_weights={"A": args.target_weight},
        expected_return=0.0, expected_variance=0.0, turnover=args.target_weight, converged=True,
    )
    current_weights = {"A": 0.0}
    market_data = {
        "A": {"price": 100.0, "adv_usd": 5_000_000.0, "daily_volatility": 0.015, "annualized_volatility": 0.015 * 252 ** 0.5, "as_of": pd.Timestamp("2020-06-30")},
    }

    algo_kwargs_by_name = {
        "market": {"start_time": 0.0},
        "limit": {"start_time": 0.0, "limit_price": 100.5},
        "twap": {"start_time": 0.0, "end_time": 50.0, "n_slices": 20},
        "vwap": {"volume_profile": [(float(i), 1.0 / 10) for i in range(10)]},
        "participation": {"start_time": 0.0, "step": 1.0, "max_participation_rate": 0.1, "expected_volume_per_step": [50_000.0] * 30},
    }

    engine_cfg = EngineConfig(
        risk_limits=RiskLimits(max_position_per_security=1_000_000.0, max_gross_notional=100_000_000.0, max_order_notional=50_000_000.0)
    )
    result = run_execution_simulation(
        opt_result, current_weights, market_data, args.portfolio_value, args.algo, algo_kwargs_by_name[args.algo],
        TransactionCostConfig(), engine_cfg,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"execution_report_{args.algo}.json"
    md_path = out_dir / f"execution_report_{args.algo}.md"

    with open(json_path, "w") as f:
        json.dump(report_to_dict(result), f, indent=2, sort_keys=True)
        f.write("\n")
    with open(md_path, "w") as f:
        f.write(render_markdown_report(result))

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    for security_id, sec in result.order_results.items():
        print(f"{security_id}: fill rate {sec.cost.fill_rate:.1%}, realized cost {sec.cost.realized_cost_fraction:.4%}")
    print(f"reconciles: {result.reconciliation.reconciles}")
    print(f"{len(result.risk_breaches)} real risk breaches")


if __name__ == "__main__":
    main()
