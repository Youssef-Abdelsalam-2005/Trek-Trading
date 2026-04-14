import type { BacktestResult } from "../types/backtest";

function generateEquityCurve() {
  const points = [];
  let equity = 10000;
  let peak = equity;
  const start = new Date("2025-01-01");

  for (let i = 0; i < 180; i++) {
    const date = new Date(start);
    date.setDate(date.getDate() + i);
    const change = (Math.random() - 0.47) * 200;
    equity = Math.max(equity + change, 1000);
    peak = Math.max(peak, equity);
    const drawdown = (equity - peak) / peak;

    points.push({
      timestamp: date.toISOString(),
      equity: Math.round(equity),
      drawdown: Math.round(drawdown * 1000) / 1000,
    });
  }
  return points;
}

function generateTrades() {
  const trades = [];
  const start = new Date("2025-01-05");

  for (let i = 0; i < 42; i++) {
    const entryDate = new Date(start);
    entryDate.setDate(entryDate.getDate() + i * 4 + Math.floor(Math.random() * 3));
    const exitDate = new Date(entryDate);
    const hours = 1 + Math.floor(Math.random() * 72);
    exitDate.setHours(exitDate.getHours() + hours);

    const side: "long" | "short" = Math.random() > 0.5 ? "long" : "short";
    const entryPrice = 120 + Math.random() * 80;
    const movement = (Math.random() - 0.42) * 15;
    const exitPrice = side === "long" ? entryPrice + movement : entryPrice - movement;
    const pnl = side === "long" ? exitPrice - entryPrice : entryPrice - exitPrice;
    const pnlPercent = pnl / entryPrice;

    const durationMs = exitDate.getTime() - entryDate.getTime();
    const durationH = Math.floor(durationMs / 3600000);
    const duration = durationH >= 24 ? `${Math.floor(durationH / 24)}d ${durationH % 24}h` : `${durationH}h`;

    trades.push({
      id: `t-${i}`,
      entryTime: entryDate.toISOString(),
      exitTime: exitDate.toISOString(),
      side,
      entryPrice: Math.round(entryPrice * 100) / 100,
      exitPrice: Math.round(exitPrice * 100) / 100,
      pnl: Math.round(pnl * 100) / 100,
      pnlPercent: Math.round(pnlPercent * 10000) / 10000,
      duration,
    });
  }
  return trades;
}

export const MOCK_BACKTEST_RESULTS: Record<string, BacktestResult> = {
  backtest: {
    strategyId: "strat-1",
    strategyName: "SOL Mean Reversion v1",
    status: "completed",
    startDate: "2025-01-01",
    endDate: "2025-06-30",
    metrics: {
      totalReturn: 0.2847,
      sharpeRatio: 1.42,
      sortinoRatio: 2.01,
      maxDrawdown: -0.1523,
      winRate: 0.573,
      tradeCount: 42,
      annualizedReturn: 0.5694,
      calmarRatio: 3.74,
    },
    equityCurve: generateEquityCurve(),
    trades: generateTrades(),
  },
  "strategy-gen": {
    strategyId: "strat-gen-1",
    strategyName: "Momentum Breakout v2",
    status: "completed",
    startDate: "2025-02-01",
    endDate: "2025-06-30",
    metrics: {
      totalReturn: 0.1205,
      sharpeRatio: 0.89,
      sortinoRatio: 1.15,
      maxDrawdown: -0.2134,
      winRate: 0.481,
      tradeCount: 67,
      annualizedReturn: 0.2891,
      calmarRatio: 1.35,
    },
    equityCurve: generateEquityCurve(),
    trades: generateTrades(),
  },
};
