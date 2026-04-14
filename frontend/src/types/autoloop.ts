export type AutoLoopStatus = "idle" | "running" | "paused" | "stopped";

export interface AutoLoopConfig {
  variationsPerIteration: number;
  mutationsPerPassing: number;
  minSortino: number;
  maxDrawdown: number;
  iterationDelaySeconds: number;
  autoStart: boolean;
}

export interface AutoLoopState {
  status: AutoLoopStatus;
  currentIteration: number;
  totalVariationsGenerated: number;
  lastIterationAt: string | null;
}

export const DEFAULT_AUTOLOOP_CONFIG: AutoLoopConfig = {
  variationsPerIteration: 5,
  mutationsPerPassing: 3,
  minSortino: 1.0,
  maxDrawdown: 30,
  iterationDelaySeconds: 60,
  autoStart: false,
};
