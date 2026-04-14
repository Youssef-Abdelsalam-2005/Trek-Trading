import type { AutoLoopStatus } from "../../types/autoloop";
import styles from "./AutoLoopControls.module.css";

interface Props {
  status: AutoLoopStatus;
  currentIteration: number;
  lastIterationAt: string | null;
  onStart: () => void;
  onPause: () => void;
  onStop: () => void;
  acting?: boolean;
}

export function AutoLoopControls({
  status,
  currentIteration,
  lastIterationAt,
  onStart,
  onPause,
  onStop,
  acting,
}: Props) {
  return (
    <div className={styles.controls} aria-label="Auto-loop controls">
      <div className={styles.statusRow}>
        <span className={`${styles.indicator} ${styles[status]}`} />
        <span className={styles.statusLabel}>
          {status === "idle" && "Idle"}
          {status === "running" && "Running"}
          {status === "paused" && "Paused"}
          {status === "stopped" && "Stopped"}
        </span>
        {currentIteration > 0 && (
          <span className={styles.iterationCount}>
            Iteration {currentIteration}
          </span>
        )}
      </div>

      {lastIterationAt && (
        <p className={styles.lastRun}>
          Last iteration:{" "}
          {new Date(lastIterationAt).toLocaleString()}
        </p>
      )}

      <div className={styles.buttons} role="group" aria-label="Loop actions">
        {(status === "idle" || status === "stopped") && (
          <button
            className={`${styles.btn} ${styles.startBtn}`}
            onClick={onStart}
            disabled={acting}
            aria-label="Start auto-loop"
          >
            {acting ? "Starting…" : "Start"}
          </button>
        )}

        {status === "paused" && (
          <button
            className={`${styles.btn} ${styles.startBtn}`}
            onClick={onStart}
            disabled={acting}
            aria-label="Resume auto-loop"
          >
            {acting ? "Resuming…" : "Resume"}
          </button>
        )}

        {status === "running" && (
          <button
            className={`${styles.btn} ${styles.pauseBtn}`}
            onClick={onPause}
            disabled={acting}
            aria-label="Pause auto-loop"
          >
            {acting ? "Pausing…" : "Pause"}
          </button>
        )}

        {(status === "running" || status === "paused") && (
          <button
            className={`${styles.btn} ${styles.stopBtn}`}
            onClick={onStop}
            disabled={acting}
            aria-label="Stop auto-loop"
          >
            {acting ? "Stopping…" : "Stop"}
          </button>
        )}
      </div>
    </div>
  );
}
