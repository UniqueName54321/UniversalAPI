# app/ai_client.py
import asyncio
from openai import AsyncOpenAI

or_api_key = ""
with open(".openrouter_api_key", "r") as f:
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
