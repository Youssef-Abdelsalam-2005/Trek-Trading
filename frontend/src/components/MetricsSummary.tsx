import type { BacktestMetrics } from "../types/backtest";

type MetricsSummaryProps = {
  metrics: BacktestMetrics;
};

type MetricDef = {
  key: keyof BacktestMetrics;
  label: string;
  format: (v: number) => string;
  threshold?: { good: number; bad: number };
};

const METRIC_DEFS: MetricDef[] = [
  {
    key: "totalReturn",
    label: "Total Return",
    format: (v) => `${(v * 100).toFixed(2)}%`,
    threshold: { good: 0, bad: -0.1 },
  },
  {
    key: "annualizedReturn",
    label: "Annualized Return",
    format: (v) => `${(v * 100).toFixed(2)}%`,
    threshold: { good: 0, bad: -0.1 },
  },
  {
    key: "sharpeRatio",
    label: "Sharpe Ratio",
    format: (v) => v.toFixed(2),
    threshold: { good: 1, bad: 0 },
  },
  {
    key: "sortinoRatio",
    label: "Sortino Ratio",
    format: (v) => v.toFixed(2),
    threshold: { good: 1.5, bad: 0 },
  },
  {
    key: "maxDrawdown",
    label: "Max Drawdown",
    format: (v) => `${(v * 100).toFixed(2)}%`,
    threshold: { good: -0.1, bad: -0.3 },
  },
  {
    key: "calmarRatio",
    label: "Calmar Ratio",
    format: (v) => v.toFixed(2),
    threshold: { good: 1, bad: 0 },
  },
  {
    key: "winRate",
    label: "Win Rate",
    format: (v) => `${(v * 100).toFixed(1)}%`,
    threshold: { good: 0.5, bad: 0.3 },
  },
  {
    key: "tradeCount",
    label: "Trade Count",
    format: (v) => v.toLocaleString(),
  },
];

function colorClass(def: MetricDef, value: number): string {
  if (!def.threshold) return "";
  if (def.key === "maxDrawdown") {
    if (value >= def.threshold.good) return "metric--good";
    if (value <= def.threshold.bad) return "metric--bad";
    return "metric--neutral";
  }
  if (value >= def.threshold.good) return "metric--good";
  if (value <= def.threshold.bad) return "metric--bad";
  return "metric--neutral";
}

export function MetricsSummary({ metrics }: MetricsSummaryProps) {
  return (
    <div className="metrics-summary">
      <h3 className="metrics-summary__title">Performance Metrics</h3>
      <dl className="metrics-grid">
        {METRIC_DEFS.map((def) => {
          const value = metrics[def.key];
          return (
            <div key={def.key} className={`metric-card ${colorClass(def, value)}`}>
              <dt className="metric-card__label">{def.label}</dt>
              <dd className="metric-card__value">{def.format(value)}</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
