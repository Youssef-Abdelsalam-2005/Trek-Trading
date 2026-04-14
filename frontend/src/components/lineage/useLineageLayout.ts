import { useMemo } from "react";
import dagre from "dagre";
import type { Node, Edge } from "@xyflow/react";
import type { StrategyVariationSummary } from "../../types/experiment";
import type { StrategyNodeData } from "./StrategyNode";

const NODE_WIDTH = 160;
const NODE_HEIGHT = 80;

export function useLineageLayout(variations: StrategyVariationSummary[]): {
  nodes: Node[];
  edges: Edge[];
} {
  return useMemo(() => {
    if (variations.length === 0) return { nodes: [], edges: [] };

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: "TB", ranksep: 80, nodesep: 40 });

    for (const v of variations) {
      g.setNode(v.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    }

    const edges: Edge[] = [];
    for (const v of variations) {
      if (v.parent_id) {
        const edgeId = `${v.parent_id}->${v.id}`;
        g.setEdge(v.parent_id, v.id);
        edges.push({
          id: edgeId,
          source: v.parent_id,
          target: v.id,
          style: { stroke: "#555", strokeWidth: 1.5 },
          animated: false,
        });
      }
    }

    dagre.layout(g);

    const nodes: Node[] = variations.map((v) => {
      const pos = g.node(v.id);
      return {
        id: v.id,
        type: "strategy",
        position: {
          x: pos.x - NODE_WIDTH / 2,
          y: pos.y - NODE_HEIGHT / 2,
        },
        data: { variation: v } satisfies StrategyNodeData,
      };
    });

    return { nodes, edges };
  }, [variations]);
}
