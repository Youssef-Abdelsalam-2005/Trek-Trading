export type BacktestMetrics = {
  totalReturn: number | null;
  sharpeRatio: number | null;
  sortinoRatio: number | null;
  maxDrawdown: number | null;
  winRate: number | null;
  tradeCount: number | null;
  annualizedReturn: number | null;
  calmarRatio: number | null;
};

export type EquityPoint = {
  time: string;
  value: number;
  drawdown: number;
};

export type Trade = {
  id: string;
  direction: "buy" | "sell";
  pair: string;
  price: number;
  quantity: number;
  valueUsd: number;
  feeUsd: number | null;
  slippageBps: number | null;
  executedAt: string;
};

export type BacktestResult = {
  id: string;
  variationId: string;
  startDate: string;
  endDate: string;
  hasError: boolean;
  errorMessage: string | null;
  durationSeconds: number | null;
  metrics: BacktestMetrics;
  equityCurve: EquityPoint[];
  trades: Trade[];
};

type ApiEquityPoint = { time: string; value: number };

type ApiTrade = {
  id: string;
  variation_id: string;
  source: string;
  direction: string;
  pair: string;
  price: number;
  quantity: number;
  value_usd: number;
  fee_usd: number | null;
  slippage_bps: number | null;
  tx_signature: string | null;
  executed_at: string;
};

type ApiBacktestResponse = {
  id: string;
  variation_id: string;
  start_date: string;
  end_date: string;
  sortino_ratio: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  total_return: number | null;
  win_rate: number | null;
  trade_count: number | null;
  has_error: boolean;
  error_message: string | null;
  duration_seconds: number | null;
  metrics: Record<string, unknown> | null;
  equity_curve: ApiEquityPoint[] | null;
  trades: ApiTrade[];
};

function computeDrawdown(curve: ApiEquityPoint[]): EquityPoint[] {
  let peak = -Infinity;
  return curve.map((p) => {
    if (p.value > peak) peak = p.value;
    const drawdown = peak > 0 ? (p.value - peak) / peak : 0;
    return { time: p.time, value: p.value, drawdown };
  });
}

export function transformApiResponse(data: ApiBacktestResponse): BacktestResult {
  const extra = data.metrics ?? {};
  return {
    id: data.id,
    variationId: data.variation_id,
    startDate: data.start_date,
    endDate: data.end_date,
    hasError: data.has_error,
    errorMessage: data.error_message,
    durationSeconds: data.duration_seconds,
    metrics: {
      totalReturn: data.total_return,
      sharpeRatio: data.sharpe_ratio,
      sortinoRatio: data.sortino_ratio,
      maxDrawdown: data.max_drawdown,
      winRate: data.win_rate,
      tradeCount: data.trade_count,
      annualizedReturn: (extra.annualized_return as number) ?? null,
      calmarRatio: (extra.calmar_ratio as number) ?? null,
    },
    equityCurve: computeDrawdown(data.equity_curve ?? []),
    trades: data.trades.map((t) => ({
      id: t.id,
      direction: t.direction as "buy" | "sell",
      pair: t.pair,
      price: t.price,
      quantity: t.quantity,
      valueUsd: t.value_usd,
      feeUsd: t.fee_usd,
      slippageBps: t.slippage_bps,
      executedAt: t.executed_at,
    })),
  };
}
