import { useState } from "react";
import type { BacktestResult } from "../types/backtest";
import { EquityCurveChart } from "./EquityCurveChart";
import { MetricsSummary } from "./MetricsSummary";
import { TradeList } from "./TradeList";

type Tab = "chart" | "metrics" | "trades";

type BacktestPanelProps = {
  result: BacktestResult | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

export function BacktestPanel({ result, loading, error, onClose }: BacktestPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>("chart");

  return (
    <aside className="backtest-panel" role="complementary" aria-label="Backtest results">
      <header className="backtest-panel__header">
        <h2>Backtest Results</h2>
        <button
          className="backtest-panel__close"
          onClick={onClose}
          aria-label="Close panel"
          type="button"
        >
          &times;
        </button>
      </header>

      {loading && (
        <div className="backtest-panel__loading" role="status">
          <div className="backtest-panel__spinner" />
          <span>Running backtest...</span>
        </div>
      )}

      {error && (
        <div className="backtest-panel__error" role="alert">
          <strong>Backtest failed</strong>
          <p>{error}</p>
        </div>
      )}

      {!loading && !error && !result && (
        <p className="backtest-panel__empty">Select a strategy node to view backtest results.</p>
      )}

      {!loading && !error && result && (
        <>
          <nav className="backtest-panel__tabs" aria-label="Results sections">
            {(["chart", "metrics", "trades"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                className={`backtest-panel__tab ${activeTab === tab ? "backtest-panel__tab--active" : ""}`}
                onClick={() => setActiveTab(tab)}
                aria-selected={activeTab === tab}
                role="tab"
              >
                {tab === "chart" ? "Equity Curve" : tab === "metrics" ? "Metrics" : "Trades"}
              </button>
            ))}
          </nav>

          <div className="backtest-panel__body" role="tabpanel">
            {activeTab === "chart" && <EquityCurveChart data={result.equityCurve} />}
            {activeTab === "metrics" && <MetricsSummary metrics={result.metrics} />}
            {activeTab === "trades" && <TradeList trades={result.trades} />}
          </div>

          <footer className="backtest-panel__footer">
            {new Date(result.startDate).toLocaleDateString()} &mdash; {new Date(result.endDate).toLocaleDateString()}
          </footer>
        </>
      )}
    </aside>
  );
}
