import { useCallback, useState } from "react";
import { usePaperSession } from "../hooks/usePaperSession";
import type { PaperSession, PaperTrade } from "../types/paper";

type PaperResultsProps = {
  variationId: string | undefined;
};

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "paper_passed" ? "paper-status--passed" :
    status === "paper_failed" ? "paper-status--failed" :
    "paper-status--active";
  return <span className={`paper-status ${cls}`}>{status.replace(/_/g, " ")}</span>;
}

function ProgressBar({ session }: { session: PaperSession }) {
  const pct = session.totalSteps > 0 ? (session.currentStep / session.totalSteps) * 100 : 0;
  const daysElapsed = session.endTime
    ? Math.ceil((new Date(session.endTime).getTime() - new Date(session.startTime).getTime()) / 86400000)
    : Math.ceil((Date.now() - new Date(session.startTime).getTime()) / 86400000);
  const daysRemaining = Math.max(0, session.durationDays - daysElapsed);

  return (
    <div className="paper-progress">
      <div className="paper-progress__bar">
        <div className="paper-progress__fill" style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <div className="paper-progress__labels">
        <span>Step {session.currentStep} / {session.totalSteps}</span>
        <span>{daysRemaining > 0 ? `${daysRemaining} day${daysRemaining !== 1 ? "s" : ""} remaining` : "Complete"}</span>
      </div>
    </div>
  );
}

function MetricsPanel({ session }: { session: PaperSession }) {
  const pnl = session.currentCapital - session.initialCapital;
  const pnlPct = session.initialCapital > 0 ? (pnl / session.initialCapital) * 100 : 0;

  const metrics = [
    {
      label: "P&L",
      value: `$${pnl.toFixed(2)}`,
      sub: `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`,
      good: pnl >= 0,
    },
    {
      label: "Equity",
      value: `$${session.currentCapital.toFixed(2)}`,
      sub: `from $${session.initialCapital.toFixed(2)}`,
      good: session.currentCapital >= session.initialCapital,
    },
    {
      label: "Sortino",
      value: session.sortinoResult != null ? session.sortinoResult.toFixed(2) : "—",
      sub: `threshold: ${session.sortinoThreshold.toFixed(2)}`,
      good: session.sortinoResult != null ? session.sortinoResult >= session.sortinoThreshold : null,
    },
    {
      label: "Max Drawdown",
      value: session.maxDrawdownResult != null ? `${(session.maxDrawdownResult * 100).toFixed(2)}%` : "—",
      sub: `threshold: ${(session.maxDrawdownThreshold * 100).toFixed(1)}%`,
      good: session.maxDrawdownResult != null ? session.maxDrawdownResult <= session.maxDrawdownThreshold : null,
    },
    {
      label: "Win Rate",
      value: session.trades.length > 0
        ? `${((session.trades.filter((t) => t.filled).length / session.trades.length) * 100).toFixed(1)}%`
        : "—",
      sub: `${session.trades.length} trades`,
      good: null,
    },
  ];

  return (
    <div className="paper-metrics">
      {metrics.map((m) => (
        <div key={m.label} className={`paper-metric ${m.good === true ? "paper-metric--good" : m.good === false ? "paper-metric--bad" : ""}`}>
          <span className="paper-metric__label">{m.label}</span>
          <span className="paper-metric__value">{m.value}</span>
          <span className="paper-metric__sub">{m.sub}</span>
        </div>
      ))}
    </div>
  );
}

