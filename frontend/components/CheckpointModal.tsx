"use client";

import { useEffect, useRef, useState } from "react";
import {
  Check,
  ExternalLink,
  Loader2,
  ShieldQuestion,
  X,
} from "lucide-react";
import { Checkpoint, Source } from "@/lib/useResearchAgent";

interface Props {
  checkpoint: Checkpoint;
  onDecision: (
    decision: "approve" | "reject",
    feedback?: string,
    selectedSources?: number[]
  ) => void;
}

const MAX_FEEDBACK = 500;

export default function CheckpointModal({ checkpoint, onDecision }: Props) {
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectedIndices, setSelectedIndices] = useState<number[]>(
    checkpoint.sources ? checkpoint.sources.map((_, i) => i) : []
  );
  const firstFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    firstFocusRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) {
        setSubmitting(true);
        onDecision("reject");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDecision, submitting]);

  const toggleSource = (idx: number) => {
    setSelectedIndices((prev) =>
      prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx]
    );
  };

  const handleApprove = () => {
    if (submitting) return;
    setSubmitting(true);
    onDecision(
      "approve",
      feedback || undefined,
      checkpoint.sources ? selectedIndices : undefined
    );
  };

  const handleReject = () => {
    if (submitting) return;
    setSubmitting(true);
    onDecision("reject");
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="checkpoint-title"
    >
      <div className="bg-surface border border-border rounded-xl shadow-xl max-w-2xl w-full max-h-[85vh] flex flex-col animate-slide-up">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-border">
          <div className="flex items-start gap-3">
            <div className="size-8 rounded-lg bg-accent/10 text-accent flex items-center justify-center shrink-0">
              <ShieldQuestion className="size-4" />
            </div>
            <div>
              <h2
                id="checkpoint-title"
                className="text-base font-semibold text-fg"
              >
                Human Review Required
              </h2>
              <p className="text-sm text-fg-muted mt-0.5">{checkpoint.message}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleReject}
            disabled={submitting}
            aria-label="Reject and close"
            className="shrink-0 size-8 rounded-md text-fg-subtle hover:text-fg hover:bg-surface-2 flex items-center justify-center transition-colors focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-50"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {checkpoint.sources && (
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-fg-subtle font-medium">
                Sources to include ({selectedIndices.length}/{checkpoint.sources.length})
              </p>
              <div className="space-y-2">
                {checkpoint.sources.map((source: Source, i: number) => {
                  const checked = selectedIndices.includes(i);
                  return (
                    <label
                      key={i}
                      ref={(el) => {
                        if (i === 0) firstFocusRef.current = el;
                      }}
                      tabIndex={0}
                      className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none ${
                        checked
                          ? "border-accent bg-accent/5"
                          : "border-border hover:bg-surface-2"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSource(i)}
                        className="sr-only peer"
                      />
                      <span
                        className={`mt-0.5 size-4 rounded border shrink-0 flex items-center justify-center transition-colors ${
                          checked
                            ? "bg-accent border-accent"
                            : "bg-bg border-border-strong"
                        }`}
                        aria-hidden="true"
                      >
                        {checked && (
                          <Check className="size-3 text-accent-fg" strokeWidth={3} />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-sm text-fg truncate">
                          {source.title}
                        </div>
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-xs text-fg-subtle hover:text-accent truncate inline-flex items-center gap-1 max-w-full"
                        >
                          <ExternalLink className="size-3 shrink-0" />
                          <span className="truncate">{source.url}</span>
                        </a>
                        <div className="text-xs text-fg-muted mt-1 line-clamp-2">
                          {source.snippet}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {checkpoint.summaries && (
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-fg-subtle font-medium">
                Summaries ({checkpoint.summaries.length})
              </p>
              <div className="space-y-2">
                {checkpoint.summaries.map((s, i) => (
                  <div key={i} className="p-3 bg-surface-2 rounded-lg text-sm">
                    <div className="font-medium text-fg">{s.title}</div>
                    <div className="text-fg-muted mt-1 whitespace-pre-wrap">
                      {s.summary}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-1">
            <label
              htmlFor="checkpoint-feedback"
              className="text-xs uppercase tracking-wide text-fg-subtle font-medium block"
            >
              Feedback (optional)
            </label>
            <textarea
              id="checkpoint-feedback"
              ref={(el) => {
                if (!checkpoint.sources && el) firstFocusRef.current = el;
              }}
              value={feedback}
              onChange={(e) =>
                setFeedback(e.target.value.slice(0, MAX_FEEDBACK))
              }
              placeholder="Add instructions or context for the agent…"
              disabled={submitting}
              className="w-full bg-bg border border-border rounded-lg p-3 text-sm resize-none h-24 placeholder:text-fg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:border-accent disabled:opacity-50"
            />
            <div className="text-xs text-fg-subtle text-right font-mono tabular-nums">
              {feedback.length}/{MAX_FEEDBACK}
            </div>
          </div>
        </div>

        {/* Sticky footer */}
        <div className="flex gap-2 justify-end px-6 py-3 border-t border-border bg-surface rounded-b-xl">
          <button
            type="button"
            onClick={handleReject}
            disabled={submitting}
            className="px-4 py-2 rounded-lg border border-border text-fg text-sm font-medium hover:bg-surface-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-50"
          >
            Reject & Stop
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={submitting}
            className="px-4 py-2 rounded-lg bg-accent text-accent-fg text-sm font-medium hover:bg-accent-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-70 inline-flex items-center gap-2"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                Submitting…
              </>
            ) : (
              "Approve & Continue"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
