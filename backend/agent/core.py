"""Core agent loop — search → read → synthesize → draft with HITL checkpoints."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import anthropic

from .state import AgentState, Phase, TraceEntry
from ..tools import search_web, read_url

# Claude pricing (Sonnet 4) per 1M tokens
INPUT_COST_PER_M = 3.00
OUTPUT_COST_PER_M = 15.00


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_COST_PER_M + output_tokens * OUTPUT_COST_PER_M) / 1_000_000


class ResearchAgent:
    """Multi-step research agent with HITL checkpoints.

    Usage:
        agent = ResearchAgent(topic="...")
        async for event in agent.run():
            # event is a dict: {"type": "trace"|"checkpoint"|"draft"|"done"|"error", ...}
            if event["type"] == "checkpoint":
                agent.submit_human_decision("approve")
    """

    def __init__(self, topic: str, model: str = "claude-sonnet-4-20250514"):
        self.state = AgentState(topic=topic)
        self.model = model
        self.client = anthropic.AsyncAnthropic()
        self._human_event: asyncio.Event = asyncio.Event()
        self._max_retries = 2

    def submit_human_decision(self, decision: str, feedback: str | None = None):
        """Called by the API layer when a human responds to a checkpoint."""
        self.state.human_decision = decision
        self.state.human_feedback = feedback
        self._human_event.set()

    async def run(self) -> AsyncIterator[dict]:
        """Execute the full agent loop, yielding events for the frontend."""
        try:
            # Phase 1: Search
            async for event in self._phase_search():
                yield event

            # Checkpoint 1: Human reviews sources
            yield self._checkpoint("source_review", {
                "message": f"Found {len(self.state.sources)} sources. Review and approve the top picks.",
                "sources": self.state.sources,
            })
            await self._wait_for_human()

            if self.state.human_decision == "reject":
                self.state.phase = Phase.FAILED
                yield {"type": "done", "reason": "User rejected sources"}
                return

            # Phase 2: Read selected sources
            async for event in self._phase_read():
                yield event

            # Phase 3: Synthesize
            async for event in self._phase_synthesize():
                yield event

            # Checkpoint 2: Human reviews synthesis plan
            yield self._checkpoint("synthesis_review", {
                "message": "Here's the synthesis of sources. Approve to generate the final draft.",
                "summaries": self.state.summaries,
            })
            await self._wait_for_human()

            if self.state.human_decision == "reject":
                self.state.phase = Phase.FAILED
                yield {"type": "done", "reason": "User rejected synthesis"}
                return

            # Phase 4: Draft
            async for event in self._phase_draft():
                yield event

            self.state.phase = Phase.COMPLETE
            yield {"type": "done", "state": self.state.to_dict()}

        except Exception as e:
            self.state.phase = Phase.FAILED
            self.state.error = str(e)
            yield {"type": "error", "error": str(e), "state": self.state.to_dict()}

    async def _phase_search(self) -> AsyncIterator[dict]:
        """Search the web for sources on the topic."""
        self.state.phase = Phase.SEARCH
        t0 = time.time()

        sources = await self._retry(search_web, self.state.topic)

        entry = self.state.add_trace(
            phase="search",
            action="web_search",
            input=self.state.topic,
            output=f"Found {len(sources)} results",
            duration_ms=int((time.time() - t0) * 1000),
        )
        self.state.sources = sources
        yield {"type": "trace", "entry": entry.to_dict(), "state": self.state.to_dict()}

    async def _phase_read(self) -> AsyncIterator[dict]:
        """Read the selected (or all) sources."""
        self.state.phase = Phase.READ

        # Use human-selected sources if provided, otherwise top 5
        to_read = self.state.selected_sources or self.state.sources[:5]

        for source in to_read:
            t0 = time.time()
            try:
                content = await self._retry(read_url, source["url"])
            except Exception as e:
                content = f"[Error fetching {source['url']}: {e}]"

            entry = self.state.add_trace(
                phase="read",
                action="fetch_url",
                input=source["url"],
                output=content[:300],
                duration_ms=int((time.time() - t0) * 1000),
            )
            source["content"] = content
            yield {"type": "trace", "entry": entry.to_dict(), "state": self.state.to_dict()}

    async def _phase_synthesize(self) -> AsyncIterator[dict]:
        """Use Claude to summarize each source."""
        self.state.phase = Phase.SYNTHESIZE

        to_read = self.state.selected_sources or self.state.sources[:5]

        for source in to_read:
            content = source.get("content", "")
            if not content or content.startswith("[Error"):
                self.state.summaries.append({
                    "url": source["url"],
                    "title": source.get("title", ""),
                    "summary": f"Skipped — {content[:100]}",
                })
                continue

            t0 = time.time()
            prompt = (
                f"Summarize this content in 3-5 bullet points, focusing on key facts "
                f"relevant to the research topic: '{self.state.topic}'.\n\n"
                f"Source: {source['title']}\n\n{content}"
            )

            response = await self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            summary_text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = _estimate_cost(input_tokens, output_tokens)

            self.state.summaries.append({
                "url": source["url"],
                "title": source.get("title", ""),
                "summary": summary_text,
            })

            entry = self.state.add_trace(
                phase="synthesize",
                action="summarize_source",
                input=source["url"],
                output=summary_text[:300],
                token_count=input_tokens + output_tokens,
                cost_usd=cost,
                duration_ms=int((time.time() - t0) * 1000),
            )
            yield {"type": "trace", "entry": entry.to_dict(), "state": self.state.to_dict()}

    async def _phase_draft(self) -> AsyncIterator[dict]:
        """Generate the final research draft from summaries."""
        self.state.phase = Phase.DRAFT
        t0 = time.time()

        summaries_text = "\n\n".join(
            f"### {s['title']}\nSource: {s['url']}\n{s['summary']}"
            for s in self.state.summaries
            if not s["summary"].startswith("Skipped")
        )

        extra_instructions = ""
        if self.state.human_feedback:
            extra_instructions = f"\n\nAdditional instructions from the user: {self.state.human_feedback}"

        prompt = (
            f"You are a research analyst. Based on the following source summaries, "
            f"write a well-structured research brief on: '{self.state.topic}'.\n\n"
            f"Requirements:\n"
            f"- Start with a 2-sentence executive summary\n"
            f"- Organize into 3-5 sections with headers\n"
            f"- Cite sources inline as [Source Title](url)\n"
            f"- End with 'Key Takeaways' (3-5 bullets)\n"
            f"- Be specific — use numbers, names, dates when available\n"
            f"- Flag any contradictions between sources\n"
            f"{extra_instructions}\n\n"
            f"Source summaries:\n\n{summaries_text}"
        )

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        self.state.draft = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = _estimate_cost(input_tokens, output_tokens)

        entry = self.state.add_trace(
            phase="draft",
            action="generate_draft",
            input=f"Topic: {self.state.topic}, {len(self.state.summaries)} summaries",
            output=self.state.draft[:500],
            token_count=input_tokens + output_tokens,
            cost_usd=cost,
            duration_ms=int((time.time() - t0) * 1000),
        )
        yield {"type": "trace", "entry": entry.to_dict(), "state": self.state.to_dict()}
        yield {"type": "draft", "content": self.state.draft}

    def _checkpoint(self, name: str, data: dict) -> dict:
        """Pause execution and yield a checkpoint for human review."""
        self.state.phase = Phase.WAITING_HUMAN
        self.state.human_decision = None
        self.state.human_feedback = None
        self._human_event.clear()
        return {"type": "checkpoint", "name": name, "data": data, "state": self.state.to_dict()}

    async def _wait_for_human(self):
        """Block until a human submits a decision."""
        await self._human_event.wait()

    async def _retry(self, fn, *args, **kwargs):
        """Retry a tool call with exponential backoff."""
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    self.state.add_trace(
                        phase=self.state.phase.value,
                        action="retry",
                        input=f"Attempt {attempt + 1} failed: {e}",
                        output=f"Waiting {wait}s before retry",
                        error=str(e),
                    )
                    await asyncio.sleep(wait)
        raise last_error
