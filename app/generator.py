# app/generator.py
import asyncio
from typing import AsyncIterator, Tuple
from .prompts import SYSTEM_MESSAGE
from .ai_client import generate_text_response, stream_text_response

def get_max_tokens_for_path(url_path: str) -> int:
    p = url_path.lower()
    if p in ("robots.txt", "sitemap.xml", "readme.md"):
        return 512
    if p.startswith(("api/", "data/", "json/")) or p.endswith((".json", ".xml", ".txt")):
        return 1024
    if "why-" in p or "how-" in p or "-" in p:
        return 2048
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

def _normalize_mime(first_line: str) -> str:
    fl = (first_line or "").strip()
    if fl.lower().startswith("content-type"):
        fl = fl.split(":", 1)[-1].strip()
    if "/" not in fl:
        fl = "text/plain"
    if "charset" not in fl.lower():
        fl = f"{fl}; charset=utf-8"
    return fl

async def stream_page_for_path(
    url_path: str,
    model: str,
    optional_data: str = "",
    mood_instruction: str = "",
    max_tokens: int = 2048,
) -> Tuple[str, AsyncIterator[str]]:
    """
    Returns (media_type, async iterator of body chunks).
    The first line of the model stream is parsed as the MIME type.
    """
    messages = _build_messages(url_path, optional_data, mood_instruction)
    token_stream = stream_text_response(messages, model=model, max_tokens=max_tokens, temperature=0.7)

    # Buffer until we get the first newline to read the MIME
    mime_holder = {"mime": None}
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    buffer = ""

    async def producer():
        nonlocal buffer
        async for chunk in token_stream:
            if mime_holder["mime"] is None:
                buffer += chunk
                if "\n" in buffer:
                    first_line, rest = buffer.split("\n", 1)
                    mime_holder["mime"] = _normalize_mime(first_line)
                    if rest:
                        await queue.put(rest)
            else:
                await queue.put(chunk)
        # If stream ended and we never saw a newline, treat whole buffer as body
        if mime_holder["mime"] is None:
            mime_holder["mime"] = _normalize_mime("")
            if buffer:
                await queue.put(buffer)
        await queue.put(None)

    async def body_iter():
        # Emit everything placed in the queue by producer
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    # Start producer task
    asyncio.create_task(producer())

    # Wait until MIME discovered
    while mime_holder["mime"] is None:
        await asyncio.sleep(0)

    return mime_holder["mime"], body_iter()
