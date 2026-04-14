"""Basic tests for agent state machine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agent.state import AgentState, Phase, TraceEntry


def test_initial_state():
    state = AgentState(topic="test topic")
    assert state.topic == "test topic"
    assert state.phase == Phase.SEARCH
    assert state.trace == []
    assert state.total_tokens == 0
    assert state.total_cost_usd == 0.0


def test_add_trace():
    state = AgentState(topic="test")
    entry = state.add_trace(
        phase="search",
        action="web_search",
        input="test query",
        output="Found 5 results",
        token_count=100,
        cost_usd=0.001,
        duration_ms=500,
    )
    assert len(state.trace) == 1
    assert state.total_tokens == 100
    assert state.total_cost_usd == 0.001
    assert entry.phase == "search"


def test_to_dict():
    state = AgentState(topic="test")
    state.add_trace(phase="search", action="test", input="x", output="y")
    d = state.to_dict()
    assert d["topic"] == "test"
    assert d["phase"] == "search"
    assert len(d["trace"]) == 1


def test_phase_transitions():
    state = AgentState()
    assert state.phase == Phase.SEARCH
    state.phase = Phase.READ
    assert state.phase == Phase.READ
    state.phase = Phase.WAITING_HUMAN
    assert state.phase == Phase.WAITING_HUMAN


if __name__ == "__main__":
    test_initial_state()
    test_add_trace()
    test_to_dict()
    test_phase_transitions()
    print("All tests passed!")
