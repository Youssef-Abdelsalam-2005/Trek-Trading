"""Sandbox script for backtesting strategy code with vectorbt.

Reads JSON from stdin with keys: strategy_code, ohlcv_data, fee_rate, slippage.
Writes JSON metrics to stdout. Non-zero exit on failure.

This script runs in a separate process to enforce process isolation (C4).
"""
from __future__ import annotations

import json
import sys
import traceback
from io import StringIO
from typing import Any

import numpy as np
import pandas as pd
import vectorbt as vbt


def _load_ohlcv(raw: str) -> pd.DataFrame:
    df = pd.read_json(StringIO(raw), orient="records")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").set_index("timestamp")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def _exec_strategy(code: str, df: pd.DataFrame) -> pd.Series:
    """Execute strategy code and call generate_signal(df)."""
    ns: dict[str, Any] = {}
    exec(code, ns)  # noqa: S102
    generate_signal = ns.get("generate_signal")
    if generate_signal is None:
        raise ValueError("Strategy code must define generate_signal(df)")
    signals = generate_signal(df)
    if not isinstance(signals, pd.Series):
        signals = pd.Series(signals, index=df.index)
    return signals


def _compute_metrics(
    df: pd.DataFrame,
    signals: pd.Series,
    fee_rate: float,
    slippage: float,
) -> dict[str, Any]:
    entries = signals == 1
    exits = signals == -1

    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        fees=fee_rate,
        slippage=slippage,
        init_cash=10_000.0,
        freq="1h",
    )

    stats = pf.stats()
    total_return = float(pf.total_return())
    trades = pf.trades.records_readable if hasattr(pf.trades, "records_readable") else None
    trade_count = int(pf.trades.count()) if hasattr(pf.trades, "count") else 0
    win_rate = float(pf.trades.win_rate()) if trade_count > 0 else 0.0

    returns = pf.returns()
    neg_returns = returns[returns < 0]
    downside_std = float(neg_returns.std()) if len(neg_returns) > 0 else 0.0
    mean_return = float(returns.mean())
    sortino = mean_return / downside_std if downside_std > 0 else 0.0

    sharpe = float(pf.sharpe_ratio()) if hasattr(pf, "sharpe_ratio") else 0.0
    max_dd = float(pf.max_drawdown())

    equity = pf.value()
    equity_curve = {
        "timestamps": [t.isoformat() for t in equity.index],
        "values": [float(v) for v in equity.values],
    }

    return {
        "sortino_ratio": _finite(sortino),
        "sharpe_ratio": _finite(sharpe),
        "max_drawdown": _finite(max_dd),
        "total_return": _finite(total_return),
        "win_rate": _finite(win_rate),
        "trade_count": trade_count,
        "equity_curve": equity_curve,
        "metrics": {
            "init_cash": 10_000.0,
            "final_value": _finite(float(equity.iloc[-1])) if len(equity) > 0 else 10_000.0,
            "total_trades": trade_count,
            "stats_summary": {k: _finite(float(v)) if isinstance(v, (int, float, np.floating)) else str(v) for k, v in stats.items()},
        },
    }


def _finite(v: float) -> float:
    if np.isnan(v) or np.isinf(v):
        return 0.0
    return v


def main() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw)

    strategy_code = payload["strategy_code"]
    ohlcv_data = payload["ohlcv_data"]
    fee_rate = payload.get("fee_rate", 0.001)
    slippage = payload.get("slippage", 0.0005)

    df = _load_ohlcv(ohlcv_data)
    signals = _exec_strategy(strategy_code, df)
    result = _compute_metrics(df, signals, fee_rate, slippage)

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
