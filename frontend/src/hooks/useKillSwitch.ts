import { useCallback, useState } from "react";

interface KillSwitchResponse {
  id: string;
  strategies_affected: number;
  reason: string | null;
  triggered_by: string;
  details: { killed_ids: string[] } | null;
  created_at: string;
  updated_at: string;
}

type KillSwitchState =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "success"; data: KillSwitchResponse }
  | { status: "error"; message: string };

export function useKillSwitch() {
  const [state, setState] = useState<KillSwitchState>({ status: "idle" });

  const trigger = useCallback(async (reason?: string) => {
    setState({ status: "pending" });
    try {
      const res = await fetch("/api/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason || "Manual kill switch", triggered_by: "user" }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data: KillSwitchResponse = await res.json();
      setState({ status: "success", data });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "Unknown error" });
    }
  }, []);

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, trigger, reset };
}
