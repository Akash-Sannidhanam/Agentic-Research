"""Drives one full agent run headlessly, auto-answering checkpoints.

The agent's HITL design blocks on `await self._wait_for_human()` after each
checkpoint event. The runner subscribes to agent events and calls
`submit_human_decision` directly, applying scripted decisions for HITL
dataset entries. No WebSocket, no UI.

URL cache integration: `backend.agent.core.read_url` is patched in-place so
the agent's `_phase_read` transparently hits the cache.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any

import anthropic

from ..agent import core as agent_core
from ..agent.core import ResearchAgent
from . import cache as url_cache
from .graders import deterministic, invariants, judge as judge_mod


@contextmanager
def _maybe_cache_reads(use_cache: bool):
    """Swap agent_core.read_url for the cache wrapper for the duration of a run."""
    if not use_cache:
        yield
        return
    original = agent_core.read_url
    agent_core.read_url = url_cache.get_or_fetch
    try:
        yield
    finally:
        agent_core.read_url = original


def _phase_timings(trace: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for entry in trace:
        phase = entry.get("phase", "unknown")
        ms = entry.get("duration_ms") or 0
        totals[phase] = totals.get(phase, 0.0) + ms / 1000.0
    return {k: round(v, 2) for k, v in totals.items()}


def _apply_source_review(agent: ResearchAgent, entry: dict) -> None:
    """Honor reject_source_indexes for HITL entries."""
    hitl = entry.get("hitl") or {}
    reject = set(hitl.get("reject_source_indexes") or [])
    if not reject:
        return
    kept = [s for i, s in enumerate(agent.state.sources) if i not in reject]
    agent.state.selected_sources = kept


def _synthesis_feedback(entry: dict) -> str | None:
    hitl = entry.get("hitl") or {}
    return hitl.get("synthesis_feedback")


async def run_topic(
    entry: dict,
    *,
    use_cache: bool = True,
    judge_client: anthropic.AsyncAnthropic | None = None,
) -> dict:
    """Execute one agent run end-to-end and return a TopicRun record."""
    started = time.time()
    agent = ResearchAgent(topic=entry["topic"])
    error: str | None = None

    with _maybe_cache_reads(use_cache):
        try:
            async for event in agent.run():
                etype = event.get("type")
                if etype == "checkpoint":
                    name = event["name"]
                    if name == "source_review":
                        _apply_source_review(agent, entry)
                        agent.submit_human_decision("approve")
                    elif name == "synthesis_review":
                        fb = _synthesis_feedback(entry)
                        agent.submit_human_decision("approve", feedback=fb)
                elif etype == "error":
                    error = event.get("error")
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

    duration = round(time.time() - started, 2)
    state = agent.state

    # Build the source summary with a citation flag for the report.
    from .graders.deterministic import _LINK_RE

    draft = state.draft or ""
    cited = {m.group(1) for m in _LINK_RE.finditer(draft)}
    source_records = [
        {"url": s["url"], "title": s.get("title", ""), "cited": s["url"] in cited}
        for s in state.summaries
    ]

    if error or not draft:
        return {
            "id": entry["id"],
            "topic": entry["topic"],
            "kind": entry["kind"],
            "error": error or "no draft produced",
            "draft": draft,
            "sources": source_records,
            "deterministic": {"structure_score": 0.0},
            "invariants": [],
            "judge": judge_mod.zero_scores(error or "no draft produced"),
            "cost_usd": round(state.total_cost_usd, 5),
            "duration_s": duration,
            "phase_timings": _phase_timings([t.to_dict() for t in state.trace]),
        }

    det = deterministic.grade(draft, state.summaries)

    inv: list[dict] = []
    if entry["kind"] == "hitl":
        inv = invariants.grade(draft, entry.get("hitl") or {}, state.sources)

    if det["structure_score"] < 1.0:
        judge_result = judge_mod.zero_scores("structure checks failed")
    else:
        client = judge_client or anthropic.AsyncAnthropic()
        judge_result = await judge_mod.judge(
            client, entry["topic"], draft, state.summaries
        )

    total_cost = round(state.total_cost_usd + judge_result.get("cost_usd", 0.0), 5)

    return {
        "id": entry["id"],
        "topic": entry["topic"],
        "kind": entry["kind"],
        "draft": draft,
        "sources": source_records,
        "deterministic": det,
        "invariants": inv,
        "judge": judge_result,
        "cost_usd": total_cost,
        "duration_s": duration,
        "phase_timings": _phase_timings([t.to_dict() for t in state.trace]),
    }
