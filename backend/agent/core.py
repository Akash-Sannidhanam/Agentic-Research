"""Core agent loop — search → read → synthesize → draft with HITL checkpoints."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import anthropic

from .state import AgentState, Phase, TraceEntry
from ..tools import search_web, read_url

# Claude pricing per 1M tokens: (input, output).
# Cache write (5-min TTL) is 1.25× input; cache read is 0.1× input.
_PRICING = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7":   (5.00, 25.00),
}


def _estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    # input_tokens is the uncached remainder; the three input buckets are additive.
    input_rate, output_rate = _PRICING[model]
    return (
        input_tokens * input_rate
        + cache_creation_tokens * input_rate * 1.25
        + cache_read_tokens * input_rate * 0.10
        + output_tokens * output_rate
    ) / 1_000_000


# Frozen system prompts — kept byte-stable to preserve the prompt-cache prefix.
# Anything dynamic (topic, sources, feedback) MUST stay in the user message.
# Sonnet 4's minimum cacheable prefix is 1024 tokens; SYNTHESIZE_SYSTEM_PROMPT
# is sized to comfortably clear that threshold.

SYNTHESIZE_SYSTEM_PROMPT = """You are a senior research analyst preparing source-by-source briefings for a downstream synthesis step. Your only job in this turn is to extract what matters from a single source so it can be combined with others later. You are not writing the final brief; you are preparing structured notes for it.

# Output format

Produce 3 to 5 bullet points and nothing else. No preamble, no closing remarks, no headings, no meta-commentary about the source. Each bullet starts with `- ` and is one to three sentences. Order bullets by importance: most load-bearing fact first.

# What belongs in a bullet

Each bullet must carry information that would change a reader's understanding of the topic. Prefer:

- Specific numbers, percentages, dates, durations, monetary amounts, and named entities (people, organizations, products, jurisdictions). When the source gives a precise figure, use the precise figure — do not round or hedge unless the source itself hedged.
- Causal claims and mechanisms ("X happens because Y"), not just observations.
- Comparisons and benchmarks ("twice the rate of the prior year", "the largest in the sector since 2019").
- Concrete examples that illustrate a general claim.
- Direct quotes when the wording itself is the news (regulatory language, official statements, controversial framings). Quote sparingly — at most one quoted bullet per source — and reproduce the wording verbatim inside double quotes.

What does not belong in a bullet:

- Generic background that any reader of the topic would already know.
- The source's own throat-clearing ("This article will explore...", "In recent years...").
- Author opinions presented as fact, unless explicitly attributed.
- Restating the source's title or URL.

# Handling uncertainty and provenance

When the source itself flags uncertainty — forecasts, projections, anonymous sourcing, leaked documents, single-source claims — preserve that hedge in your bullet. Use phrases like "the source projects", "according to an unnamed official", "the company stated in a press release", or "preliminary data suggests". The downstream step needs to know what is established versus speculative.

If two parts of the source contradict each other, surface the contradiction in a single bullet rather than picking a side. Example: `- The press release claims a 30% reduction, but the linked methodology footnote describes a 12% baseline-adjusted figure.`

If the source is paywalled, truncated, or appears to be only navigational chrome with no substance, return a single bullet: `- [Source provided no extractable content beyond [briefly describe what you saw]].` Do not invent.

# Faithfulness rules

- Never introduce facts that are not in the provided source content. If the topic asks about X but the source is about Y, your bullets describe Y and that is fine — the synthesis step decides what to keep.
- Do not merge facts from different parts of the source into a single claim if doing so changes the meaning.
- Preserve the source's own units, dates, and proper nouns. Do not convert currencies, translate dates, or anglicize names unless the source did.
- If the source contains a number that looks suspicious (e.g., obviously a typo, or contradicts a widely-known fact), still report it as written — flag the suspicion in a parenthetical, do not silently correct it.

# Worked example

Topic: "impact of remote work on commercial real estate vacancy"

Source content (excerpt): "Manhattan office availability hit 18.4% in Q3 2024, up from 11.9% pre-pandemic, per Cushman & Wakefield. The brokerage attributes 60% of that gap to hybrid work patterns and the remainder to a 2023 supply wave from buildings begun in 2019. Class A trophy assets remain near 95% leased; the vacancy is concentrated in Class B and C product built before 1990. 'We are watching a structural repricing, not a cyclical dip,' said the firm's head of research."

Acceptable output:

