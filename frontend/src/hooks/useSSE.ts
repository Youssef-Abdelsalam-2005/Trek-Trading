import { useEffect, useRef, useCallback, useState } from "react";

export type SSEEvent = {
  type: string;
  data: unknown;
  timestamp: number;
};

type UseSSEOptions = {
  url: string;
  onEvent?: (event: SSEEvent) => void;
  reconnectMs?: number;
};

export function useSSE({ url, onEvent, reconnectMs = 3000 }: UseSSEOptions) {
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
    }

    const es = new EventSource(url);
    sourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
    };

    es.onmessage = (msg) => {
      try {
        const parsed: SSEEvent = JSON.parse(msg.data);
        console.log("[SSE]", parsed.type, parsed);
        onEventRef.current?.(parsed);
      } catch {
        console.log("[SSE] raw:", msg.data);
      }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      sourceRef.current = null;
      setTimeout(connect, reconnectMs);
    };
  }, [url, reconnectMs]);

  useEffect(() => {
    connect();
    return () => {
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [connect]);

  return { connected };
}
