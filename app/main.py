from typing import Dict, Tuple

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from .config import MAIN_MODEL, RANDOM_MODEL
from .generator import generate_page_for_path, get_max_tokens_for_path, parse_ai_http_response
from .memory import remember_page, get_related_memory

app = FastAPI()

# Simple in-memory cache: key -> (content_type, body)
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
    Generate a random fictional topic page using a fake path.
    """
    fake_path = "!!GENERATE_RANDOM_TOPIC!!"

    response_body = await generate_page_for_path(
        url_path=fake_path,
        model=RANDOM_MODEL,
        optional_data="",
        mood_instruction=mood or "",
        max_tokens=3072,
    )

    content_type, body = parse_ai_http_response(response_body)
    # Random topics are not stored in memory (like your original code)
    return Response(content=body, media_type=content_type)


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
async def edit_page_post(
    url_path: str,
    instructions: str = Form(""),
):
    """
    Regenerate the page with edit instructions, then redirect to the updated page.
    """
    optional_data = f"EDIT_INSTRUCTIONS:\n{instructions or '(no specific instructions)'}\n"

    max_tokens = get_max_tokens_for_path(url_path)

    response_body = await generate_page_for_path(
        url_path=url_path,
        model=MAIN_MODEL,
        optional_data=optional_data,
        mood_instruction="",  # mood can be part of EDIT_INSTRUCTIONS if desired
        max_tokens=max_tokens,
    )

    content_type, body = parse_ai_http_response(response_body)

    # Record new version in memory and update cache
    normalized_path = "/" + url_path if not url_path.startswith("/") else url_path
    await remember_page(normalized_path, body, content_type)

    cache_key = url_path + "?"
    cache[cache_key] = (content_type, body)

    return RedirectResponse(url=normalized_path, status_code=302)


@app.api_route("/{url_path:path}", methods=["GET", "POST"])
async def handle_request(
    url_path: str,
    request: Request,
    mood: str | None = None,
):
    """
    Main catch-all route that delegates to the LLM based on URL path.
    Supports GET + POST, cache, and site memory.
    """
    query = request.url.query or ""
    cache_key = f"{url_path}?{query}"

    # Serve from cache for GETs
    if request.method == "GET" and cache_key in cache:
        content_type, body = cache[cache_key]
        return Response(content=body, media_type=content_type)

    # Build OPTIONAL_DATA from memory + POST body
    optional_chunks: list[str] = []

    # 1) Site memory: summaries of related pages
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

    # 2) POST data (if any)
    if request.method == "POST":
        post_body_bytes = await request.body()
        post_body = post_body_bytes.decode("utf-8", "ignore")
        optional_chunks.append(f"POST_DATA:\n{post_body}\n")

    optional_data = "\n\n".join(optional_chunks) if optional_chunks else "(none)"

    max_tokens = get_max_tokens_for_path(url_path)

    response_body = await generate_page_for_path(
        url_path=url_path,
        model=MAIN_MODEL,
        optional_data=optional_data,
        mood_instruction=(mood or "").strip(),
        max_tokens=max_tokens,
    )

    content_type, body = parse_ai_http_response(response_body)

    # Record into memory
    await remember_page(normalized_path, body, content_type)

    resp = Response(content=body, media_type=content_type)

    # Cache GET responses
    if request.method == "GET":
        cache[cache_key] = (content_type, body)

    return resp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=True)
