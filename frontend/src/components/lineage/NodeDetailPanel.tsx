import { useCallback, useEffect, useReducer } from "react";
import type { VariationDetail } from "../../types/experiment";
import { getVariationDetail } from "../../api/experiments";
import { STATUS_COLORS, STATUS_LABELS } from "./statusColors";
import styles from "./NodeDetailPanel.module.css";

type Phase = "loading" | "error" | "ready";

interface State {
  phase: Phase;
  detail: VariationDetail | null;
  error: string | null;
}

type Action =
  | { type: "loading" }
  | { type: "loaded"; detail: VariationDetail }
  | { type: "error"; message: string };

function reducer(_state: State, action: Action): State {
  switch (action.type) {
    case "loading":
      return { phase: "loading", detail: null, error: null };
    case "loaded":
      return { phase: "ready", detail: action.detail, error: null };
    case "error":
      return { phase: "error", detail: null, error: action.message };
  }
}

interface Props {
  variationId: string;
  onClose: () => void;
}

export function NodeDetailPanel({ variationId, onClose }: Props) {
  const [state, dispatch] = useReducer(reducer, {
    phase: "loading",
    detail: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    dispatch({ type: "loading" });

    getVariationDetail(variationId)
      .then((detail) => {
        if (!cancelled) dispatch({ type: "loaded", detail });
      })
      .catch((err) => {
        if (!cancelled)
          dispatch({
            type: "error",
            message: err instanceof Error ? err.message : "Failed to load",
          });
      });

    return () => {
      cancelled = true;
    };
  }, [variationId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  return (
    <aside
      className={styles.panel}
      aria-label="Strategy variation detail"
      onKeyDown={handleKeyDown}
    >
      <div className={styles.header}>
        <h2 className={styles.title}>Strategy Detail</h2>
        <button
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Close detail panel"
        >
          &times;
        </button>
      </div>

      {state.phase === "loading" && (
        <p className={styles.loading} aria-busy="true">
          Loading details…
        </p>
      )}

      {state.phase === "error" && (
        <div role="alert" className={styles.errorBanner}>
          {state.error}
        </div>
      )}

      {state.phase === "ready" && state.detail && (
        <DetailContent detail={state.detail} />
      )}
    </aside>
  );
}

function DetailContent({ detail }: { detail: VariationDetail }) {
  const { variation, backtest_runs, skeptic_audits, paper_sessions } = detail;
  const color = STATUS_COLORS[variation.status];

  return (
    <div className={styles.content}>
      <section className={styles.section}>
        <div className={styles.variationHeader}>
          <span className={styles.name}>
            {variation.name ?? `Variation ${variation.id.slice(-6)}`}
          </span>
          <span className={styles.badge} style={{ background: color }}>
            {STATUS_LABELS[variation.status]}
          </span>
        </div>
        <dl className={styles.metaGrid}>
          <dt>Generation</dt>
          <dd>{variation.generation}</dd>
          <dt>Sortino</dt>
          <dd>
            {variation.sortino_ratio != null
              ? variation.sortino_ratio.toFixed(2)
              : "—"}
          </dd>
          <dt>Max Drawdown</dt>
          <dd>
            {variation.max_drawdown_pct != null
              ? `${variation.max_drawdown_pct.toFixed(1)}%`
              : "—"}
          </dd>
          <dt>LLM Cost</dt>
          <dd>${variation.cumulative_llm_cost_usd.toFixed(4)}</dd>
        </dl>
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Backtest Results</h3>
        {backtest_runs.length === 0 ? (
          <p className={styles.empty}>No backtest runs</p>
        ) : (
          backtest_runs.map((bt) => (
            <div key={bt.id} className={styles.card}>
              <dl className={styles.metaGrid}>
                <dt>Sortino</dt>
                <dd>{bt.sortino_ratio?.toFixed(2) ?? "—"}</dd>
                <dt>Max DD</dt>
                <dd>
                  {bt.max_drawdown_pct != null
                    ? `${bt.max_drawdown_pct.toFixed(1)}%`
                    : "—"}
                </dd>
                <dt>Return</dt>
                <dd>
                  {bt.total_return_pct != null
                    ? `${bt.total_return_pct.toFixed(1)}%`
                    : "—"}
                </dd>
                <dt>Win Rate</dt>
                <dd>
                  {bt.win_rate != null
                    ? `${(bt.win_rate * 100).toFixed(0)}%`
                    : "—"}
                </dd>
                <dt>Trades</dt>
                <dd>{bt.total_trades}</dd>
              </dl>
            </div>
          ))
        )}
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Skeptic Audits</h3>
        {skeptic_audits.length === 0 ? (
          <p className={styles.empty}>No audits</p>
        ) : (
          skeptic_audits.map((sa) => (
            <div key={sa.id} className={styles.card}>
              <div className={styles.auditHeader}>
                <span
                  className={sa.passed ? styles.auditPass : styles.auditFail}
                >
                  {sa.passed ? "Passed" : "Failed"}
                </span>
                {sa.score != null && (
                  <span className={styles.auditScore}>
                    Score: {sa.score.toFixed(2)}
                  </span>
                )}
              </div>
              {sa.reasoning && (
                <p className={styles.reasoning}>{sa.reasoning}</p>
              )}
            </div>
          ))
        )}
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Paper Sessions</h3>
        {paper_sessions.length === 0 ? (
          <p className={styles.empty}>No paper sessions</p>
        ) : (
          paper_sessions.map((ps) => (
            <div key={ps.id} className={styles.card}>
              <span
                className={styles.badge}
                style={{
                  background:
                    ps.status === "passed"
                      ? "#22c55e"
                      : ps.status === "failed"
                        ? "#ef4444"
                        : "#f59e0b",
                }}
              >
                {ps.status}
              </span>
              <dl className={styles.metaGrid}>
                <dt>Sortino</dt>
                <dd>{ps.sortino_ratio?.toFixed(2) ?? "—"}</dd>
                <dt>Max DD</dt>
                <dd>
                  {ps.max_drawdown_pct != null
                    ? `${ps.max_drawdown_pct.toFixed(1)}%`
                    : "—"}
                </dd>
                <dt>Return</dt>
                <dd>
                  {ps.total_return_pct != null
                    ? `${ps.total_return_pct.toFixed(1)}%`
                    : "—"}
                </dd>
                <dt>Win Rate</dt>
                <dd>
                  {ps.win_rate != null
                    ? `${(ps.win_rate * 100).toFixed(0)}%`
                    : "—"}
                </dd>
                <dt>Fill Failures</dt>
                <dd>
                  {ps.fill_failure_rate != null
                    ? `${(ps.fill_failure_rate * 100).toFixed(0)}%`
                    : "—"}
                </dd>
              </dl>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
