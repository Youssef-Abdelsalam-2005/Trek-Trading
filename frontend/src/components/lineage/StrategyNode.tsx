import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { StrategyVariationSummary } from "../../types/experiment";
import { STATUS_COLORS, STATUS_LABELS } from "./statusColors";
import styles from "./StrategyNode.module.css";

export type StrategyNodeData = {
  variation: StrategyVariationSummary;
};

function StrategyNodeInner({ data }: NodeProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const variation = (data as StrategyNodeData).variation;
  const color = STATUS_COLORS[variation.status];
  const label = STATUS_LABELS[variation.status];

  return (
    <div
      className={styles.node}
      style={{ borderColor: color }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <Handle type="target" position={Position.Top} className={styles.handle} />

      <div className={styles.statusBadge} style={{ background: color }}>
        {label}
      </div>

      <div className={styles.name}>
        {variation.name ?? `Variation ${variation.id.slice(-6)}`}
      </div>

      <div className={styles.meta}>
        <span>Gen {variation.generation}</span>
        <span>${variation.cumulative_llm_cost_usd.toFixed(3)}</span>
      </div>

      {showTooltip && (
        <div className={styles.tooltip} role="tooltip">
          <div className={styles.tooltipRow}>
            <span>Sortino</span>
            <span>
              {variation.sortino_ratio != null
                ? variation.sortino_ratio.toFixed(2)
                : "—"}
            </span>
          </div>
          <div className={styles.tooltipRow}>
            <span>Max Drawdown</span>
            <span>
              {variation.max_drawdown_pct != null
                ? `${variation.max_drawdown_pct.toFixed(1)}%`
                : "—"}
            </span>
          </div>
          <div className={styles.tooltipRow}>
            <span>LLM Cost</span>
            <span>${variation.cumulative_llm_cost_usd.toFixed(4)}</span>
          </div>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className={styles.handle}
      />
    </div>
  );
}

export const StrategyNode = memo(StrategyNodeInner);
