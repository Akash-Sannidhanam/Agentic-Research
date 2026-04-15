"use client";

import { AlertCircle, BookOpen, Brain, PenLine, RefreshCw, Search } from "lucide-react";
import { TraceEntry } from "@/lib/useResearchAgent";

const PHASE_BADGE: Record<string, string> = {
  search:     "bg-[var(--phase-search-bg)] text-[var(--phase-search-fg)]",
  read:       "bg-[var(--phase-read-bg)] text-[var(--phase-read-fg)]",
  synthesize: "bg-[var(--phase-synthesize-bg)] text-[var(--phase-synthesize-fg)]",
  draft:      "bg-[var(--phase-draft-bg)] text-[var(--phase-draft-fg)]",
  retry:      "bg-[var(--phase-retry-bg)] text-[var(--phase-retry-fg)]",
};

const PHASE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  search: Search,
  read: BookOpen,
  synthesize: Brain,
  draft: PenLine,
  retry: RefreshCw,
};

export default function TracePanel({ trace }: { trace: TraceEntry[] }) {
  if (trace.length === 0) return null;

  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-xs uppercase tracking-wide text-fg-subtle font-medium">
          Execution Trace
        </span>
        <span className="text-xs text-fg-subtle font-mono tabular-nums">
          {trace.length} {trace.length === 1 ? "step" : "steps"}
        </span>
      </div>

      <div className="max-h-96 overflow-y-auto divide-y divide-border">
        {trace.map((entry) => {
          const Icon = entry.error ? AlertCircle : PHASE_ICON[entry.phase] ?? Search;
          const badgeClass = PHASE_BADGE[entry.phase] ?? "bg-surface-2 text-fg-muted";

          return (
            <div
              key={entry.id}
              className="flex items-center gap-3 px-4 py-2 text-sm animate-slide-up"
            >
              <Icon
                className={`size-3.5 shrink-0 ${entry.error ? "text-danger" : "text-fg-muted"}`}
              />
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide shrink-0 ${badgeClass}`}
              >
                {entry.phase}
              </span>
              <div className="flex-1 min-w-0">
                <span className="font-medium text-fg">{entry.action}</span>
                {entry.input && (
                  <span
                    className="text-fg-muted ml-2 truncate inline-block align-bottom max-w-[60%]"
                    title={entry.input}
                  >
                    {entry.input}
                  </span>
                )}
                {entry.error && (
                  <div className="text-danger text-xs mt-0.5">{entry.error}</div>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {entry.cache_read_tokens > 0 && (
                  <span
                    className="rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
                    title={`${entry.cache_read_tokens} tokens served from prompt cache`}
                  >
                    cache hit · {entry.cache_read_tokens}
                  </span>
                )}
                {entry.cache_creation_tokens > 0 && (
                  <span
                    className="rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
                    title={`${entry.cache_creation_tokens} tokens written to prompt cache (paid 1.25× input premium)`}
                  >
                    cache write · {entry.cache_creation_tokens}
                  </span>
                )}
                <div className="text-right font-mono tabular-nums text-xs text-fg-subtle">
                  <div>{entry.duration_ms}ms</div>
                  {entry.cost_usd > 0 && <div>${entry.cost_usd.toFixed(4)}</div>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
