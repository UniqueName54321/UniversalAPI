"""
API routes for the UniversalAPI application.

This module handles API endpoints and administrative functionality including:
- LLM endpoint for direct model access
- Reset endpoints (hard, soft, lobotomy)
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response
from typing import Dict

from ..ai_client import generate_text_response
from ..memory import clear_page_memory
from ..state import clear_cache, clear_image_cache
from ..config import MAIN_MODEL, PAGE_MEMORY_FILE_STR, OPENROUTER_KEY_FILE_STR, IMAGE_CACHE_DIR_STR
import shutil
from pathlib import Path


def safe_delete_file(path: Path) -> None:
    """Safely delete a file."""
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception as e:
        print(f"Failed to delete file {path}: {e}")


def safe_delete_dir(path: Path) -> None:
    """Safely delete a directory."""
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
    except Exception as e:
        print(f"Failed to delete directory {path}: {e}")


def register_routes(app: FastAPI) -> None:
    """Register API routes with the FastAPI application."""
    
    @app.api_route("/api/llm/", methods=["GET", "POST"])
    async def llm_endpoint(request: Request):
        """
        Simple LLM endpoint that takes 'prompt' and optional 'model' query/form parameters.
        Returns raw text response from the model.
        """
        if request.method == "GET":
            prompt = request.query_params.get("prompt", "")
            model = request.query_params.get("model", MAIN_MODEL)
            model = MAIN_MODEL  # bodged line of code to make sure model param is ignored
        else:
            form = await request.form()
            prompt = form.get("prompt", "")
            model = form.get("model", MAIN_MODEL)
            model = MAIN_MODEL  # bodged line of code to make sure model param is ignored

        if not prompt:
            return Response("Error: 'prompt' parameter is required.", status_code=400)

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ]

        response_text = await generate_text_response(
            messages=messages,
            model=model,
            max_tokens=1024,
            temperature=0.7,
        )

        return Response(content=response_text, media_type="text/plain; charset=utf-8", status_code=200)

    @app.get("/api/hard-reset")
    @app.get("/api/hard-reset/")
    async def hard_reset_endpoint():
        """
        HARD RESET:
        - Deletes .page_memory.json
        - Deletes image cache directory
        - Deletes .openrouter_api_key
        Fully resets server memory/cache and API key.
        """
        clear_page_memory()  # wipe in-memory dict first
        safe_delete_file(Path(PAGE_MEMORY_FILE_STR))
        safe_delete_dir(Path(IMAGE_CACHE_DIR_STR))
        safe_delete_file(Path(OPENROUTER_KEY_FILE_STR))

        return Response(
            content="Hard reset complete: page memory, image cache, and OpenRouter API key deleted.",
            media_type="text/plain; charset=utf-8",
            status_code=200,
        )

    @app.get("/api/soft-reset")
    @app.get("/api/soft-reset/")
    async def soft_reset_endpoint():
        """
        SOFT RESET:
        - Deletes .page_memory.json
        - Deletes image cache directory
        - Keeps .openrouter_api_key
        Resets content memory + image cache, but keeps API key configured.
        """
        clear_page_memory()  # wipe in-memory dict first
        safe_delete_file(Path(PAGE_MEMORY_FILE_STR))
        safe_delete_dir(Path(IMAGE_CACHE_DIR_STR))

        return Response(
            content="Soft reset complete: page memory and image cache deleted, API key preserved.",
            media_type="text/plain; charset=utf-8",
            status_code=200,
        )

    @app.get("/api/lobotomy")
    @app.get("/api/lobotomy/")
    async def lobotomy_endpoint():
        """
        LOBOTOMY:
        - Deletes only .page_memory.json
        - Keeps image cache and API key
        Resets site memory while retaining cached images and configuration.
        """
        clear_page_memory()  # wipe in-memory dict first
        safe_delete_file(Path(PAGE_MEMORY_FILE_STR))

        return Response(
            content="Lobotomy complete: page memory deleted, image cache and API key preserved.",
            media_type="text/plain; charset=utf-8",
            status_code=200,
        )