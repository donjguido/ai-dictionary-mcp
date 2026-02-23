"""In-memory cache with TTL for API responses."""

import time
from typing import Any


class Cache:
    """Simple in-memory cache with time-based expiry."""

    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        """Get a value if it exists and hasn't expired."""
        if key not in self._store:
            return None
        value, timestamp = self._store[key]
        if time.time() - timestamp > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Store a value with the current timestamp."""
        self._store[key] = (value, time.time())

    def clear(self) -> None:
        """Clear all cached data."""
        self._store.clear()
