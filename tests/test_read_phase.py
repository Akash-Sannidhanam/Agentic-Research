"""Tests for the parallel read phase."""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Anthropic client construction reads ANTHROPIC_API_KEY at __init__ time; provide a dummy.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

from backend.agent import core as core_module
from backend.agent.core import ResearchAgent


FAKE_SOURCES = [
    {"url": f"https://example.com/{i}", "title": f"Source {i}", "snippet": ""}
    for i in range(5)
]


def _make_agent() -> ResearchAgent:
    agent = ResearchAgent(topic="test")
    # Each source dict needs to be unique per agent, since fetch_one mutates it.
    agent.state.selected_sources = [dict(s) for s in FAKE_SOURCES]
    return agent


async def _drive_read(agent: ResearchAgent) -> list[dict]:
    return [event async for event in agent._phase_read()]


def test_read_phase_runs_in_parallel(monkeypatch_target=core_module):
    """5 sources × 0.3s each must finish in well under the 1.5s sequential bound."""
    PER_FETCH = 0.3

    async def slow_stub(url: str) -> str:
        await asyncio.sleep(PER_FETCH)
        return f"content for {url}"

    original = monkeypatch_target.read_url
    monkeypatch_target.read_url = slow_stub
    try:
        agent = _make_agent()
        t0 = time.time()
        events = asyncio.run(_drive_read(agent))
        elapsed = time.time() - t0
    finally:
        monkeypatch_target.read_url = original

    # Sequential would be 5 × 0.3 = 1.5s. Parallel should land near 0.3s.
    assert elapsed < 1.0, f"expected parallel speedup, took {elapsed:.2f}s"
    assert len(events) == 5
    assert all(e["type"] == "trace" for e in events)
    assert len(agent.state.trace) == 5
    assert all(t.phase == "read" for t in agent.state.trace)
    for source in agent.state.selected_sources:
        assert source["content"] == f"content for {source['url']}"


def test_read_phase_isolates_failures(monkeypatch_target=core_module):
    """One URL failing must not abort the others; failed source carries an error string."""

    async def stub(url: str) -> str:
        if url == "https://example.com/2":
            raise RuntimeError("boom")
        await asyncio.sleep(0.05)
        return f"content for {url}"

    original = monkeypatch_target.read_url
    monkeypatch_target.read_url = stub
    try:
        agent = _make_agent()
        agent._max_retries = 0  # fail fast — don't burn 3s on backoff for the failing URL
        events = asyncio.run(_drive_read(agent))
    finally:
        monkeypatch_target.read_url = original

    assert len(events) == 5
    by_url = {s["url"]: s for s in agent.state.selected_sources}
    assert by_url["https://example.com/2"]["content"].startswith("[Error fetching ")
    for url, source in by_url.items():
        if url == "https://example.com/2":
            continue
        assert source["content"] == f"content for {url}"


if __name__ == "__main__":
    test_read_phase_runs_in_parallel()
    test_read_phase_isolates_failures()
    print("All tests passed!")
