from __future__ import annotations

import asyncio
from typing import Optional
from typing import Any

import httpx


def _client_kwargs(proxy: str | None, headers: dict[str, str] | None) -> dict[str, Any]:
    base = {
        "headers": headers or {},
        "timeout": httpx.Timeout(30.0, connect=30.0),
        "follow_redirects": True,
    }
    if proxy:
        try:
            return {**base, "proxy": proxy}
        except TypeError:
            return {**base, "proxies": proxy}
    return base


def make_client(*, proxy: str | None, headers: dict[str, str] | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(**_client_kwargs(proxy, headers))


async def fetch_text(
    url: str,
    *,
    proxy: str | None,
    headers: dict[str, str] | None,
    retries: int = 3,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    last_err: Exception | None = None
    for i in range(retries):
        try:
            if client is None:
                async with httpx.AsyncClient(**_client_kwargs(proxy, headers)) as c:
                    r = await c.get(url)
                    r.raise_for_status()
                    return r.text
            r = await client.get(url)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.6 * (i + 1))
    assert last_err is not None
    raise last_err
