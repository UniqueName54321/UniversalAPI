"""
Content generation routes for the UniversalAPI application.

This module handles core content generation functionality including:
- Home page
- Random content generation
- Main catch-all route for dynamic content generation
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from typing import AsyncIterator

from ..generator import (
    generate_page_for_path,
    get_max_tokens_for_path,
    stream_page_for_path,
    parse_status_and_mime,
    generate_png_for_path,
)
from ..memory import remember_page, get_related_memory
from ..state import get_cache, get_image_cache, set_cache_entry, set_image_cache_entry
from ..config import IMAGE_CACHE_DIR_STR, RANDOM_MODEL
import os
import asyncio


HOME_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Universal AI Router</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      max-width: 800px;
      margin: auto;
      padding: 2rem;
      line-height: 1.6;
    }
    nav {
      margin-bottom: 1.5rem;
    }
    nav a {
      margin-right: 1rem;
      text-decoration: none;
      color: #0645AD;
    }
    nav a:hover {
      text-decoration: underline;
    }
    code {
      background: #f4f4f4;
      padding: 0.15rem 0.35rem;
      border-radius: 3px;
      font-size: 0.95em;
    }
    ul.examples li {
      margin-bottom: 0.4rem;
    }
    .hero-box {
      margin: 1.5rem 0;
      padding: 1rem 1.25rem;
      border-radius: 8px;
      background: #f7f9ff;
      border: 1px solid #dde4ff;
    }
    .search-input {
      width: 100%;
      padding: 0.6rem 0.75rem;
      font-size: 1rem;
      border-radius: 6px;
      border: 1px solid #ccc;
      box-sizing: border-box;
    }
    .search-button {
      margin-top: 0.6rem;
      padding: 0.5rem 1rem;
      font-size: 0.95rem;
      border-radius: 6px;
      border: none;
      background: #0645AD;
      color: white;
      cursor: pointer;
    }
    .search-button:hover {
      background: #043577;
    }
    .hint {
      font-size: 0.9rem;
      color: #555;
      margin-top: 0.4rem;
    }
  </style>
</head>
<body>
  <nav>
    <a href="/">Home</a>
    <a href="/about">About</a>
    <a href="/help">Help</a>
    <a href="/contact">Contact</a>
  </nav>

  <h1>Universal AI Router</h1>
  <p>
    This server uses an AI model to dynamically generate content based on the URL path.
    Every path behaves like its own tiny, auto-generated page, API, or explanation.
  </p>

  <div class="hero-box">
    <form action="/go" method="get">
      <label for="q"><strong>Ask for anything:</strong></label><br>
      <input
        id="q"
        name="q"
        class="search-input"
        type="text"
        placeholder="e.g. "explain black holes like I'm 10", "T-rated sci-fi story about time loops", "cute golden retriever.png"">
      <button type="submit" class="search-button">Send to AI</button>
      <p class="hint">
        We'll turn this into a smart URL behind the scenes. Power users can still edit the address bar manually.
      </p>
    </form>
  </div>

  <h2>How to Use It</h2>
  <p>You can either type in the box above, or mess with the path yourself in the address bar. For example, try:</p>
  <ul class="examples">
    <li><code>/cat</code> – explanation of a concept or thing.</li>
    <li><code>/why-is-the-sky-blue</code> – answer to a question.</li>
    <li><code>/about</code>, <code>/help</code>, <code>/contact</code> – normal-looking pages.</li>
    <li><code>/api/example</code> – JSON-style API responses.</li>
    <li><code>/edit/cat</code> – regenerate an existing page with new instructions.</li>
  </ul>

  <p>
    Behind the scenes, pages are remembered and lightly summarized so related URLs
    can reference each other's knowledge.
  </p>

  <p><strong>TL;DR:</strong> Type what you want, or mess with the path. The AI will improvise, remember, and let you tweak.</p>
</body>
</html>
"""


