"""HTTP client for the AI Dictionary GitHub Pages API."""

import asyncio

import httpx

from .cache import Cache

API_BASE = "https://phenomenai.org/api/v1"
TIMEOUT = 15.0
MAX_RETRIES = 3

cache = Cache(ttl_seconds=3600)


async def _fetch_json(url: str) -> dict | list | None:
    """Fetch JSON from a URL with error handling and 429 retry."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return None
                raise
            except (httpx.ConnectError, httpx.TimeoutException):
                return None
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


async def get_citation(slug: str) -> dict | None:
    """Fetch citation data for a single term (cached)."""
    cache_key = f"cite:{slug}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/cite/{slug}.json")
    if data:
        cache.set(cache_key, data)
        return data
    return None


async def get_census() -> dict:
    """Fetch bot census data (cached)."""
    cached = cache.get("census")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/census.json")
    if data:
        cache.set("census", data)
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


async def get_interest() -> dict:
    """Fetch interest/composite scores (cached)."""
    cached = cache.get("interest")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/interest.json")
    if data:
        cache.set("interest", data)
        return data
    return {}


async def get_changelog() -> list[dict]:
    """Fetch changelog entries (cached)."""
    cached = cache.get("changelog")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/changelog.json")
    if data and "entries" in data:
        cache.set("changelog", data)
        return data
    return {}


async def get_discussions() -> dict:
    """Fetch discussions data (cached)."""
    cached = cache.get("discussions")
    if cached is not None:
        return cached

    data = await _fetch_json(f"{API_BASE}/discussions.json")
    if data:
        cache.set("discussions", data)
        return data
    return {}
