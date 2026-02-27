# app/generator.py
import asyncio
import re
from typing import AsyncIterator, Tuple

from .config import RANDOM_MODEL, IMAGE_GEN_MODEL

from .prompts import IMAGE_PROMPT_SYSTEM, SYSTEM_MESSAGE
from .ai_client import generate_image, generate_text_response, stream_text_response


def get_max_tokens_for_path(url_path: str) -> int:
    p = url_path.lower().strip()

    # --- NEW: /stories/* gets massive token budget ---
    if p.startswith("stories/") or p.startswith("/stories/"):
        return 64000  # or 64000 if your model supports it

    # Tiny text-ish or config-like
    if p in ("robots.txt", "sitemap.xml", "readme.md"):
        return 512

    # API / data paths – usually structured JSON/XML, but not artificially capped
    if p.startswith(("api/", "data/", "json/")) or p.endswith(
        (".json", ".xml", ".txt")
    ):
        return 8192  # Much larger for proper API responses

    # Question-style or long-slug explanation
    if "why-" in p or "how-" in p or "-" in p:
        return 8192  # Larger for comprehensive explanations

    # Default: full HTML-ish page with sections
    return 16384  # Much larger for comprehensive pages


def _build_messages(url_path: str, optional_data: str, mood_instruction: str):
    mood_instruction = (mood_instruction or "").strip()
    mood_line = (
        f"MOOD_OVERRIDE: {mood_instruction}"
        if mood_instruction
        else "MOOD_OVERRIDE: (none)"
    )
    user_prompt = (
        f"URL_PATH: {url_path}\n"
        f"{mood_line}\n\n"
        f"OPTIONAL_DATA:\n{optional_data or '(none)'}\n"
    )
    return [SYSTEM_MESSAGE, {"role": "user", "content": user_prompt}]


async def generate_page_for_path(
    url_path: str,
    model: str,
    optional_data: str = "",
    mood_instruction: str = "",
    max_tokens: int = 2048,
) -> str:
    messages = _build_messages(url_path, optional_data, mood_instruction)
    return await generate_text_response(
        messages, model=model, max_tokens=max_tokens, temperature=0.7
    )


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


def _path_to_image_concept(url_path: str) -> str:
    """
    Convert something like '/stories/space-wizard.png' -> 'space wizard'
    or '/dragon/holding-latte.png' -> 'dragon holding latte'
    """
    # strip leading slash and extension
    path = url_path.lstrip("/")
    if path.lower().endswith(".png"):
        path = path[:-4]

    # take last segment as main topic
    segment = path.split("/")[-1]
    segment = segment.replace("-", " ").replace("_", " ")
    segment = re.sub(r"\s+", " ", segment).strip()
    return segment or "abstract scene"


async def generate_png_for_path(
    url_path: str,
    optional_data: str,
    mood_instruction: str | None = None,
) -> tuple[bytes, int]:
    """
    Returns (image_bytes, status_code).
    Status 200 on success, 500 or 400-ish on failure.
    """

    concept = _path_to_image_concept(url_path)

    # You can get fancy and let optional_data influence the prompt
    # e.g. SITE_MEMORY: previous pages, POST_DATA, etc.
    # For now we just use it lightly.
    base_prompt = (
        f"High quality illustration of: {concept}. "
        "Crisp details, visually appealing, centered composition."
    )

    if mood_instruction:
        base_prompt += f" Style mood: {mood_instruction}."

    # If SITE_MEMORY contains something juicy about this path, you could parse it
    # from optional_data, but that's extra credit.

    try:
        image_bytes = await generate_image(
            prompt=base_prompt,
            model=IMAGE_GEN_MODEL,
        )
        if not image_bytes:
            return b"", 500
        return image_bytes, 200
    except Exception as e:
        # log error somewhere if you want
        print(f"[IMAGE] Error generating PNG for {url_path}: {e}")
        return b"", 500


async def build_image_prompt_for_path(
    url_path: str,
    optional_data: str,
    mood_instruction: str | None = None,
) -> str:
    """
    Use RANDOM_MODEL to turn the raw path + site memory into a proper image prompt.
    """

    # We'll give the model enough context to be smart, but keep it cheap.
    mood_line = mood_instruction.strip() if mood_instruction else "(none)"

    user_content = (
        f"URL_PATH: {url_path}\nMOOD: {mood_line}\n\nSITE_CONTEXT:\n{optional_data}"
    )

    messages = [
        {"role": "system", "content": IMAGE_PROMPT_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    # Keep this cheap + deterministic-ish
    prompt = await generate_text_response(
        messages=messages,
        model=RANDOM_MODEL,
        max_tokens=128,
        temperature=0.2,
    )

    return prompt.strip()


async def generate_png_for_path(
    url_path: str,
    optional_data: str,
    mood_instruction: str | None = None,
) -> tuple[bytes, int]:
    """
    1) Use RANDOM_MODEL to infer the best image prompt.
    2) Use IMAGE_GEN_MODEL to generate the PNG bytes.
    3) Return (bytes, status_code).
    """

    print("[DEBUG] Using IMAGE_GEN_MODEL:", IMAGE_GEN_MODEL)

    try:
        image_prompt = await build_image_prompt_for_path(
            url_path=url_path,
            optional_data=optional_data,
            mood_instruction=mood_instruction,
        )

        if not image_prompt:
            print(f"[IMAGE] Empty prompt for {url_path}")
            return b"", 500

        # Call your image model via ai_client
        img_bytes = await generate_image(
            prompt=image_prompt,
            model=IMAGE_GEN_MODEL,
        )

        if not img_bytes:
            print(f"[IMAGE] No bytes returned for {url_path}")
            return b"", 500

        return img_bytes, 200

    except Exception as e:
        print(f"[IMAGE] Error generating PNG for {url_path}: {e}")
        return b"", 500
