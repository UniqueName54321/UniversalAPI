"""
Image generation routes for the UniversalAPI application.

This module handles PNG image generation and caching functionality.
"""

from fastapi import FastAPI
from fastapi.responses import Response

from ..generator import generate_png_for_path
from ..state import get_image_cache, set_image_cache_entry
from ..config import IMAGE_CACHE_DIR_STR
import os


def register_routes(app: FastAPI) -> None:
    """Register image generation routes with the FastAPI application."""
    # Image routes are handled within the main catch-all route in content_routes.py
    # This module exists for future image-specific endpoints if needed
    
    pass  # Currently all image logic is in content_routes.py