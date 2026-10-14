"""Stage 10 -- renders a real ``ExecutionSimulationResult`` into a
reproducible report: a JSON-serializable dict, and a professional
Markdown document. Both derived from the SAME object -- never
recomputed separately, so they can't silently disagree. Mirrors the
other six engines' own reporting convention.
"""

from __future__ import annotations

from ..pipeline import ExecutionSimulationResult


def report_to_dict(result: ExecutionSimulationResult) -> dict:
    securities = {}
    for security_id, sec in result.order_results.items():
        securities[security_id] = {
            "n_parent_orders": len(sec.parent_orders),
            "order_states": [o.state.value for o in sec.parent_orders],
            "n_fills": len(sec.fills),
            "expected_cost_fraction": sec.cost.expected_cost_fraction,
            "realized_cost_fraction": sec.cost.realized_cost_fraction,
            "fill_rate": sec.cost.fill_rate,
            "realized_avg_fill_price": sec.cost.realized_avg_fill_price,
            "analytics": [
                {
                    "order_id": a.order_id,
                    "fill_rate": a.fill_rate,
                    "implementation_shortfall": a.implementation_shortfall,
                    "maker_fill_quantity": a.maker_fill_quantity,
                    "taker_fill_quantity": a.taker_fill_quantity,
                    "maker_notional_fraction": a.maker_notional_fraction,
                    "realized_adverse_selection": a.realized_adverse_selection,
                    "theoretical_adverse_selection": a.theoretical_adverse_selection,
                }
                for a in sec.analytics
            ],
        }

    recon = result.reconciliation
    return {
        "securities": securities,
        "reconciliation": {
            "realized_cash": recon.realized_cash,
            "position_by_security": recon.position_by_security,
            "mark_to_market_value": recon.mark_to_market_value,
            "total_pnl": recon.total_pnl,
            "reconciles": recon.reconciles,
            "discrepancy_detail": list(recon.discrepancy_detail),
        },
        "risk_breaches": [{"rule_name": b.rule_name, "detail": b.detail, "severity": b.severity} for b in result.risk_breaches],
        "event_log_length": result.event_log_length,
    }


def render_markdown_report(result: ExecutionSimulationResult) -> str:
    payload = report_to_dict(result)
    lines: list[str] = []
    lines.append("# Execution & Order Management Simulation -- Research Report")
    lines.append("")
    lines.append("All data in this report is synthetic and non-proprietary.")
    lines.append("")

    lines.append("## Per-Security Execution")
    lines.append("| Security | Orders | Fills | Fill Rate | Expected Cost | Realized Cost |")
    lines.append("|---|---|---|---|---|---|")
    for security_id, sec in payload["securities"].items():
        lines.append(
            f"| {security_id} | {sec['n_parent_orders']} | {sec['n_fills']} | {sec['fill_rate']:.1%} | "
            f"{sec['expected_cost_fraction']:.4%} | {sec['realized_cost_fraction']:.4%} |"
        )
    lines.append("")

    lines.append("## Execution Analytics")
    for security_id, sec in payload["securities"].items():
        lines.append(f"### {security_id}")
        for a in sec["analytics"]:
            shortfall = f"{a['implementation_shortfall']:.4%}" if a["implementation_shortfall"] is not None else "n/a"
            lines.append(
                f"- `{a['order_id']}`: fill rate {a['fill_rate']:.1%}, implementation shortfall {shortfall}, "
                f"maker fraction {a['maker_notional_fraction']:.1%}"
            )
    lines.append("")

    recon = payload["reconciliation"]
    lines.append("## Reconciliation")
    lines.append(f"- Realized cash: {recon['realized_cash']:.2f}  Mark-to-market: {recon['mark_to_market_value']:.2f}  Total P&L: {recon['total_pnl']:.2f}")
    lines.append(f"- Reconciles: **{recon['reconciles']}**")
    if recon["discrepancy_detail"]:
        for d in recon["discrepancy_detail"]:
            lines.append(f"  - {d}")
    lines.append("")

    lines.append("## Risk Breaches")
    if payload["risk_breaches"]:
        for b in payload["risk_breaches"]:
            lines.append(f"- **[{b['severity'].upper()}]** {b['rule_name']}: {b['detail']}")
    else:
        lines.append("No real risk breaches.")
    lines.append("")

    lines.append(f"## Event Log\n- {payload['event_log_length']} real events processed, in deterministic order.")

    return "\n".join(lines)
