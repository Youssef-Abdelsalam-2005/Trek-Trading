import type { AutoLoopConfig, AutoLoopState } from "../types/autoloop";

const API_BASE = "/api";

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }
  return response.json();
}

export async function getAutoLoopConfig(
  experimentId: string
): Promise<AutoLoopConfig> {
  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/autoloop/config`
  );
  return handleResponse<AutoLoopConfig>(res);
}

export async function updateAutoLoopConfig(
  experimentId: string,
  config: AutoLoopConfig
): Promise<AutoLoopConfig> {
  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/autoloop/config`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }
  );
  return handleResponse<AutoLoopConfig>(res);
}

export async function getAutoLoopState(
  experimentId: string
): Promise<AutoLoopState> {
  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/autoloop/state`
  );
  return handleResponse<AutoLoopState>(res);
}

export async function startAutoLoop(
  experimentId: string
): Promise<AutoLoopState> {
  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/autoloop/start`,
    { method: "POST" }
  );
  return handleResponse<AutoLoopState>(res);
}

export async function pauseAutoLoop(
  experimentId: string
): Promise<AutoLoopState> {
  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/autoloop/pause`,
    { method: "POST" }
  );
  return handleResponse<AutoLoopState>(res);
}

export async function stopAutoLoop(
  experimentId: string
): Promise<AutoLoopState> {
  const res = await fetch(
    `${API_BASE}/experiments/${encodeURIComponent(experimentId)}/autoloop/stop`,
    { method: "POST" }
  );
  return handleResponse<AutoLoopState>(res);
}
