"""HITL-specific invariants: did the agent actually respond to human decisions?

These are deterministic, cheap checks. They complement the LLM judge — the
judge is good at "is the prose good?" but bad at "is this specific URL in
this specific set?". For HITL behavior we want binary answers.
"""

from __future__ import annotations

import re

from .deterministic import _LINK_RE  # reuse the same link regex


_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "to", "for", "and", "or", "but",
    "over", "with", "by", "at", "as", "is", "are", "was", "were", "be",
    "specifically", "focus", "emphasize", "named", "partnerships", "from",
    "this", "that", "these", "those", "it", "its",
}


def _extract_keywords(feedback: str) -> list[str]:
    """Pull content words out of a short feedback string.

    We want terms the draft should visibly incorporate: proper nouns, nouns,
    named entities. Low-precision keyword extraction is fine — the check is
    coarse ("did any of these terms show up?") not grammatical.
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]+", feedback)
    return [w for w in words if w.lower() not in _STOPWORDS and len(w) > 2]


def rejected_sources_absent(draft: str, rejected_urls: list[str]) -> dict:
    cited = {m.group(1) for m in _LINK_RE.finditer(draft)}
    leaked = sorted(set(rejected_urls) & cited)
    return {
        "name": "rejected_sources_absent",
        "pass": len(leaked) == 0,
        "detail": f"leaked urls: {leaked}" if leaked else "no rejected urls in draft",
    }


def feedback_keywords_present(draft: str, feedback: str) -> dict:
    """Soft check: do the feedback's content words show up in the draft?

    Reported but not used to gate — feedback can be incorporated semantically
    without lexical overlap. A low score is a signal, not a failure.
    """
    if not feedback:
        return {
            "name": "feedback_keywords_present",
            "pass": True,
            "detail": "no feedback provided",
        }

    keywords = _extract_keywords(feedback)
    if not keywords:
        return {
            "name": "feedback_keywords_present",
            "pass": True,
            "detail": "no content keywords extracted",
        }

    draft_lower = draft.lower()
    hits = [kw for kw in keywords if kw.lower() in draft_lower]
    coverage = len(hits) / len(keywords)
    return {
        "name": "feedback_keywords_present",
        "pass": coverage >= 0.5,
        "detail": f"{len(hits)}/{len(keywords)} keywords present ({coverage:.0%}): {hits}",
        "coverage": round(coverage, 3),
    }


def grade(draft: str, hitl_config: dict, sources: list[dict]) -> list[dict]:
    """Run all invariants that apply to this HITL config."""
    invariants = []

    reject_idx = hitl_config.get("reject_source_indexes") or []
    if reject_idx:
        rejected_urls = [sources[i]["url"] for i in reject_idx if i < len(sources)]
        invariants.append(rejected_sources_absent(draft, rejected_urls))

    feedback = hitl_config.get("synthesis_feedback")
    if feedback:
        invariants.append(feedback_keywords_present(draft, feedback))

    return invariants