def register_routes(app: FastAPI) -> None:
    """Register content generation routes with the FastAPI application."""

    @app.get("/", response_class=HTMLResponse)
    async def home() -> HTMLResponse:
        """Serve the home page."""
        return HTMLResponse(HOME_HTML)

    @app.get("/random")
    async def random_page(mood: str | None = None):
        """Stream a random fictional topic page."""
        status_code, media_type, body_stream = await stream_page_for_path(
            url_path="!!GENERATE_RANDOM_TOPIC!!",
            model=RANDOM_MODEL,
            optional_data="",
            mood_instruction=mood or "",
            max_tokens=3072,
        )

        async def passthrough():
            async for chunk in body_stream:
                yield chunk

        return StreamingResponse(
            passthrough(), media_type=media_type, status_code=status_code
        )

    @app.api_route("/{url_path:path}", methods=["GET", "POST"])
    async def handle_request(url_path: str, request: Request, mood: str | None = None):
        # Block favicon.ico to save tokens
        if url_path == "favicon.ico":
            return Response(status_code=504)
        """Handle dynamic content generation for any path."""
        cache = get_cache()
        image_cache = get_image_cache()

        query = request.url.query or ""
        cache_key = f"{url_path}?{query}"
        normalized_path = "/" + url_path if not url_path.startswith("/") else url_path

        # ----- CACHE HIT -----
        if request.method == "GET" and cache_key in cache:
            content_type, body = cache[cache_key]
            return Response(content=body, media_type=content_type)

        # ----- OPTIONAL DATA BUILD -----
        optional_chunks: list[str] = []

        related = get_related_memory(normalized_path)
        if related:
            lines = [
                "SITE_MEMORY:",
                "Here are summaries of related pages on this site:",
            ]
            for path, entry in related:
                lines.append(f"\n--- {path} ---")
                summary = entry.get("summary", "")
                if summary:
                    lines.append(summary[:600])
            optional_chunks.append("\n".join(lines))

        if request.method == "POST":
            post_body = (await request.body()).decode("utf-8", "ignore")
            optional_chunks.append(f"POST_DATA:\n{post_body}\n")

        optional_data = "\n\n".join(optional_chunks) if optional_chunks else "(none)"

        # ==============================
        #  SPECIAL CASE: PNG GENERATION
        # ==============================
        if url_path.lower().endswith(".png"):
            disk_path = os.path.join(IMAGE_CACHE_DIR_STR, url_path.replace("/", "_"))

            # RAM cache
            if url_path in image_cache:
                return Response(
                    content=image_cache[url_path],
                    media_type="image/png",
                    status_code=200,
                )

            # Disk cache
            if os.path.exists(disk_path):
                with open(disk_path, "rb") as f:
                    img_bytes = f.read()
                set_image_cache_entry(url_path, img_bytes)
                return Response(
                    content=img_bytes, media_type="image/png", status_code=200
                )

            # Generate fresh image via RANDOM_MODEL → IMAGE_GEN_MODEL
            image_bytes, status_code = await generate_png_for_path(
                url_path=normalized_path,
                optional_data=optional_data,
                mood_instruction=(mood or "").strip(),
            )

            if status_code == 200 and image_bytes:
                set_image_cache_entry(url_path, image_bytes)
                tmp = disk_path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(image_bytes)
                os.replace(tmp, disk_path)

            return Response(
                content=image_bytes, media_type="image/png", status_code=status_code
            )

        # ----- NORMAL TEXT/HTML/JSON GENERATION PATH -----
        max_tokens = get_max_tokens_for_path(url_path)

        # ----- STREAM FROM MODEL -----
        status_code, media_type, body_stream = await stream_page_for_path(
            url_path=url_path,
            model="openrouter/auto",  # MAIN_MODEL
            optional_data=optional_data,
            mood_instruction=(mood or "").strip(),
            max_tokens=max_tokens,
        )

        # ----- RULE: DO NOT STREAM JSON OR XML -----
        if (
            media_type.startswith("application/json")
            or media_type.endswith("json")
            or media_type.endswith("xml")
            or media_type.startswith("text/xml")
            or "xml" in media_type
        ):
            parts = []
            async for chunk in body_stream:
                parts.append(chunk)
            full_body = "".join(parts)

            asyncio.create_task(remember_page(normalized_path, full_body, media_type))

            if request.method == "GET":
                set_cache_entry(cache_key, (media_type, full_body))

            return Response(full_body, media_type=media_type, status_code=status_code)

        # ----- OTHERWISE: STREAM LIKE A GIGACHAD -----
        async def tee():
            parts: list[str] = []
            async for chunk in body_stream:
                parts.append(chunk)
                yield chunk

            full_body = "".join(parts)

            asyncio.create_task(remember_page(normalized_path, full_body, media_type))

            if request.method == "GET":
                set_cache_entry(cache_key, (media_type, full_body))

        return StreamingResponse(tee(), media_type=media_type, status_code=status_code)
