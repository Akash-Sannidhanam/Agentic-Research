"""On-disk URL content cache so eval reruns don't hammer the network.

Keyed by SHA256(url). Writes <hash>.txt with the fetched content and a
<hash>.json sidecar with {url, fetched_at} so the cache is inspectable.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..tools import read_url

CACHE_DIR = Path(__file__).parent / "cache"


def _path_for(url: str) -> tuple[Path, Path]:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.txt", CACHE_DIR / f"{digest}.json"


async def get_or_fetch(url: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    txt_path, meta_path = _path_for(url)
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8")

    content = await read_url(url)
    txt_path.write_text(content, encoding="utf-8")
    meta_path.write_text(
        json.dumps({"url": url, "fetched_at": time.time()}, indent=2),
        encoding="utf-8",
    )
    return content
