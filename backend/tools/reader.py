"""URL reader — fetches a page and extracts clean text content."""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

MAX_CONTENT_LENGTH = 8000  # chars — keep context window manageable


async def read_url(url: str) -> str:
    """Fetch a URL and return its text content, cleaned of HTML."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        # 5xx is transient — re-raise so the caller's retry logic can run.
        if status >= 500:
            raise
        return f"[Error fetching {url}: HTTP {status}]"

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    content = "\n".join(lines)

    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n\n[...truncated]"

    return content
