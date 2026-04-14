import { useCallback, useEffect, useMemo, useReducer } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { StrategyVariationSummary } from "../../types/experiment";
import { getExperimentVariations } from "../../api/experiments";
import { StrategyNode } from "./StrategyNode";
import { useLineageLayout } from "./useLineageLayout";
import { NodeDetailPanel } from "./NodeDetailPanel";
import { STATUS_COLORS } from "./statusColors";
import styles from "./ExperimentLineageCanvas.module.css";

const nodeTypes = { strategy: StrategyNode };

type Phase = "loading" | "error" | "ready" | "empty";

interface State {
  phase: Phase;
  variations: StrategyVariationSummary[];
  selectedNodeId: string | null;
  error: string | null;
}

type Action =
  | { type: "loaded"; variations: StrategyVariationSummary[] }
  | { type: "error"; message: string }
  | { type: "selectNode"; id: string | null };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loaded":
      return {
        ...state,
        phase: action.variations.length > 0 ? "ready" : "empty",
        variations: action.variations,
        error: null,
      };
    case "error":
      return { ...state, phase: "error", error: action.message };
    case "selectNode":
      return { ...state, selectedNodeId: action.id };
  }
}

interface Props {
  experimentId: string;
}

export function ExperimentLineageCanvas({ experimentId }: Props) {
  const [state, dispatch] = useReducer(reducer, {
    phase: "loading",
    variations: [],
    selectedNodeId: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    getExperimentVariations(experimentId)
      .then((variations) => {
        if (!cancelled) dispatch({ type: "loaded", variations });
      })
      .catch((err) => {
        if (!cancelled)
          dispatch({
            type: "error",
            message:
              err instanceof Error ? err.message : "Failed to load lineage",
          });
      });

    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  const { nodes: layoutNodes, edges: layoutEdges } = useLineageLayout(
    state.variations
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutEdges);

  useEffect(() => {
    setNodes(layoutNodes);
    setEdges(layoutEdges);
  }, [layoutNodes, layoutEdges, setNodes, setEdges]);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    dispatch({ type: "selectNode", id: node.id });
  }, []);

  const handleClosePanel = useCallback(() => {
    dispatch({ type: "selectNode", id: null });
  }, []);

  const minimapNodeColor = useMemo(() => {
    const colorMap = new Map<string, string>();
    for (const v of state.variations) {
      colorMap.set(v.id, STATUS_COLORS[v.status]);
    }
    return (node: { id: string }) => colorMap.get(node.id) ?? "#666";
  }, [state.variations]);

  if (state.phase === "loading") {
    return (
      <div className={styles.container} aria-busy="true">
        <p className={styles.loading}>Loading strategy lineage…</p>
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <div className={styles.container}>
        <div role="alert" className={styles.errorBanner}>
          {state.error}
        </div>
      </div>
    );
  }

  if (state.phase === "empty") {
    return (
      <div className={styles.container}>
        <p className={styles.empty}>
          No strategy variations yet. Run an experiment iteration to generate
          strategies.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#2a2a3e" gap={20} />
        <Controls className={styles.controls} />
        <MiniMap
          nodeColor={minimapNodeColor}
          maskColor="rgba(0, 0, 0, 0.6)"
          className={styles.minimap}
        />
      </ReactFlow>

      {state.selectedNodeId && (
        <NodeDetailPanel
          variationId={state.selectedNodeId}
          onClose={handleClosePanel}
        />
      )}
    </div>
  );
}
