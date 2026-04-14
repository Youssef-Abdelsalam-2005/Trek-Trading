import type {
  StrategyVariationSummary,
  VariationDetail,
} from "../types/experiment";
import { StrategyStatus } from "../types/experiment";

const API_BASE = "/api";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }
  return response.json();
}

export async function getExperimentVariations(
  experimentId: string
): Promise<StrategyVariationSummary[]> {
  if (USE_MOCK) return generateMockVariations();

  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/variations`
  );
  return handleResponse<StrategyVariationSummary[]>(res);
}

export async function getVariationDetail(
  variationId: string
): Promise<VariationDetail> {
  if (USE_MOCK) return generateMockDetail(variationId);

  const res = await fetch(
    `${API_BASE}/variations/${encodeURIComponent(variationId)}/detail`
  );
  return handleResponse<VariationDetail>(res);
}

function generateMockVariations(): StrategyVariationSummary[] {
  const statuses = Object.values(StrategyStatus);
  const variations: StrategyVariationSummary[] = [];
  let idCounter = 0;

  function makeId() {
    idCounter++;
    return `mock-${idCounter.toString().padStart(3, "0")}`;
  }

  const root = makeId();
  variations.push({
    id: root,
    experiment_id: "exp-001",
    parent_id: null,
    name: "Root Strategy",
    status: StrategyStatus.LIVE,
    generation: 0,
    llm_cost_usd: 0.02,
    cumulative_llm_cost_usd: 0.02,
    sortino_ratio: 2.1,
    max_drawdown_pct: 12.3,
    created_at: "2026-04-10T10:00:00Z",
    updated_at: "2026-04-10T10:00:00Z",
  });

  function addChildren(parentId: string, gen: number, count: number) {
    if (gen > 4) return;
    for (let i = 0; i < count; i++) {
      const id = makeId();
      const status = statuses[Math.floor(Math.random() * statuses.length)];
      variations.push({
        id,
        experiment_id: "exp-001",
        parent_id: parentId,
        name: `G${gen}-V${i + 1}`,
        status,
        generation: gen,
        llm_cost_usd: +(Math.random() * 0.05).toFixed(4),
        cumulative_llm_cost_usd: +(Math.random() * 0.2 + gen * 0.02).toFixed(
          4
        ),
        sortino_ratio:
          status === StrategyStatus.GENERATED
            ? null
            : +(Math.random() * 3).toFixed(2),
        max_drawdown_pct:
          status === StrategyStatus.GENERATED
            ? null
            : +(Math.random() * 40).toFixed(1),
        created_at: "2026-04-10T10:00:00Z",
        updated_at: "2026-04-10T10:00:00Z",
      });
      const childCount =
        gen === 1 ? 2 + Math.floor(Math.random() * 2)
        : gen === 2 ? 1 + Math.floor(Math.random() * 2)
        : gen === 3 ? Math.floor(Math.random() * 2)
        : 0;
      addChildren(id, gen + 1, childCount);
    }
  }

  addChildren(root, 1, 5);
  return variations;
}

function generateMockDetail(variationId: string): VariationDetail {
  const statuses = Object.values(StrategyStatus);
  const status = statuses[Math.floor(Math.random() * statuses.length)];

  return {
    variation: {
      id: variationId,
      experiment_id: "exp-001",
      parent_id: null,
      name: `Strategy ${variationId.slice(-3)}`,
      status,
      generation: 1,
      llm_cost_usd: 0.03,
      cumulative_llm_cost_usd: 0.05,
      sortino_ratio: 1.8,
      max_drawdown_pct: 15.2,
      created_at: "2026-04-10T10:00:00Z",
      updated_at: "2026-04-10T10:00:00Z",
    },
    backtest_runs: [
      {
        id: "bt-001",
        sortino_ratio: 1.8,
        max_drawdown_pct: 15.2,
        total_return_pct: 34.5,
        win_rate: 0.62,
        total_trades: 142,
        created_at: "2026-04-10T12:00:00Z",
      },
    ],
    skeptic_audits: [
      {
        id: "sa-001",
        passed: true,
        score: 0.85,
        reasoning:
          "Strategy shows consistent returns with acceptable drawdown. No curve-fitting detected.",
        created_at: "2026-04-10T14:00:00Z",
      },
    ],
    paper_sessions: [
      {
        id: "ps-001",
        status: "passed",
        sortino_ratio: 1.6,
        max_drawdown_pct: 18.1,
        total_return_pct: 12.3,
        win_rate: 0.58,
        total_trades: 47,
        fill_failure_rate: 0.28,
        created_at: "2026-04-11T08:00:00Z",
      },
    ],
  };
}
