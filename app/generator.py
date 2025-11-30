from .prompts import SYSTEM_MESSAGE
from .ai_client import generate_text_response


def get_max_tokens_for_path(url_path: str) -> int:
    """
    Rough heuristic for max_tokens based on the URL path.
    """
    p = url_path.lower()

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


async def generate_page_for_path(
    url_path: str,
    model: str,
    optional_data: str = "",
    mood_instruction: str = "",
    max_tokens: int = 2048,
) -> str:
    """
    Build a user-level prompt that works with the cached SYSTEM_MESSAGE
    and call the model via ai_client.generate_text_response.
    """
    mood_instruction = (mood_instruction or "").strip()
    if mood_instruction:
        mood_line = f"MOOD_OVERRIDE: {mood_instruction}"
    else:
        mood_line = "MOOD_OVERRIDE: (none)"

    user_prompt = (
        f"URL_PATH: {url_path}\n"
        f"{mood_line}\n\n"
        f"OPTIONAL_DATA:\n{optional_data or '(none)'}\n"
    )

    messages = [
        SYSTEM_MESSAGE,
        {"role": "user", "content": user_prompt},
    ]

    return await generate_text_response(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=0.7,
    )


def parse_ai_http_response(model_output: str) -> tuple[str, str]:
    """
    Parse the model output into (content_type, body).
    First line: MIME type (or possibly 'Content-Type: ...').
    Rest: body.
    """
    raw_first_line, _, rest = model_output.partition("\n")
    first_line = raw_first_line.strip()

    # Remove "Content-Type:" prefix if the model added it
    if first_line.lower().startswith("content-type"):
        first_line = first_line.split(":", 1)[-1].strip()

    # If it's empty or invalid, default to text/plain
    if ("/" not in first_line) or not first_line:
        first_line = "text/plain"

    content_type = first_line
    body = rest.strip()

    # If content_type lacks a charset, force UTF-8
    if "charset" not in content_type.lower():
        content_type = f"{content_type}; charset=utf-8"

    return content_type, body
