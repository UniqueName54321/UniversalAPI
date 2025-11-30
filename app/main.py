import asyncio
from typing import Dict, Tuple
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse, StreamingResponse

from .config import MAIN_MODEL, RANDOM_MODEL
from .generator import generate_page_for_path, get_max_tokens_for_path, stream_page_for_path
from .memory import remember_page, get_related_memory

app = FastAPI()
cache: Dict[str, Tuple[str, str]] = {}


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

  <h2>How to Use It</h2>
  <p>Just change the path in the address bar. For example, try:</p>
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

  <p><strong>TL;DR:</strong> Mess with the path. The AI will improvise, remember, and let you tweak.</p>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(HOME_HTML)


@app.get("/random")
async def random_page(mood: str | None = None):
    """
    Stream a random fictional topic page.
    """
    media_type, body_stream = await stream_page_for_path(
        url_path="!!GENERATE_RANDOM_TOPIC!!",
        model=RANDOM_MODEL,
        optional_data="",
        mood_instruction=mood or "",
        max_tokens=3072,
    )

    # No memory for /random per your original rule
    async def passthrough():
        async for chunk in body_stream:
            yield chunk

    return StreamingResponse(passthrough(), media_type=media_type)

@app.get("/edit/{url_path:path}", response_class=HTMLResponse)
async def edit_page_get(url_path: str) -> HTMLResponse:
    """
    Simple 'edit this page' interface (GET).
    """
    display_path = "/" + url_path if not url_path.startswith("/") else url_path

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Edit {display_path}</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      max-width: 800px;
      margin: auto;
      padding: 2rem;
      line-height: 1.6;
    }}
    textarea {{
      width: 100%;
      height: 200px;
      font-family: inherit;
      font-size: 1rem;
    }}
    label {{
      font-weight: bold;
    }}
    .actions {{
      margin-top: 1rem;
    }}
    button {{
      padding: 0.5rem 1rem;
      font-size: 1rem;
    }}
  </style>
</head>
<body>
  <h1>Edit {display_path}</h1>
  <p>Describe how you want this page changed. The AI will regenerate it from scratch, keeping the URL's topic in mind.</p>
  <form method="POST">
    <label for="instructions">Edit instructions:</label><br>
    <textarea id="instructions" name="instructions" placeholder="e.g. Make it shorter, add a FAQ section, keep it friendly but more formal."></textarea>
    <div class="actions">
      <button type="submit">Regenerate Page</button>
      <a href="{display_path}" style="margin-left: 1rem;">Cancel</a>
    </div>
  </form>
</body>
</html>
"""
    return HTMLResponse(html)


@app.post("/edit/{url_path:path}")
async def edit_page_post(url_path: str, instructions: str = Form("")):
    """
    Regenerate content, then redirect. (Non-stream is fine here since we redirect.)
    We DEFER summarization.
    """
    optional_data = f"EDIT_INSTRUCTIONS:\n{instructions or '(no specific instructions)'}\n"
    max_tokens = get_max_tokens_for_path(url_path)

    response_body = await generate_page_for_path(
        url_path=url_path,
        model=MAIN_MODEL,
        optional_data=optional_data,
        mood_instruction="",
        max_tokens=max_tokens,
    )

    # Parse first line for media type, then body
    raw_first, _, rest = response_body.partition("\n")
    media_type = raw_first.strip()
    if media_type.lower().startswith("content-type"):
        media_type = media_type.split(":", 1)[-1].strip()
    if "/" not in media_type:
        media_type = "text/plain"
    if "charset" not in media_type.lower():
        media_type = f"{media_type}; charset=utf-8"
    full_body = rest.strip()

    normalized_path = "/" + url_path if not url_path.startswith("/") else url_path
    cache_key = url_path + "?"

    # Cache now
    cache[cache_key] = (media_type, full_body)

    # Defer memory work (summarization + links)
    asyncio.create_task(remember_page(normalized_path, full_body, media_type))

    return RedirectResponse(url=normalized_path, status_code=302)


@app.api_route("/{url_path:path}", methods=["GET", "POST"])
async def handle_request(url_path: str, request: Request, mood: str | None = None):
    query = request.url.query or ""
    cache_key = f"{url_path}?{query}"

    # ----- CACHE HIT -----
    if request.method == "GET" and cache_key in cache:
        content_type, body = cache[cache_key]
        return Response(content=body, media_type=content_type)

    # ----- OPTIONAL DATA BUILD -----
    optional_chunks: list[str] = []
    normalized_path = "/" + url_path if not url_path.startswith("/") else url_path

    related = get_related_memory(normalized_path)
    if related:
        lines = ["SITE_MEMORY:", "Here are summaries of related pages on this site:"]
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

    max_tokens = get_max_tokens_for_path(url_path)

    # ----- STREAM FROM MODEL -----
    media_type, body_stream = await stream_page_for_path(
        url_path=url_path,
        model=MAIN_MODEL,
        optional_data=optional_data,
        mood_instruction=(mood or "").strip(),
        max_tokens=max_tokens,
    )

    # ----- RULE: DO NOT STREAM JSON OR XML -----
    if media_type.startswith("application/json") or media_type.endswith("json") \
       or media_type.endswith("xml") or media_type.startswith("text/xml") \
       or "xml" in media_type:

        # Fully consume the stream
        parts = []
        async for chunk in body_stream:
            parts.append(chunk)
        full_body = "".join(parts)

        # async memory save
        asyncio.create_task(remember_page(normalized_path, full_body, media_type))

        if request.method == "GET":
            cache[cache_key] = (media_type, full_body)

        return Response(full_body, media_type=media_type)

    # ----- OTHERWISE: STREAM LIKE A GIGACHAD -----
    async def tee():
        parts: list[str] = []
        async for chunk in body_stream:
            parts.append(chunk)
            yield chunk

        full_body = "".join(parts)

        asyncio.create_task(remember_page(normalized_path, full_body, media_type))

        if request.method == "GET":
            cache[cache_key] = (media_type, full_body)

    return StreamingResponse(tee(), media_type=media_type)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=True)
