import { StrategyStatus } from "../../types/experiment";

export const STATUS_COLORS: Record<StrategyStatus, string> = {
  [StrategyStatus.GENERATED]: "#6b7280",
  [StrategyStatus.BACKTESTING]: "#3b82f6",
  [StrategyStatus.BACKTESTED]: "#60a5fa",
  [StrategyStatus.SKEPTIC_PENDING]: "#8b5cf6",
  [StrategyStatus.SKEPTIC_PASSED]: "#10b981",
  [StrategyStatus.SKEPTIC_FAILED]: "#ef4444",
  [StrategyStatus.PAPER_TRADING]: "#f59e0b",
  [StrategyStatus.PAPER_PASSED]: "#22c55e",
  [StrategyStatus.PAPER_FAILED]: "#f97316",
  [StrategyStatus.LIVE]: "#059669",
  [StrategyStatus.HALTED]: "#eab308",
  [StrategyStatus.KILLED]: "#dc2626",
  [StrategyStatus.RETIRED]: "#9ca3af",
};

export const STATUS_LABELS: Record<StrategyStatus, string> = {
  [StrategyStatus.GENERATED]: "Generated",
  [StrategyStatus.BACKTESTING]: "Backtesting",
  [StrategyStatus.BACKTESTED]: "Backtested",
  [StrategyStatus.SKEPTIC_PENDING]: "Skeptic Pending",
  [StrategyStatus.SKEPTIC_PASSED]: "Skeptic Passed",
  [StrategyStatus.SKEPTIC_FAILED]: "Skeptic Failed",
  [StrategyStatus.PAPER_TRADING]: "Paper Trading",
  [StrategyStatus.PAPER_PASSED]: "Paper Passed",
  [StrategyStatus.PAPER_FAILED]: "Paper Failed",
  [StrategyStatus.LIVE]: "Live",
  [StrategyStatus.HALTED]: "Halted",
  [StrategyStatus.KILLED]: "Killed",
  [StrategyStatus.RETIRED]: "Retired",
};
