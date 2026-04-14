"""Web search tool — uses Tavily API for search, with fallback to a simple scraper."""

from __future__ import annotations

import os
import httpx

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"


async def search_web(query: str, max_results: int = 8) -> list[dict[str, str]]:
    """Search the web and return a list of {url, title, snippet}."""
    if not TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY not set — add it to backend/.env")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TAVILY_URL,
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for r in data.get("results", []):
        results.append({
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("content", "")[:300],
        })
    return results
