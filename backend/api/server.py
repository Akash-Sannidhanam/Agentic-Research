"""FastAPI server — REST + WebSocket for real-time agent execution."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..agent import ResearchAgent

app = FastAPI(title="Agentic Research", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active runs keyed by run_id
active_runs: dict[str, ResearchAgent] = {}


class ResearchRequest(BaseModel):
    topic: str


class HumanDecision(BaseModel):
    run_id: str
    decision: str  # "approve" | "reject"
    feedback: str | None = None
    selected_sources: list[int] | None = None  # indices into sources list


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/decide")
async def submit_decision(body: HumanDecision):
    """Submit a human decision for a checkpoint."""
    agent = active_runs.get(body.run_id)
    if not agent:
        return {"error": "Run not found"}

    # If human selected specific sources, update state
    if body.selected_sources is not None:
        agent.state.selected_sources = [
            agent.state.sources[i]
            for i in body.selected_sources
            if i < len(agent.state.sources)
        ]

    agent.submit_human_decision(body.decision, body.feedback)
    return {"status": "ok"}


@app.websocket("/ws/research")
async def websocket_research(ws: WebSocket):
    """WebSocket endpoint — streams agent events in real-time.

    Client sends: {"topic": "..."} to start
    Server sends: trace/checkpoint/draft/done/error events as JSON
    Client sends: {"decision": "approve|reject", "feedback": "..."} at checkpoints
    """
    await ws.accept()

    try:
        # Wait for the initial topic message
        init_msg = await ws.receive_json()
        topic = init_msg.get("topic", "")
        if not topic:
            await ws.send_json({"type": "error", "error": "No topic provided"})
            return

        agent = ResearchAgent(topic=topic)
        active_runs[agent.state.run_id] = agent

        await ws.send_json({"type": "started", "run_id": agent.state.run_id})

        # Run agent in a task so we can listen for human input concurrently
        event_queue: asyncio.Queue[dict] = asyncio.Queue()

        async def run_agent():
            async for event in agent.run():
                await event_queue.put(event)
            await event_queue.put(None)  # sentinel

        agent_task = asyncio.create_task(run_agent())

        while True:
            # Wait for either an agent event or a WebSocket message
            receive_task = asyncio.create_task(ws.receive_json())
            queue_task = asyncio.create_task(event_queue.get())

            done, pending = await asyncio.wait(
                {receive_task, queue_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            for task in done:
                result = task.result()

                if task is queue_task:
                    # Agent event
                    if result is None:
                        # Agent finished
                        return
                    await ws.send_json(result)

                elif task is receive_task:
                    # Human decision from client
                    decision = result.get("decision", "approve")
                    feedback = result.get("feedback")
                    selected = result.get("selected_sources")

                    if selected is not None:
                        agent.state.selected_sources = [
                            agent.state.sources[i]
                            for i in selected
                            if i < len(agent.state.sources)
                        ]

                    agent.submit_human_decision(decision, feedback)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        # Cleanup
        for run_id, a in list(active_runs.items()):
            if a is agent:
                del active_runs[run_id]
                break
