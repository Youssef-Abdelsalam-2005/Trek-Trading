export type BacktestMetrics = {
  totalReturn: number;
  sharpeRatio: number;
  sortinoRatio: number;
  maxDrawdown: number;
  winRate: number;
  tradeCount: number;
  annualizedReturn: number;
  calmarRatio: number;
};

export type EquityPoint = {
  timestamp: string;
  equity: number;
  drawdown: number;
};

export type Trade = {
  id: string;
  entryTime: string;
  exitTime: string;
  side: "long" | "short";
  entryPrice: number;
  exitPrice: number;
  pnl: number;
  pnlPercent: number;
  duration: string;
};

export type BacktestResult = {
  strategyId: string;
  strategyName: string;
  status: "running" | "completed" | "failed";
  startDate: string;
  endDate: string;
  metrics: BacktestMetrics;
  equityCurve: EquityPoint[];
  trades: Trade[];
};
