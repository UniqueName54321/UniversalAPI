import openai
import textwrap

or_api_key = ""
with open(".openrouter_api_key", "r") as f:
    or_api_key = f.read().strip()

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=or_api_key
)

def _preview(text: str, limit: int = 400) -> str:
    """Return a shortened one-line preview of text for logging."""
    text = text.replace("\n", "\\n")
    if len(text) > limit:
        return text[:limit] + "... [truncated]"
    return text

def generate_text_response(prompt: str, model: str) -> str:
    # --- pre-call debug info ---
    print("\n[AI] --------------------------------------------------")
    print(f"[AI] Calling model: {model}")
    print(f"[AI] max_tokens: 16384, temperature: 0.7")
    print(f"[AI] Prompt preview:\n[AI]   { _preview(prompt) }")
    print("[AI] Sending request to OpenRouter...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=16384,  # more than enough for most usecases
            temperature=0.7,
        )
    except Exception as e:
        # log the error and re-raise so Flask still surfaces it
        print(f"[AI] ERROR while calling model {model}: {e}")
        raise

    message = response.choices[0].message.content or ""
    resp_preview = _preview(message)

    # --- post-call debug info ---
    print("[AI] Received response from model.")
    print(f"[AI] Response preview:\n[AI]   {resp_preview}")
    print(f"[AI] Response length: {len(message)} characters")

    # token usage (if the backend provides it)
    usage = getattr(response, "usage", None)
    if usage:
        try:
            print(
                f"[AI] Token usage - prompt: {usage.prompt_tokens}, "
                f"completion: {usage.completion_tokens}, "
                f"total: {usage.total_tokens}"
            )
        except Exception:
            # if structure is weird, just dump it
            print(f"[AI] Raw usage object: {usage}")

    print("[AI] --------------------------------------------------\n")

    return message

# IMAGE SUPPORT COMING SOON
