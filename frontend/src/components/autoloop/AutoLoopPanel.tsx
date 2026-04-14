import { useCallback, useEffect, useReducer } from "react";
import type { AutoLoopConfig, AutoLoopState } from "../../types/autoloop";
import { DEFAULT_AUTOLOOP_CONFIG } from "../../types/autoloop";
import * as api from "../../api/autoloop";
import { AutoLoopConfigForm } from "./AutoLoopConfigForm";
import { AutoLoopControls } from "./AutoLoopControls";
import styles from "./AutoLoopPanel.module.css";

type Phase = "loading" | "error" | "ready";

interface State {
  phase: Phase;
  config: AutoLoopConfig;
  loopState: AutoLoopState;
  error: string | null;
  acting: boolean;
}

type Action =
  | { type: "loaded"; config: AutoLoopConfig; loopState: AutoLoopState }
  | { type: "error"; message: string }
  | { type: "acting" }
  | { type: "stateUpdated"; loopState: AutoLoopState }
  | { type: "configSaved"; config: AutoLoopConfig }
  | { type: "actError"; message: string };

const INITIAL_LOOP_STATE: AutoLoopState = {
  status: "idle",
  currentIteration: 0,
  totalVariationsGenerated: 0,
  lastIterationAt: null,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loaded":
      return {
        ...state,
        phase: "ready",
        config: action.config,
        loopState: action.loopState,
        error: null,
      };
    case "error":
      return { ...state, phase: "error", error: action.message, acting: false };
    case "acting":
      return { ...state, acting: true };
    case "stateUpdated":
      return { ...state, loopState: action.loopState, acting: false };
    case "configSaved":
      return { ...state, config: action.config };
    case "actError":
      return { ...state, acting: false, error: action.message };
  }
}

interface Props {
  experimentId: string;
}

export function AutoLoopPanel({ experimentId }: Props) {
  const [state, dispatch] = useReducer(reducer, {
    phase: "loading",
    config: DEFAULT_AUTOLOOP_CONFIG,
    loopState: INITIAL_LOOP_STATE,
    error: null,
    acting: false,
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [config, loopState] = await Promise.all([
          api.getAutoLoopConfig(experimentId),
          api.getAutoLoopState(experimentId),
        ]);
        if (!cancelled) dispatch({ type: "loaded", config, loopState });
      } catch (err) {
        if (!cancelled)
          dispatch({
            type: "error",
            message:
              err instanceof Error ? err.message : "Failed to load config",
          });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  const handleSave = useCallback(
    async (config: AutoLoopConfig) => {
      const saved = await api.updateAutoLoopConfig(experimentId, config);
      dispatch({ type: "configSaved", config: saved });
    },
    [experimentId]
  );

  const handleAction = useCallback(
    async (action: () => Promise<AutoLoopState>) => {
      dispatch({ type: "acting" });
      try {
        const loopState = await action();
        dispatch({ type: "stateUpdated", loopState });
      } catch (err) {
        dispatch({
          type: "actError",
          message: err instanceof Error ? err.message : "Action failed",
        });
      }
    },
    []
  );

  if (state.phase === "loading") {
    return (
      <div className={styles.panel} aria-busy="true">
        <p className={styles.loading}>Loading auto-loop configuration…</p>
      </div>
    );
  }

  if (state.phase === "error" && !state.config) {
    return (
      <div className={styles.panel}>
        <div role="alert" className={styles.errorBanner}>
          {state.error}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      {state.error && (
        <div role="alert" className={styles.errorBanner}>
          {state.error}
        </div>
      )}

      <AutoLoopControls
        status={state.loopState.status}
        currentIteration={state.loopState.currentIteration}
        lastIterationAt={state.loopState.lastIterationAt}
        onStart={() => handleAction(() => api.startAutoLoop(experimentId))}
        onPause={() => handleAction(() => api.pauseAutoLoop(experimentId))}
        onStop={() => handleAction(() => api.stopAutoLoop(experimentId))}
        acting={state.acting}
      />

      <AutoLoopConfigForm
        initialConfig={state.config}
        onSave={handleSave}
        disabled={state.loopState.status === "running"}
      />
    </div>
  );
}
