import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { EquityPoint } from "../types/backtest";

type EquityCurveChartProps = {
  data: EquityPoint[];
};

function formatDate(timestamp: string) {
  return new Date(timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatCurrency(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

export function EquityCurveChart({ data }: EquityCurveChartProps) {
  if (data.length === 0) {
    return <p className="backtest-panel__empty">No equity data available.</p>;
  }

  return (
    <div className="equity-chart">
      <h3 className="equity-chart__title">Portfolio Value</h3>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="time"
            tickFormatter={formatDate}
            tick={{ fontSize: 11, fill: "var(--text)" }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={formatCurrency}
            tick={{ fontSize: 11, fill: "var(--text)" }}
            axisLine={false}
            tickLine={false}
            width={72}
          />
          <Tooltip
            contentStyle={{
              background: "var(--bg-alt)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 13,
            }}
            labelFormatter={(label) => formatDate(String(label))}
            formatter={(value, name) => [
              name === "value" ? formatCurrency(Number(value)) : `${(Number(value) * 100).toFixed(1)}%`,
              name === "value" ? "Equity" : "Drawdown",
            ]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#equityGrad)"
          />
          <Line
            type="monotone"
            dataKey="drawdown"
            stroke="var(--danger)"
            strokeWidth={1}
            strokeDasharray="4 3"
            dot={false}
            yAxisId="dd"
          />
          <YAxis
            yAxisId="dd"
            orientation="right"
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fontSize: 11, fill: "var(--text)" }}
            axisLine={false}
            tickLine={false}
            width={48}
            domain={["dataMin", 0]}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
