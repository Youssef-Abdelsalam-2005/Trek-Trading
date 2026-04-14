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
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useSSE, type SSEEvent } from "../hooks/useSSE";
import { BacktestPanel } from "../components/BacktestPanel";
import { type BacktestResult, transformApiResponse } from "../types/backtest";

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
  const [panelOpen, setPanelOpen] = useState(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

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

      if (event.type === "backtest_result" && typeof event.data === "object" && event.data !== null) {
        setBacktestResult(event.data as BacktestResult);
        setBacktestLoading(false);
        setBacktestError(null);
      }
    },
    [setNodes],
  );

  const { connected } = useSSE({
    url: "/api/events",
    onEvent: handleSSEEvent,
  });

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    if (selectedNodeId === node.id && panelOpen) {
      setPanelOpen(false);
      setSelectedNodeId(null);
      return;
    }

    setSelectedNodeId(node.id);
    setPanelOpen(true);
    setBacktestLoading(true);
    setBacktestError(null);
    setBacktestResult(null);

    fetch(`/api/backtests/${encodeURIComponent(node.id)}`)
      .then((res) => {
        if (!res.ok) {
          if (res.status === 404) throw new Error("No backtest results available for this node.");
          throw new Error(`Failed to fetch backtest results (${res.status})`);
        }
        return res.json();
      })
      .then((data) => {
        setBacktestResult(transformApiResponse(data));
        setBacktestLoading(false);
      })
      .catch((err) => {
        setBacktestLoading(false);
        setBacktestError(err instanceof Error ? err.message : "Unknown error");
      });
  }, [selectedNodeId, panelOpen]);

  const handleClosePanel = useCallback(() => {
    setPanelOpen(false);
    setSelectedNodeId(null);
  }, []);

  return (
    <main className="canvas-page">
      <header className="canvas-header">
        <h1>Experiment: {id}</h1>
        <span className={`sse-status ${connected ? "sse-status--connected" : "sse-status--disconnected"}`}>
          {connected ? "Live" : "Reconnecting..."}
        </span>
      </header>
      <div className="canvas-body">
        <div className={`canvas-container ${panelOpen ? "canvas-container--with-panel" : ""}`}>
          <ReactFlow
            nodes={nodes.map((n) => ({
              ...n,
              className: n.id === selectedNodeId ? "selected-node" : undefined,
            }))}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>
        {panelOpen && (
          <BacktestPanel
            result={backtestResult}
            loading={backtestLoading}
            error={backtestError}
            onClose={handleClosePanel}
          />
        )}
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
