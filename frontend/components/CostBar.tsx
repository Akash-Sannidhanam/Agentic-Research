"use client";

import { Check, Clock, XCircle } from "lucide-react";
import { Phase } from "@/lib/useResearchAgent";

const STEPS: { key: Phase; label: string }[] = [
  { key: "search",     label: "Search" },
  { key: "read",       label: "Read" },
  { key: "synthesize", label: "Synthesize" },
  { key: "draft",      label: "Draft" },
];

const STEP_INDEX: Record<Phase, number> = {
  idle: -1,
  search: 0,
  read: 1,
  synthesize: 2,
  draft: 3,
  waiting_human: -1,
  complete: 4,
  failed: -1,
};

interface Props {
  phase: Phase;
  totalTokens: number;
  totalCost: number;
}

export default function CostBar({ phase, totalTokens, totalCost }: Props) {
  const currentIdx = STEP_INDEX[phase];
  const isWaiting = phase === "waiting_human";
  const isFailed = phase === "failed";
  const isComplete = phase === "complete";

  return (
    <div className="bg-surface border border-border rounded-lg px-4 py-2.5 flex items-center gap-4 animate-slide-up">
      {isWaiting ? (
        <div className="flex items-center gap-2 text-sm">
          <span className="size-2 rounded-full bg-warning animate-pulse-soft" />
          <Clock className="size-3.5 text-warning" />
          <span className="font-medium text-fg">Awaiting your review</span>
        </div>
      ) : isFailed ? (
        <div className="flex items-center gap-2 text-sm">
          <XCircle className="size-4 text-danger" />
          <span className="font-medium text-danger">Failed</span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 min-w-0">
          {STEPS.map((step, i) => {
            const isActive = i === currentIdx;
            const isDone = isComplete || i < currentIdx;
            return (
              <div key={step.key} className="flex items-center gap-1.5">
                <span
                  className={[
                    "size-2 rounded-full shrink-0 transition-colors",
                    isActive && "bg-accent animate-pulse-soft",
                    isDone && !isActive && "bg-fg-muted",
                    !isActive && !isDone && "border border-border bg-bg",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                />
                {isActive && (
                  <span className="text-sm font-medium text-fg whitespace-nowrap">
                    {step.label}…
                  </span>
                )}
                {isComplete && i === STEPS.length - 1 && (
                  <span className="text-sm font-medium text-success whitespace-nowrap flex items-center gap-1">
                    <Check className="size-3.5" /> Complete
                  </span>
                )}
                {i < STEPS.length - 1 && (
                  <span className="w-4 h-px bg-border shrink-0" />
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="ml-auto flex items-center gap-4 font-mono tabular-nums text-xs text-fg-muted shrink-0">
        <span>{totalTokens.toLocaleString()} tok</span>
        <span>${totalCost.toFixed(4)}</span>
      </div>
    </div>
  );
}
