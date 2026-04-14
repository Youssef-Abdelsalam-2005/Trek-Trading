export type PaperSessionStatus = "paper_trading" | "paper_passed" | "paper_failed";

export type PaperTrade = {
  id: string;
  timestamp: string;
  direction: "buy" | "sell";
  inputMint: string;
  outputMint: string;
  inAmount: number;
  quotedOutAmount: number;
  filled: boolean;
  priceImpactPct: number;
};

export type PaperSession = {
  id: string;
  variationId: string;
  status: PaperSessionStatus;
  startTime: string;
  endTime: string | null;
  durationDays: number;
  initialCapital: number;
  currentCapital: number;
  currentStep: number;
  totalSteps: number;
  sortinoThreshold: number;
  maxDrawdownThreshold: number;
  sortinoResult: number | null;
  maxDrawdownResult: number | null;
  equityCurve: number[];
  trades: PaperTrade[];
};

type ApiPaperTrade = {
  id: string;
  session_id: string;
  timestamp: string;
  direction: string;
  input_mint: string;
  output_mint: string;
  in_amount: number;
  quoted_out_amount: number;
  filled: boolean;
  price_impact_pct: number;
};

type ApiPaperSession = {
  id: string;
  variation_id: string;
  status: string;
  start_time: string;
  end_time: string | null;
  duration_days: number;
  initial_capital: number;
  current_capital: number;
  current_step: number;
  total_steps: number;
  sortino_threshold: number;
  max_drawdown_threshold: number;
  sortino_result: number | null;
  max_drawdown_result: number | null;
  equity_curve: number[];
  trades: ApiPaperTrade[];
};

export function transformPaperSession(data: ApiPaperSession): PaperSession {
  return {
    id: data.id,
    variationId: data.variation_id,
    status: data.status as PaperSessionStatus,
    startTime: data.start_time,
    endTime: data.end_time,
    durationDays: data.duration_days,
    initialCapital: data.initial_capital,
    currentCapital: data.current_capital,
    currentStep: data.current_step,
    totalSteps: data.total_steps,
    sortinoThreshold: data.sortino_threshold,
    maxDrawdownThreshold: data.max_drawdown_threshold,
    sortinoResult: data.sortino_result,
    maxDrawdownResult: data.max_drawdown_result,
    equityCurve: data.equity_curve,
    trades: data.trades.map((t) => ({
      id: t.id,
      timestamp: t.timestamp,
      direction: t.direction as "buy" | "sell",
      inputMint: t.input_mint,
      outputMint: t.output_mint,
      inAmount: t.in_amount,
      quotedOutAmount: t.quoted_out_amount,
      filled: t.filled,
      priceImpactPct: t.price_impact_pct,
    })),
  };
}
