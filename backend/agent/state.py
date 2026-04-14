"""Agent state machine — tracks execution through search → read → synthesize → draft."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(str, Enum):
    SEARCH = "search"
    READ = "read"
    SYNTHESIZE = "synthesize"
    DRAFT = "draft"
    COMPLETE = "complete"
    FAILED = "failed"
    WAITING_HUMAN = "waiting_human"


@dataclass
class TraceEntry:
    """One step in the execution trace."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    phase: str = ""
    action: str = ""
    input: str = ""
    output: str = ""
    token_count: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "action": self.action,
            "input": self.input[:200],  # truncate for frontend
            "output": self.output[:500],
            "token_count": self.token_count,
            "cost_usd": round(self.cost_usd, 6),
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "error": self.error,
        }


@dataclass
class AgentState:
    """Full state of a research run."""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    topic: str = ""
    phase: Phase = Phase.SEARCH
    sources: list[dict[str, str]] = field(default_factory=list)  # {url, title, snippet}
    selected_sources: list[dict[str, str]] = field(default_factory=list)
    summaries: list[dict[str, str]] = field(default_factory=list)  # {url, summary}
    draft: str = ""
    trace: list[TraceEntry] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error: str | None = None
    human_decision: str | None = None  # "approve" | "reject" | "modify"
    human_feedback: str | None = None

    def add_trace(self, **kwargs) -> TraceEntry:
        entry = TraceEntry(**kwargs)
        self.trace.append(entry)
        self.total_tokens += entry.token_count
        self.total_cost_usd += entry.cost_usd
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "phase": self.phase.value,
            "sources_found": len(self.sources),
            "sources_selected": len(self.selected_sources),
            "summaries_done": len(self.summaries),
            "has_draft": bool(self.draft),
            "trace": [t.to_dict() for t in self.trace],
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "error": self.error,
        }
