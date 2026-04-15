"""Deterministic structure and citation checks on the final draft.

All functions are pure: they take the raw draft and the source summaries used
to generate it and return a dict of booleans / numbers. `grade()` rolls them
up into a single record with a 0-or-1 `structure_score`.
"""

from __future__ import annotations

import re

# Markdown link: [text](url). Captures the URL.
_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^\s)]+)\)")
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
# Accept common bullet characters: -, *, +, and Unicode • ‣ ⁃.
_BULLET_RE = re.compile(r"^\s*[-*+•‣⁃]\s+", re.MULTILINE)


def _cited_urls(draft: str) -> set[str]:
    return {m.group(1) for m in _LINK_RE.finditer(draft)}


def has_exec_summary(draft: str) -> bool:
    """Opening prose summary of 1-4 sentences.

    Accepts common preambles before the summary: a document title (`# ...`),
    an `## Executive Summary` header, or both. The first *prose* block after
    any leading headers is what we score. Stops looking if that block is itself
    another header or if more than two leading headers appear.
    """
    blocks = [b.strip() for b in draft.strip().split("\n\n") if b.strip()]
    if not blocks:
        return False

    # Skip up to 2 consecutive leading header blocks (e.g. `# Title` then
    # `## Executive Summary`). More than that means the summary is missing.
    i = 0
    while i < len(blocks) and i < 2 and blocks[i].startswith("#"):
        i += 1

    if i >= len(blocks) or blocks[i].startswith("#"):
        return False

    body = blocks[i]
    sentences = re.findall(r"[.!?](\s|$)", body)
    return 1 <= len(sentences) <= 4


def section_count(draft: str) -> int:
    """Count `##` sections excluding the Key Takeaways section."""
    return sum(
        1
        for m in _SECTION_RE.finditer(draft)
        if "key takeaway" not in m.group(1).lower()
    )


def has_key_takeaways(draft: str) -> bool:
    return any(
        "key takeaway" in m.group(1).lower() for m in _SECTION_RE.finditer(draft)
    )


def key_takeaways_count(draft: str) -> int:
    """Bullets in the Key Takeaways section, 0 if the section is missing."""
    # Split on `## ` headers and find the Key Takeaways block.
    parts = re.split(r"^##\s+", draft, flags=re.MULTILINE)
    for part in parts:
        header, _, body = part.partition("\n")
        if "key takeaway" in header.lower():
            return len(_BULLET_RE.findall(body))
    return 0


def citation_coverage(draft: str, summaries: list[dict]) -> float:
    """Fraction of read sources cited at least once in the draft."""
    read = [s for s in summaries if not s["summary"].startswith("Skipped")]
    if not read:
        return 0.0
    cited = _cited_urls(draft)
    hits = sum(1 for s in read if s["url"] in cited)
    return hits / len(read)


def no_hallucinated_urls(draft: str, summaries: list[dict]) -> tuple[bool, list[str]]:
    """Every URL cited in the draft must come from the read summaries."""
    allowed = {s["url"] for s in summaries}
    cited = _cited_urls(draft)
    extras = sorted(cited - allowed)
    return (len(extras) == 0, extras)


def grade(draft: str, summaries: list[dict]) -> dict:
    exec_ok = has_exec_summary(draft)
    sections = section_count(draft)
    kt_ok = has_key_takeaways(draft)
    kt_count = key_takeaways_count(draft)
    coverage = citation_coverage(draft, summaries)
    clean_urls, extra_urls = no_hallucinated_urls(draft, summaries)

    # Pass thresholds from the DRAFT_SYSTEM_PROMPT rubric.
    sections_ok = 3 <= sections <= 5
    kt_count_ok = 3 <= kt_count <= 5

    structure_pass = all([exec_ok, sections_ok, kt_ok, kt_count_ok, clean_urls])

    return {
        "has_exec_summary": exec_ok,
        "section_count": sections,
        "section_count_ok": sections_ok,
        "has_key_takeaways": kt_ok,
        "key_takeaways_count": kt_count,
        "key_takeaways_count_ok": kt_count_ok,
        "citation_coverage": round(coverage, 3),
        "no_hallucinated_urls": clean_urls,
        "hallucinated_urls": extra_urls,
        "structure_score": 1.0 if structure_pass else 0.0,
    }
