import { useState, useRef, useCallback } from "react";

export type Phase =
  | "idle"
  | "search"
  | "read"
  | "synthesize"
  | "draft"
  | "waiting_human"
  | "complete"
  | "failed";

export interface TraceEntry {
  id: string;
  phase: string;
  action: string;
  input: string;
  output: string;
  token_count: number;
  cost_usd: number;
  duration_ms: number;
  timestamp: number;
  error: string | null;
}

export interface Source {
  url: string;
  title: string;
  snippet: string;
}

export interface Checkpoint {
  name: string;
  message: string;
  sources?: Source[];
  summaries?: { url: string; title: string; summary: string }[];
}

export interface AgentState {
  run_id: string;
  phase: Phase;
  sources_found: number;
  sources_selected: number;
  summaries_done: number;
  has_draft: boolean;
  total_tokens: number;
  total_cost_usd: number;
  trace: TraceEntry[];
  error: string | null;
}

export function useResearchAgent() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [checkpoint, setCheckpoint] = useState<Checkpoint | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [totalCost, setTotalCost] = useState(0);
  const [totalTokens, setTotalTokens] = useState(0);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const detachWs = (ws: WebSocket | null) => {
    if (!ws) return;
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
  };

  const reset = useCallback(() => {
    const ws = wsRef.current;
    detachWs(ws);
    ws?.close();
    wsRef.current = null;
    setPhase("idle");
    setTrace([]);
    setCheckpoint(null);
    setDraft("");
    setTotalCost(0);
    setTotalTokens(0);
    setSources([]);
    setError(null);
  }, []);

  const start = useCallback((topic: string) => {
    reset();
    setPhase("search");

    const ws = new WebSocket("ws://localhost:8000/ws/research");
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ topic }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case "started":
          break;

        case "trace":
          setTrace((prev) => [...prev, msg.entry]);
          if (msg.state) {
            setPhase(msg.state.phase as Phase);
            setTotalCost(msg.state.total_cost_usd);
            setTotalTokens(msg.state.total_tokens);
          }
          break;

        case "checkpoint":
          setPhase("waiting_human");
          setCheckpoint({
            name: msg.name,
            message: msg.data.message,
            sources: msg.data.sources,
            summaries: msg.data.summaries,
          });
          if (msg.data.sources) {
            setSources(msg.data.sources);
          }
          break;

        case "draft":
          setDraft(msg.content);
          break;

        case "done":
          detachWs(ws);
          setPhase("complete");
          if (msg.state) {
            setTotalCost(msg.state.total_cost_usd);
            setTotalTokens(msg.state.total_tokens);
          }
          break;

        case "error":
          detachWs(ws);
          setPhase("failed");
          setError(msg.error);
          break;
      }
    };

    ws.onclose = () => {
      if (phase !== "complete" && phase !== "failed") {
        setPhase("failed");
        setError("Connection closed unexpectedly");
      }
    };

    ws.onerror = () => {
      setPhase("failed");
      setError("WebSocket connection failed — is the backend running?");
    };
  }, [reset]);

  const submitDecision = useCallback(
    (decision: "approve" | "reject", feedback?: string, selectedSources?: number[]) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;

      ws.send(
        JSON.stringify({
          decision,
          feedback,
          selected_sources: selectedSources,
        })
      );
      setCheckpoint(null);
    },
    []
  );

  return {
    phase,
    trace,
    checkpoint,
    draft,
    totalCost,
    totalTokens,
    sources,
    error,
    start,
    submitDecision,
    reset,
  };
}
