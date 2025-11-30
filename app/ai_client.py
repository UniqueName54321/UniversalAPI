# app/ai_client.py
import base64
from openai import AsyncOpenAI
from .config import OPENROUTER_KEY_FILE_STR

import httpx

or_api_key = ""
with open(OPENROUTER_KEY_FILE_STR, "r") as f:
    or_api_key = f.read().strip()

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=or_api_key,
)

def _preview(text: str, limit: int = 400) -> str:
    text = text.replace("\n", "\\n")
    return text[:limit] + ("... [truncated]" if len(text) > limit else "")

async def generate_text_response(messages: list[dict], model: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
    print("\n[AI] ----- non-stream call -----")
    print(f"[AI] model={model} max_tokens={max_tokens} temp={temperature}")
    print(f"[AI] prompt preview: {_preview(next((m['content'] for m in messages if m['role']=='user'),''))}")
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    msg = resp.choices[0].message.content or ""
    print(f"[AI] completion len={len(msg)}")
    return msg

async def stream_text_response(messages: list[dict], model: str, max_tokens: int = 2048, temperature: float = 0.7):
    """
    Async generator that yields content tokens (strings).
    """
    print("\n[AI] ----- stream call -----")
    print(f"[AI] model={model} max_tokens={max_tokens} temp={temperature}")
    print(f"[AI] prompt preview: {_preview(next((m['content'] for m in messages if m['role']=='user'),''))}")

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )

    async for event in stream:
        # OpenAI-compatible streaming events: look for delta.content
        try:
            delta = event.choices[0].delta
            if delta and (tok := (delta.content or "")):
                yield tok
        except Exception:
            # ignore non-token events (e.g., role, tool, etc.)
            continue


async def generate_image(prompt: str, model: str) -> bytes:
    """
    Generate an image via OpenRouter using the chat/completions endpoint.

    Returns raw image bytes (PNG or whatever the model outputs).
    Raises RuntimeError on failure.
    """

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {or_api_key}",
        "Content-Type": "application/json",
        # Optional but nice for attribution on OpenRouter dashboards:
        # "HTTP-Referer": "https://github.com/<your-username>/UniversalAPI",
        # "X-Title": "UniversalAPI",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "modalities": ["image", "text"],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        # Let yourself see the full error body while debugging
        raise RuntimeError(
            f"OpenRouter image API error {r.status_code}: {r.text}"
        )

    result = r.json()

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(f"No choices in OpenRouter image response: {result}")

    message = choices[0].get("message") or {}
    images = message.get("images") or []
    if not images:
        raise RuntimeError(f"No images field in image response: {result}")

    # OpenRouter returns base64 data URLs like "data:image/png;base64,AAAA..."
    data_url = images[0]["image_url"]["url"]
    if not data_url.startswith("data:image"):
        raise RuntimeError(f"Unexpected image_url format: {data_url[:80]}...")

    _, b64_data = data_url.split(",", 1)
    return base64.b64decode(b64_data)