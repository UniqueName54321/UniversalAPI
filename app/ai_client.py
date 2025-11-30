import asyncio
import openai

or_api_key = ""
with open(".openrouter_api_key", "r") as f:
    or_api_key = f.read().strip()

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=or_api_key,
)


def _preview(text: str, limit: int = 400) -> str:
    """Return a shortened one-line preview of text for logging."""
    text = text.replace("\n", "\\n")
    if len(text) > limit:
        return text[:limit] + "... [truncated]"
    return text


async def generate_text_response(
    messages: list[dict],
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str:
    """
    Async wrapper around the synchronous OpenRouter client.
    Uses a threadpool so it plays nice with FastAPI's event loop.
    """

    # --- pre-call debug info ---
    print("\n[AI] --------------------------------------------------")
    print(f"[AI] Calling model: {model}")
    print(f"[AI] max_tokens: {max_tokens}, temperature: {temperature}")

    user_contents = [m.get("content", "") for m in messages if m.get("role") == "user"]
    last_user_content = user_contents[-1] if user_contents else ""
    print(f"[AI] Prompt preview (last user message):\n[AI]   { _preview(last_user_content) }")
    print("[AI] Sending request to OpenRouter...")

    loop = asyncio.get_event_loop()

    def _call_sync():
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            print(f"[AI] ERROR while calling model {model}: {e}")
            raise

    response = await loop.run_in_executor(None, _call_sync)

    message = response.choices[0].message.content or ""
    resp_preview = _preview(message)

    # --- post-call debug info ---
    print("[AI] Received response from model.")
    print(f"[AI] Response preview:\n[AI]   {resp_preview}")
    print(f"[AI] Response length: {len(message)} characters")

    usage = getattr(response, "usage", None)
    if usage:
        try:
            print(
                f"[AI] Token usage - prompt: {usage.prompt_tokens}, "
                f"completion: {usage.completion_tokens}, "
                f"total: {usage.total_tokens}"
            )
        except Exception:
            print(f"[AI] Raw usage object: {usage}")

    print("[AI] --------------------------------------------------\n")

    return message
