"""HTTP client for the AI Dictionary GitHub Pages API."""

import httpx

from .cache import Cache

API_BASE = "https://donjguido.github.io/ai-dictionary/api/v1"
TIMEOUT = 15.0

cache = Cache(ttl_seconds=3600)


async def _fetch_json(url: str) -> dict | list | None:
    """Fetch JSON from a URL with error handling."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except (httpx.ConnectError, httpx.TimeoutException):
            return None


async def get_all_terms() -> list[dict]:
    """Fetch all terms (cached). Returns list of term dicts."""
    cached = cache.get("terms")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/terms.json")
    if data and "terms" in data:
        cache.set("terms", data["terms"])
        return data["terms"]
    return []


async def get_tags() -> dict:
    """Fetch tag index (cached)."""
    cached = cache.get("tags")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/tags.json")
    if data and "tags" in data:
        cache.set("tags", data)
        return data
    return {}


async def get_frontiers() -> dict:
    """Fetch frontiers (cached)."""
    cached = cache.get("frontiers")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/frontiers.json")
    if data:
        cache.set("frontiers", data)
        return data
    return {}


async def get_meta() -> dict:
    """Fetch metadata (cached)."""
    cached = cache.get("meta")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/meta.json")
    if data:
        cache.set("meta", data)
        return data
    return {}