function EquityChart({ curve, initialCapital }: { curve: number[]; initialCapital: number }) {
  if (curve.length === 0) return <p className="paper-empty">No equity data yet.</p>;

  const max = Math.max(...curve, initialCapital);
  const min = Math.min(...curve, initialCapital);
  const range = max - min || 1;
  const h = 200;
  const w = 600;
  const points = curve.map((v, i) => {
    const x = (i / Math.max(1, curve.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");

  return (
    <div className="paper-chart">
      <h3 className="paper-chart__title">Equity Curve</h3>
      <svg viewBox={`0 0 ${w} ${h}`} className="paper-chart__svg" aria-label="Equity curve chart">
        <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="2" />
        <line
          x1="0" y1={h - ((initialCapital - min) / range) * h}
          x2={w.toString()} y2={h - ((initialCapital - min) / range) * h}
          stroke="var(--text)" strokeWidth="1" strokeDasharray="4 3" opacity="0.4"
        />
      </svg>
      <div className="paper-chart__legend">
        <span>Start: ${initialCapital.toFixed(0)}</span>
        <span>Current: ${curve[curve.length - 1]?.toFixed(2)}</span>
      </div>
    </div>
  );
}

function TradeLog({ trades }: { trades: PaperTrade[] }) {
  if (trades.length === 0) return <p className="paper-empty">No trades yet.</p>;

  return (
    <div className="paper-trades">
      <h3 className="paper-trades__title">Trade Log</h3>
      <div className="paper-trades__scroll">
        <table className="paper-trades__table" role="table">
          <thead>
            <tr>
              <th scope="col">Direction</th>
              <th scope="col">Time</th>
              <th scope="col" className="num">Amount In</th>
              <th scope="col" className="num">Quoted Out</th>
              <th scope="col">Filled</th>
              <th scope="col" className="num">Impact</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id}>
                <td>
                  <span className={`paper-dir paper-dir--${t.direction}`}>{t.direction}</span>
                </td>
                <td>{formatDateTime(t.timestamp)}</td>
                <td className="num">{t.inAmount.toFixed(4)}</td>
                <td className="num">{t.quotedOutAmount.toFixed(4)}</td>
                <td>{t.filled ? "Yes" : "No"}</td>
                <td className="num">{t.priceImpactPct.toFixed(2)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PromoteButton({ variationId, onPromoted }: { variationId: string; onPromoted: () => void }) {
  const [state, setState] = useState<"idle" | "pending" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const promote = useCallback(async () => {
    setState("pending");
    try {
      const res = await fetch(`/api/variations/${encodeURIComponent(variationId)}/promote`, {
        method: "POST",
      });
      if (res.status === 409) {
        setErrorMsg("Strategy is not in paper_passed state");
        setState("error");
        return;
      }
      if (!res.ok) throw new Error(`Promote failed (${res.status})`);
      onPromoted();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Unknown error");
      setState("error");
    }
  }, [variationId, onPromoted]);

  return (
    <div className="paper-promote">
      <button
        type="button"
        className="paper-promote__btn"
        onClick={promote}
        disabled={state === "pending"}
      >
        {state === "pending" ? "Promoting..." : "Promote to Live"}
      </button>
      {state === "error" && <p className="paper-promote__error" role="alert">{errorMsg}</p>}
    </div>
  );
}

export default function PaperResults({ variationId }: PaperResultsProps) {
  const { state, refetch } = usePaperSession(variationId);

  if (state.status === "loading") {
    return (
      <div className="paper-results paper-results--loading" role="status">
        <div className="paper-spinner" />
        <span>Loading paper trading session...</span>
      </div>
    );
  }

  if (state.status === "empty") {
    return (
      <div className="paper-results paper-results--empty">
        <p>No paper trading session found for this variation.</p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="paper-results paper-results--error" role="alert">
        <strong>Error loading session</strong>
        <p>{state.message}</p>
        <button type="button" onClick={refetch}>Retry</button>
      </div>
    );
  }

  const { session } = state;

  return (
    <div className="paper-results">
      <header className="paper-results__header">
        <h2>Paper Trading Results</h2>
        <StatusBadge status={session.status} />
      </header>

      <ProgressBar session={session} />
      <MetricsPanel session={session} />
      <EquityChart curve={session.equityCurve} initialCapital={session.initialCapital} />
      <TradeLog trades={session.trades} />

      {session.status === "paper_passed" && (
        <PromoteButton variationId={session.variationId} onPromoted={refetch} />
      )}
    </div>
  );
}
