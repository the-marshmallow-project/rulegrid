"""The stdlib HTTP the two default clients need: JSON in, JSON out, off the event loop."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any


def _call(url: str, api_key: str, payload: Any | None, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} from {url}: {e.read().decode(errors='replace')[:500]}") from None


async def call(url: str, api_key: str, payload: Any | None = None, timeout: float = 30) -> Any:
    """GET `url`, or POST `payload` to it, with a bearer key, and return the JSON answered."""
    return await asyncio.to_thread(_call, url, api_key, payload, timeout)
