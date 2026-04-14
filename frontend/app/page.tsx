"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertCircle,
  CheckCircle2,
  Clipboard,
  ClipboardCheck,
  FileText,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import { useResearchAgent } from "@/lib/useResearchAgent";
import TracePanel from "@/components/TracePanel";
import CheckpointModal from "@/components/CheckpointModal";
import CostBar from "@/components/CostBar";

const EXAMPLE_TOPICS = [
  "Recent advances in retrieval-augmented generation",
  "Trade-offs of WebAssembly vs native apps in 2026",
  "Best practices for human-in-the-loop AI agents",
];

export default function Home() {
  const [topic, setTopic] = useState("");
  const [copied, setCopied] = useState(false);
  const {
    phase,
    trace,
    checkpoint,
    draft,
    totalCost,
    totalTokens,
    error,
    start,
    submitDecision,
    reset,
  } = useResearchAgent();

  const canSubmit = phase === "idle" || phase === "complete" || phase === "failed";
  const inputDisabled = !canSubmit;

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!topic.trim() || !canSubmit) return;
    start(topic.trim());
  };

  const handleReset = () => {
    reset();
    setTopic("");
    setCopied(false);
  };

  const handleCopy = async () => {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // noop
    }
  };

  const showEmptyState = phase === "idle" && trace.length === 0 && !draft;

  return (
    <div className="min-h-screen bg-bg">
      <div className="max-w-3xl mx-auto px-4 py-16 space-y-6">
        {/* Header */}
        <header className="space-y-1">
          <div className="flex items-center gap-2">
            <Sparkles className="size-5 text-accent" />
            <h1 className="text-2xl font-semibold tracking-tight text-fg">
              Agentic Research
            </h1>
          </div>
          <p className="text-sm text-fg-muted">
            AI research agent with human-in-the-loop checkpoints
          </p>
        </header>

        {/* Input */}
        <form onSubmit={handleSubmit}>
          <div className="flex gap-2">
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="Enter a research topic…"
              disabled={inputDisabled}
              className="flex-1 h-11 px-3 bg-surface border border-border rounded-lg text-sm text-fg placeholder:text-fg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:border-accent disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            />
            <button
              type="submit"
              disabled={!topic.trim() || inputDisabled}
              className="h-11 px-5 rounded-lg bg-accent text-accent-fg text-sm font-medium hover:bg-accent-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Research
            </button>
            {(phase === "complete" || phase === "failed") && (
              <button
                type="button"
                onClick={handleReset}
                className="h-11 px-4 rounded-lg border border-border bg-surface text-fg text-sm font-medium hover:bg-surface-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 inline-flex items-center gap-2"
              >
                <RefreshCw className="size-3.5" />
                New
              </button>
            )}
          </div>
        </form>

        {/* Empty state */}
        {showEmptyState && (
          <div className="bg-surface border border-dashed border-border rounded-xl p-8 text-center space-y-4 animate-fade-in">
            <div className="flex justify-center">
              <div className="size-10 rounded-full bg-accent/10 text-accent flex items-center justify-center">
                <Search className="size-5" />
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-sm font-medium text-fg">Start with a topic</p>
              <p className="text-xs text-fg-muted">
                The agent will search, let you pick sources, read and summarize them,
                then draft a brief.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center">
              {EXAMPLE_TOPICS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTopic(t)}
                  className="px-3 py-1.5 rounded-full bg-bg border border-border text-xs text-fg-muted hover:text-fg hover:border-border-strong transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Status bar */}
        {phase !== "idle" && (
          <CostBar phase={phase} totalTokens={totalTokens} totalCost={totalCost} />
        )}

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/30 rounded-lg text-sm text-danger animate-slide-up">
            <AlertCircle className="size-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Execution trace */}
        {trace.length > 0 && <TracePanel trace={trace} />}

        {/* Completion strip */}
        {phase === "complete" && draft && (
          <div className="flex items-center gap-2 text-sm text-success animate-fade-in">
            <CheckCircle2 className="size-4" />
            <span className="font-medium">Research complete</span>
          </div>
        )}

        {/* Draft output */}
        {draft && (
          <div className="bg-surface border border-border rounded-xl p-6 animate-slide-up">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <FileText className="size-4 text-fg-muted" />
                <h2 className="text-base font-semibold text-fg">Research Brief</h2>
              </div>
              <button
                type="button"
                onClick={handleCopy}
                aria-label="Copy markdown"
                className="size-8 rounded-md text-fg-subtle hover:text-fg hover:bg-surface-2 flex items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
              >
                {copied ? (
                  <ClipboardCheck className="size-4 text-success" />
                ) : (
                  <Clipboard className="size-4" />
                )}
              </button>
            </div>
            <div className="brief-md">
              <ReactMarkdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {draft}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {/* HITL checkpoint modal */}
        {checkpoint && (
          <CheckpointModal checkpoint={checkpoint} onDecision={submitDecision} />
        )}
      </div>
    </div>
  );
}
