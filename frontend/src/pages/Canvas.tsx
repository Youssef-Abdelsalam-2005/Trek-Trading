import { useParams } from "react-router-dom";
import { useCallback, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type OnConnect,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useSSE, type SSEEvent } from "../hooks/useSSE";

const INITIAL_NODES: Node[] = [
  {
    id: "data-source",
    type: "default",
    position: { x: 50, y: 200 },
    data: { label: "Data Source (SOL/USDC)" },
  },
  {
    id: "strategy-gen",
    type: "default",
    position: { x: 300, y: 100 },
    data: { label: "Strategy Generator (LLM)" },
  },
  {
    id: "backtest",
    type: "default",
    position: { x: 550, y: 100 },
    data: { label: "Backtester" },
  },
  {
    id: "skeptic",
    type: "default",
    position: { x: 550, y: 300 },
    data: { label: "Skeptic Auditor" },
  },
  {
    id: "paper-trade",
    type: "default",
    position: { x: 800, y: 200 },
    data: { label: "Paper Trading" },
  },
  {
    id: "live-trade",
    type: "default",
    position: { x: 1050, y: 200 },
    data: { label: "Live Execution" },
  },
];

const INITIAL_EDGES: Edge[] = [
  { id: "e-ds-sg", source: "data-source", target: "strategy-gen" },
  { id: "e-sg-bt", source: "strategy-gen", target: "backtest" },
  { id: "e-bt-sk", source: "backtest", target: "skeptic" },
  { id: "e-sk-pt", source: "skeptic", target: "paper-trade" },
  { id: "e-pt-lt", source: "paper-trade", target: "live-trade" },
];

export default function Canvas() {
  const { id } = useParams<{ id: string }>();
  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState(INITIAL_EDGES);
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);

  const onConnect: OnConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      setLastEvent(event);

      if (event.type === "node_update" && typeof event.data === "object" && event.data !== null) {
        const { nodeId, label } = event.data as { nodeId: string; label: string };
        if (nodeId && label) {
          setNodes((nds) =>
            nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, label } } : n)),
          );
        }
      }
    },
    [setNodes],
  );

  const { connected } = useSSE({
    url: "/api/events",
    onEvent: handleSSEEvent,
  });

  return (
    <main className="canvas-page">
      <header className="canvas-header">
        <h1>Experiment: {id}</h1>
        <span className={`sse-status ${connected ? "sse-status--connected" : "sse-status--disconnected"}`}>
          {connected ? "Live" : "Reconnecting..."}
        </span>
      </header>
      <div className="canvas-container">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      {lastEvent && (
        <footer className="canvas-footer">
          Last event: <code>{lastEvent.type}</code> at{" "}
          {new Date(lastEvent.timestamp).toLocaleTimeString()}
        </footer>
      )}
    </main>
  );
}
