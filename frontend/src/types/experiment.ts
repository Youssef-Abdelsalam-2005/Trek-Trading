export const StrategyStatus = {
  GENERATED: "generated",
  BACKTESTING: "backtesting",
  BACKTESTED: "backtested",
  SKEPTIC_PENDING: "skeptic_pending",
  SKEPTIC_PASSED: "skeptic_passed",
  SKEPTIC_FAILED: "skeptic_failed",
  PAPER_TRADING: "paper_trading",
  PAPER_PASSED: "paper_passed",
  PAPER_FAILED: "paper_failed",
  LIVE: "live",
  HALTED: "halted",
  KILLED: "killed",
  RETIRED: "retired",
} as const;

export type StrategyStatus =
  (typeof StrategyStatus)[keyof typeof StrategyStatus];

export interface StrategyVariationSummary {
  id: string;
  experiment_id: string;
  parent_id: string | null;
  name: string | null;
  status: StrategyStatus;
  generation: number;
  llm_cost_usd: number;
  cumulative_llm_cost_usd: number;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  created_at: string;
  updated_at: string;
}

export interface BacktestResult {
  id: string;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  total_return_pct: number | null;
  win_rate: number | null;
  total_trades: number;
  created_at: string;
}

export interface SkepticAudit {
  id: string;
  passed: boolean;
  score: number | null;
  reasoning: string | null;
  created_at: string;
}

export interface PaperSessionSummary {
  id: string;
  status: string;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  total_return_pct: number | null;
  win_rate: number | null;
  total_trades: number;
  fill_failure_rate: number | null;
  created_at: string;
}

export interface VariationDetail {
  variation: StrategyVariationSummary;
  backtest_runs: BacktestResult[];
  skeptic_audits: SkepticAudit[];
  paper_sessions: PaperSessionSummary[];
}
