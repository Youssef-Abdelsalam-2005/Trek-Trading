import { useCallback, useEffect, useRef, useState } from "react";
import { type PaperSession, transformPaperSession } from "../types/paper";

type PaperSessionState =
  | { status: "loading" }
  | { status: "empty" }
  | { status: "error"; message: string }
  | { status: "loaded"; session: PaperSession };

export function usePaperSession(variationId: string | undefined) {
  const [state, setState] = useState<PaperSessionState>({ status: "loading" });
  const eventSourceRef = useRef<EventSource | null>(null);

  const fetchSession = useCallback(async () => {
    if (!variationId) {
      setState({ status: "empty" });
      return;
    }
    setState({ status: "loading" });
    try {
      const res = await fetch(`/api/paper-sessions/${encodeURIComponent(variationId)}`);
      if (res.status === 404) {
        setState({ status: "empty" });
        return;
      }
      if (!res.ok) throw new Error(`Failed to fetch (${res.status})`);
      const data = await res.json();
      setState({ status: "loaded", session: transformPaperSession(data) });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "Unknown error" });
    }
  }, [variationId]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  useEffect(() => {
    if (!variationId) return;
    if (state.status !== "loaded" || state.session.status !== "paper_trading") return;

    const es = new EventSource(`/api/paper-sessions/${encodeURIComponent(variationId)}/stream`);
    eventSourceRef.current = es;

    es.addEventListener("session_update", (e) => {
      try {
        const data = JSON.parse(e.data);
        setState((prev) => {
          if (prev.status !== "loaded") return prev;
          return { status: "loaded", session: transformPaperSession(data) };
        });
      } catch { /* ignore malformed SSE */ }
    });

    es.addEventListener("trade", (e) => {
      try {
        const trade = JSON.parse(e.data);
        setState((prev) => {
          if (prev.status !== "loaded") return prev;
          return {
            status: "loaded",
            session: {
              ...prev.session,
              trades: [...prev.session.trades, {
                id: trade.id,
                timestamp: trade.timestamp,
                direction: trade.direction,
                inputMint: trade.input_mint,
                outputMint: trade.output_mint,
                inAmount: trade.in_amount,
                quotedOutAmount: trade.quoted_out_amount,
                filled: trade.filled,
                priceImpactPct: trade.price_impact_pct,
              }],
            },
          };
        });
      } catch { /* ignore malformed SSE */ }
    });

    es.addEventListener("session_complete", () => {
      fetchSession();
    });

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [variationId, state.status, state.status === "loaded" ? state.session.status : null, fetchSession]);

  return { state, refetch: fetchSession };
}
