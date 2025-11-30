# app/generator.py
import asyncio
from typing import AsyncIterator, Tuple
from .prompts import SYSTEM_MESSAGE
from .ai_client import generate_text_response, stream_text_response

def get_max_tokens_for_path(url_path: str) -> int:
    p = url_path.lower().strip()

    # --- NEW: /stories/* gets massive token budget ---
    if p.startswith("stories/") or p.startswith("/stories/"):
        return 64000  # or 64000 if your model supports it

    # Tiny text-ish or config-like
    if p in ("robots.txt", "sitemap.xml", "readme.md"):
        return 512

    # API / data paths – usually small structured JSON/XML
    if p.startswith(("api/", "data/", "json/")) or p.endswith((".json", ".xml", ".txt")):
        return 1024

    # Question-style or long-slug explanation
    if "why-" in p or "how-" in p or "-" in p:
        return 2048

    # Default: full HTML-ish page with sections
    return 4096


def _build_messages(url_path: str, optional_data: str, mood_instruction: str):
    mood_instruction = (mood_instruction or "").strip()
    mood_line = f"MOOD_OVERRIDE: {mood_instruction}" if mood_instruction else "MOOD_OVERRIDE: (none)"
    user_prompt = (
        f"URL_PATH: {url_path}\n"
        f"{mood_line}\n\n"
        f"OPTIONAL_DATA:\n{optional_data or '(none)'}\n"
    )
    return [SYSTEM_MESSAGE, {"role": "user", "content": user_prompt}]

async def generate_page_for_path(url_path: str, model: str, optional_data: str = "", mood_instruction: str = "", max_tokens: int = 2048) -> str:
    messages = _build_messages(url_path, optional_data, mood_instruction)
    return await generate_text_response(messages, model=model, max_tokens=max_tokens, temperature=0.7)

def _normalize_mime(mime: str) -> str:
    """
    Ensure we always have a valid MIME, with charset for text/* when missing.
    """
    mime = (mime or "").strip()

    if not mime or "/" not in mime:
        mime = "text/html"

    # Add charset for text/* if missing
    lower = mime.lower()
    if mime.startswith("text/") and "charset" not in lower:
        mime = f"{mime}; charset=utf-8"

    return mime


def parse_status_and_mime(first_line: str) -> tuple[int, str]:
    """
    First line can be:
      - "text/html"
      - "200 text/html"
      - "201 application/json; charset=utf-8"
    We:
      - extract an HTTP status (default 200)
      - normalize MIME
      - force 'no 404 ever'
    """
    line = (first_line or "").strip()

    # Defaults
    status = 200
    mime_part = "text/html"

    if line:
        parts = line.split()
        if parts[0].isdigit() and len(parts) >= 2:
            # "<status> <mime...>"
            try:
                status = int(parts[0])
            except ValueError:
                status = 200
            mime_part = " ".join(parts[1:])
        else:
            # Old behavior: just a MIME type
            mime_part = line

    # Sanitize status
    if status < 100 or status > 599:
        status = 200

    # Hard rule: never 404
    if status == 404:
        status = 418  # or 200 if you prefer

    mime = _normalize_mime(mime_part)
    return status, mime



async def stream_page_for_path(
    url_path: str,
    model: str,
    optional_data: str = "",
    mood_instruction: str = "",
    max_tokens: int = 2048,
) -> Tuple[int, str, AsyncIterator[str]]:
    messages = _build_messages(url_path, optional_data, mood_instruction)
    token_stream = stream_text_response(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=0.7,
    )

    status_holder = {"status": 200}
    mime_holder = {"mime": None}
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    buffer = ""

    async def producer():
        nonlocal buffer
        try:
            async for chunk in token_stream:
                if mime_holder["mime"] is None:
                    buffer += chunk
                    if "\n" in buffer:
                        first_line, rest = buffer.split("\n", 1)
                        status, mime = parse_status_and_mime(first_line)
                        status_holder["status"] = status
                        mime_holder["mime"] = mime
                        if rest:
                            await queue.put(rest)
                else:
                    await queue.put(chunk)

            # If the stream ends before newline, treat all as body
            if mime_holder["mime"] is None:
                status, mime = parse_status_and_mime("")
                status_holder["status"] = status
                mime_holder["mime"] = mime
                if buffer:
                    await queue.put(buffer)
        finally:
            await queue.put(None)

    async def body_iter():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    asyncio.create_task(producer())

    # Wait until MIME is discovered
    while mime_holder["mime"] is None:
        await asyncio.sleep(0)

    return status_holder["status"], mime_holder["mime"], body_iter()
