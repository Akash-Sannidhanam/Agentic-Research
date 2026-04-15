"""LLM-as-judge: scores the qualitative dimensions a regex can't measure.

Uses Haiku 4.5 (cheap, plenty smart for rubric application). Structured output
is enforced via tool-use — the model must call `submit_scores` with a JSON
object matching the schema, so we never parse free-form text.

The rubric system prompt is cacheable: the same ~1.2k-token prompt is sent for
every topic in a run, so prompt caching amortizes it after the first call.
"""

from __future__ import annotations

import json

import anthropic

JUDGE_MODEL = "claude-haiku-4-5-20251001"

# Haiku 4.5 pricing per 1M tokens.
_JUDGE_INPUT = 1.00
_JUDGE_OUTPUT = 5.00
_JUDGE_CACHE_WRITE = _JUDGE_INPUT * 1.25
_JUDGE_CACHE_READ = _JUDGE_INPUT * 0.10


JUDGE_SYSTEM_PROMPT = """You are an evaluator scoring a research brief that another AI produced from a set of source summaries. Your job is to apply a rubric consistently across many briefs so scores are comparable over time. You are not here to rewrite the brief or point out style preferences — only to score it.

# Rubric

Score the brief on four dimensions. Each dimension is scored 1-5 on the scale below. Be calibrated: a 5 is reserved for genuinely excellent work, a 3 is an average competent brief, a 1 is seriously deficient. Do not grade-inflate.

## 1. Faithfulness (1-5)

Does every factual claim in the brief trace back to the provided source summaries?

- 5: Every claim is grounded in the sources. No invented numbers, names, or events.
- 4: One minor drift — e.g., a rounded number, a loose paraphrase — but no invented facts.
- 3: A few claims go beyond what the sources say, though nothing contradicts them.
- 2: Multiple claims are not supported by the provided sources, or the brief contradicts a source.
- 1: The brief contains fabricated facts — numbers, quotes, or events not in any source.

## 2. Specificity (1-5)

Does the brief preserve the concrete information in the sources — numbers, dates, named entities, quotes — rather than hedging into generic language?

- 5: Rich with specifics. Precise figures, dates, named organizations, direct quotes where warranted.
- 4: Mostly specific, occasional rounding or generic phrasing.
- 3: A mix of specific and generic. Some passages read like any generic summary of the topic.
- 2: Heavily generic. Specifics that were in the sources got washed out into vague language.
- 1: Almost no specific information survived. Could be written without the sources.

## 3. Coverage (1-5)

Does the brief address the research topic as asked, and does it use the sources it was given rather than ignoring most of them?

- 5: Directly answers the topic. Draws on most of the provided sources.
- 4: Answers the topic. Uses most sources, one or two lightly.
- 3: Partially on-topic or notably lopsided in which sources it leans on.
- 2: Drifts off-topic in sections, or ignores most sources.
- 1: Does not answer the topic asked.

## 4. Citation Quality (1-5)

Are citations used well — placed on the claims that need them, pointing to the right source, not overused or missing?

- 5: Citations sit on non-trivial claims, point to the source that actually supports that claim, and are neither over- nor under-used.
- 4: Mostly well-placed; one or two claims under-cited or a citation in the wrong spot.
- 3: Citations exist but are applied unevenly — some sections well-cited, others sparse.
- 2: Many non-trivial claims uncited, or citations don't match the claim's source.
- 1: Citations missing, random, or pointing to wrong sources throughout.

# Output

Call the `submit_scores` tool exactly once. `rationale` should be 2-4 sentences referencing specific passages or failures, not generic praise. Do not call the tool twice."""


SUBMIT_SCORES_TOOL = {
    "name": "submit_scores",
    "description": "Record rubric scores for the brief. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},
            "specificity": {"type": "integer", "minimum": 1, "maximum": 5},
            "coverage": {"type": "integer", "minimum": 1, "maximum": 5},
            "citation_quality": {"type": "integer", "minimum": 1, "maximum": 5},
            "rationale": {
                "type": "string",
                "description": "2-4 sentences citing specific passages or issues.",
            },
        },
        "required": [
            "faithfulness",
            "specificity",
            "coverage",
            "citation_quality",
            "rationale",
        ],
    },
}


def _judge_cost(usage) -> float:
    inp = usage.input_tokens
    out = usage.output_tokens
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        inp * _JUDGE_INPUT
        + cw * _JUDGE_CACHE_WRITE
        + cr * _JUDGE_CACHE_READ
        + out * _JUDGE_OUTPUT
    ) / 1_000_000


async def judge(
    client: anthropic.AsyncAnthropic,
    topic: str,
    draft: str,
    summaries: list[dict],
) -> dict:
    """Return {faithfulness, specificity, coverage, citation_quality, composite, rationale, cost_usd}."""
    summaries_text = "\n\n".join(
        f"### {s['title']}\nSource: {s['url']}\n{s['summary']}"
        for s in summaries
        if not s["summary"].startswith("Skipped")
    )

    user_message = (
        f"Research topic:\n{topic}\n\n"
        f"Source summaries given to the drafting step:\n\n{summaries_text}\n\n"
        f"---\nBrief to score:\n\n{draft}"
    )

    response = await client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=600,
        system=[{
            "type": "text",
            "text": JUDGE_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[SUBMIT_SCORES_TOOL],
        tool_choice={"type": "tool", "name": "submit_scores"},
        messages=[{"role": "user", "content": user_message}],
    )

    tool_use = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "submit_scores"),
        None,
    )
    if tool_use is None:
        raise RuntimeError(
            f"Judge did not call submit_scores. Stop reason: {response.stop_reason}. "
            f"Content: {response.content}"
        )

    scores = tool_use.input
    composite = round(
        (
            scores["faithfulness"]
            + scores["specificity"]
            + scores["coverage"]
            + scores["citation_quality"]
        )
        / 4.0,
        2,
    )

    return {
        "faithfulness": scores["faithfulness"],
        "specificity": scores["specificity"],
        "coverage": scores["coverage"],
        "citation_quality": scores["citation_quality"],
        "composite": composite,
        "rationale": scores["rationale"],
        "cost_usd": round(_judge_cost(response.usage), 5),
    }


def zero_scores(reason: str) -> dict:
    """Placeholder scores when the draft failed structural checks."""
    return {
        "faithfulness": 0,
        "specificity": 0,
        "coverage": 0,
        "citation_quality": 0,
        "composite": 0.0,
        "rationale": f"Skipped judge: {reason}",
        "cost_usd": 0.0,
    }