- Manhattan office availability reached 18.4% in Q3 2024, up from 11.9% pre-pandemic, per Cushman & Wakefield.
- The brokerage attributes ~60% of the increase to hybrid work and the remainder to a 2023 supply wave from buildings started in 2019.
- Vacancy is bifurcated: Class A trophy assets remain near 95% leased while Class B and C buildings constructed before 1990 absorb most of the slack.
- Cushman & Wakefield's head of research framed the trend as "a structural repricing, not a cyclical dip" — language that signals their internal view rather than a transient correction.

That is the standard. Apply it to whatever source the user provides next."""


DRAFT_SYSTEM_PROMPT = """You are a senior research analyst writing the final research brief based on per-source notes that have already been distilled by an earlier step.

Structure the brief as:
1. A two-sentence executive summary at the top, with no heading.
2. Three to five body sections with markdown `##` headers, each covering a coherent sub-theme of the topic.
3. A final `## Key Takeaways` section with three to five bullet points. This section is mandatory — always include it as the last section, even if the body sections feel complete.

Cite sources inline using markdown link syntax: `[Source Title](url)`. Every non-trivial claim should carry a citation. When two sources support the same point, cite both. When sources disagree, name the disagreement explicitly and cite each side.

Be specific. Use the numbers, names, and dates that appear in the source notes — do not hedge or round when a precise figure was given. Flag any contradictions between sources rather than smoothing them over. If the user has supplied additional instructions in their message, treat those as overrides to this default structure where they conflict."""


class ResearchAgent:
    """Multi-step research agent with HITL checkpoints.

    Usage:
        agent = ResearchAgent(topic="...")
        async for event in agent.run():
            # event is a dict: {"type": "trace"|"checkpoint"|"draft"|"done"|"error", ...}
            if event["type"] == "checkpoint":
                agent.submit_human_decision("approve")
    """

    def __init__(
        self,
        topic: str,
        synth_model: str = "claude-sonnet-4-6",
        draft_model: str = "claude-opus-4-7",
    ):
        self.state = AgentState(topic=topic)
        self.synth_model = synth_model
        self.draft_model = draft_model
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
        """Read the selected (or all) sources concurrently."""
        self.state.phase = Phase.READ

        # Use human-selected sources if provided, otherwise top 5
        to_read = self.state.selected_sources or self.state.sources[:5]

        async def fetch_one(source: dict) -> dict:
            t0 = time.time()
            try:
                content = await self._retry(read_url, source["url"])
            except Exception as e:
                content = f"[Error fetching {source['url']}: {e}]"
            source["content"] = content
            entry = self.state.add_trace(
                phase="read",
                action="fetch_url",
                input=source["url"],
                output=content[:300],
                duration_ms=int((time.time() - t0) * 1000),
            )
            return {"type": "trace", "entry": entry.to_dict(), "state": self.state.to_dict()}

        tasks = [asyncio.create_task(fetch_one(src)) for src in to_read]
        for completed in asyncio.as_completed(tasks):
            yield await completed

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
            user_message = (
                f"Research topic: {self.state.topic}\n\n"
                f"Source title: {source.get('title', '')}\n\n"
                f"Content:\n{content}"
            )

            response = await self.client.messages.create(
                model=self.synth_model,
                max_tokens=500,
                system=[{
                    "type": "text",
                    "text": SYNTHESIZE_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_message}],
            )

            summary_text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cost = _estimate_cost(self.synth_model, input_tokens, output_tokens, cache_creation, cache_read)

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
                token_count=input_tokens + output_tokens + cache_creation + cache_read,
                cache_creation_tokens=cache_creation,
                cache_read_tokens=cache_read,
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
            extra_instructions = (
                f"\n\nAdditional instructions from the user: {self.state.human_feedback}"
            )

        user_message = (
            f"Research topic: {self.state.topic}\n"
            f"{extra_instructions}\n\n"
            f"Source summaries:\n\n{summaries_text}"
        )

        # Single call per run — no cache_control: a 1.25× write premium with
        # zero subsequent reads is a net loss.
        response = await self.client.messages.create(
            model=self.draft_model,
            max_tokens=4000,
            system=DRAFT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        self.state.draft = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cost = _estimate_cost(self.draft_model, input_tokens, output_tokens, cache_creation, cache_read)

        entry = self.state.add_trace(
            phase="draft",
            action="generate_draft",
            input=f"Topic: {self.state.topic}, {len(self.state.summaries)} summaries",
            output=self.state.draft[:500],
            token_count=input_tokens + output_tokens + cache_creation + cache_read,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
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
