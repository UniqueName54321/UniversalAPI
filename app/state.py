"""
Shared state management for the UniversalAPI application.

This module provides centralized state management for caching and other
shared resources across different route modules.
"""

from typing import Dict, Tuple
import threading

# Thread lock for thread-safe operations on shared state
_state_lock = threading.Lock()

# Content cache: stores generated content by path and query
# Key format: "path?query" or just "path"
# Value format: (content_type, content_body)
cache: Dict[str, Tuple[str, str]] = {}

# Image cache: stores generated PNG images by path
# Key format: path (e.g., "/cat.png")
# Value format: bytes (PNG image data)
image_cache: Dict[str, bytes] = {}


def clear_cache() -> None:
    """Clear all content cache entries."""
    global cache
    with _state_lock:
        cache = {}


def clear_image_cache() -> None:
    """Clear all image cache entries."""
    global image_cache
    with _state_lock:
        image_cache = {}


def clear_all_state() -> None:
    """Clear all cached state (content and images)."""
    clear_cache()
    clear_image_cache()


def get_cache() -> Dict[str, Tuple[str, str]]:
    """Get reference to the content cache dictionary."""
    return cache


def get_image_cache() -> Dict[str, bytes]:
    """Get reference to the image cache dictionary."""
    return image_cache


def set_cache_entry(key: str, value: Tuple[str, str]) -> None:
    """Set a cache entry in a thread-safe manner."""
    with _state_lock:
        cache[key] = value


def set_image_cache_entry(key: str, value: bytes) -> None:
    """Set an image cache entry in a thread-safe manner."""
    with _state_lock:
        image_cache[key] = value


def get_cache_entry(key: str) -> Tuple[str, str] | None:
    """Get a cache entry in a thread-safe manner."""
    with _state_lock:
        return cache.get(key)


def get_image_cache_entry(key: str) -> bytes | None:
    """Get an image cache entry in a thread-safe manner."""
    with _state_lock:
        return image_cache.get(key)