from __future__ import annotations

import math


def sortino_ratio(returns: list[float], target_return: float = 0.0) -> float:
    if not returns:
        return 0.0

    mean_return = sum(returns) / len(returns)
    excess = mean_return - target_return

    downside_diffs = [(r - target_return) ** 2 for r in returns if r < target_return]
    if not downside_diffs:
        return float("inf") if excess > 0 else 0.0

    downside_deviation = math.sqrt(sum(downside_diffs) / len(returns))
    if downside_deviation == 0:
        return float("inf") if excess > 0 else 0.0

    return excess / downside_deviation


def max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    worst_drawdown = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > worst_drawdown:
            worst_drawdown = drawdown

    return worst_drawdown
