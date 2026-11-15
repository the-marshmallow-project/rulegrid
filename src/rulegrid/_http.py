"""The stdlib HTTP the two default clients need: JSON in, JSON out, off the event loop, retrying transient failures."""

from __future__ import annotations

import asyncio
import http.client
import json
import random
import urllib.error
import urllib.request
from typing import Any

MAX_WAIT = 60
"""The longest wait between attempts, in seconds, whatever the server's `Retry-After` asks."""


class HTTPStatusError(RuntimeError):
    """An HTTP error status, with the wait the server asks before another attempt."""

    def __init__(self, url: str, error: urllib.error.HTTPError):
        super().__init__(f"{error.code} from {url}: {error.read().decode(errors='replace')[:500]}")
        self.code = error.code
        try:
            self.retry_after: float | None = float(error.headers.get("Retry-After", ""))
        except ValueError:  # absent, or an HTTP date
            self.retry_after = None


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
        with e:
            raise HTTPStatusError(url, e) from None


def _transient(error: Exception) -> bool:
    """A timeout, a refused or dropped connection, a rate limit or a server error, which a later attempt may not get."""
    if isinstance(error, HTTPStatusError):
        return error.code in (408, 429) or error.code >= 500
    return isinstance(error, OSError | http.client.HTTPException)


async def call(url: str, api_key: str, payload: Any | None = None, timeout: float = 30, retries: int = 3) -> Any:
    """GET `url`, or POST `payload` to it, with a bearer key, and return the JSON answered.

    A transient failure is retried `retries` times, after about 2, 4, 8... seconds, or as long as the server's
    `Retry-After` asks, up to `MAX_WAIT`. Any other failure, or the last one, raises.
    """
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(_call, url, api_key, payload, timeout)
        except Exception as error:
            if attempt == retries or not _transient(error):
                raise
            wait = error.retry_after if isinstance(error, HTTPStatusError) else None
            await asyncio.sleep(
                min(MAX_WAIT, 2 ** (attempt + 1) * random.uniform(0.75, 1.25) if wait is None else wait)
            )
