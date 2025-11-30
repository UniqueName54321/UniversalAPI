import asyncio
import os
import shutil
from pathlib import Path
from typing import Dict, Tuple
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse, StreamingResponse

from app.ai_client import generate_text_response

from .config import IMAGE_CACHE_DIR_STR, MAIN_MODEL, RANDOM_MODEL
from .config import MEMORY_FILE_STR as PAGE_MEMORY_FILE_STR
from .config import OPENROUTER_KEY_FILE_STR

PAGE_MEMORY_FILE = Path(PAGE_MEMORY_FILE_STR)
OPENROUTER_KEY_FILE = Path(OPENROUTER_KEY_FILE_STR)
IMAGE_CACHE_DIR = Path(IMAGE_CACHE_DIR_STR)

from .generator import generate_page_for_path, get_max_tokens_for_path, stream_page_for_path, parse_status_and_mime, generate_png_for_path
from .memory import remember_page, get_related_memory
from .memory import clear_page_memory  # NEW

app = FastAPI()
cache: Dict[str, Tuple[str, str]] = {}
image_cache: dict[str, bytes] = {}


def safe_delete_file(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception as e:
        # You can log this if you want
        print(f"Failed to delete file {path}: {e}")


def safe_delete_dir(path: Path) -> None:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
    except Exception as e:
        # You can log this if you want
        print(f"Failed to delete directory {path}: {e}")

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
    status_code, media_type, body_stream = await stream_page_for_path(
        url_path="!!GENERATE_RANDOM_TOPIC!!",
        model=RANDOM_MODEL,
        optional_data="",
        mood_instruction=mood or "",
        max_tokens=3072,
    )

    async def passthrough():
        async for chunk in body_stream:
            yield chunk

    return StreamingResponse(passthrough(), media_type=media_type, status_code=status_code)


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
    status_code, media_type = parse_status_and_mime(raw_first)
    full_body = rest.strip()

    normalized_path = "/" + url_path if not url_path.startswith("/") else url_path
    cache_key = url_path + "?"

    # Cache now
    cache[cache_key] = (media_type, full_body)

    # Defer memory work (summarization + links)
    asyncio.create_task(remember_page(normalized_path, full_body, media_type))

    return RedirectResponse(url=normalized_path, status_code=302)

@app.api_route("/api/llm/", methods=["GET", "POST"])
async def llm_endpoint(request: Request):
    """
    Simple LLM endpoint that takes 'prompt' and optional 'model' query/form parameters.
    Returns raw text response from the model.
    """
    if request.method == "GET":
        prompt = request.query_params.get("prompt", "")
        model = request.query_params.get("model", MAIN_MODEL)
        model = MAIN_MODEL # bodged line of code to make sure model param is ignored
    else:
        form = await request.form()
        prompt = form.get("prompt", "")
        model = form.get("model", MAIN_MODEL)
        model = MAIN_MODEL # bodged line of code to make sure model param is ignored

    if not prompt:
        return Response("Error: 'prompt' parameter is required.", status_code=400)

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt},
    ]

    response_text = await generate_text_response(
        messages=messages,
        model=model,
        max_tokens=1024,
        temperature=0.7,
    )

    return Response(content=response_text, media_type="text/plain; charset=utf-8", status_code=200)

@app.get("/api/hard-reset")
@app.get("/api/hard-reset/")
async def hard_reset_endpoint():
    """
    HARD RESET:
    - Deletes .page_memory.json
    - Deletes image cache directory
    - Deletes .openrouter_api_key
    Fully resets server memory/cache and API key.
    """
    clear_page_memory()  # wipe in-memory dict first
    safe_delete_file(PAGE_MEMORY_FILE)
    safe_delete_dir(IMAGE_CACHE_DIR)
    safe_delete_file(OPENROUTER_KEY_FILE)
    

    return Response(
        content="Hard reset complete: page memory, image cache, and OpenRouter API key deleted.",
        media_type="text/plain; charset=utf-8",
        status_code=200,
    )


@app.get("/api/soft-reset")
@app.get("/api/soft-reset/")
async def soft_reset_endpoint():
    """
    SOFT RESET:
    - Deletes .page_memory.json
    - Deletes image cache directory
    - Keeps .openrouter_api_key
    Resets content memory + image cache, but keeps API key configured.
    """
    clear_page_memory()  # wipe in-memory dict first
    safe_delete_file(PAGE_MEMORY_FILE)
    safe_delete_dir(IMAGE_CACHE_DIR)

    return Response(
        content="Soft reset complete: page memory and image cache deleted, API key preserved.",
        media_type="text/plain; charset=utf-8",
        status_code=200,
    )


@app.get("/api/lobotomy")
@app.get("/api/lobotomy/")
async def lobotomy_endpoint():
    """
    LOBOTOMY:
    - Deletes only .page_memory.json
    - Keeps image cache and API key
    Resets site memory while retaining cached images and configuration.
    """
    clear_page_memory()  # wipe in-memory dict first
    safe_delete_file(PAGE_MEMORY_FILE)

    return Response(
        content="Lobotomy complete: page memory deleted, image cache and API key preserved.",
        media_type="text/plain; charset=utf-8",
        status_code=200,
    )

@app.api_route("/{url_path:path}", methods=["GET", "POST"])
async def handle_request(url_path: str, request: Request, mood: str | None = None):
    query = request.url.query or ""
    cache_key = f"{url_path}?{query}"
    normalized_path = "/" + url_path if not url_path.startswith("/") else url_path

    # ----- CACHE HIT -----
    if request.method == "GET" and cache_key in cache:
        content_type, body = cache[cache_key]
        return Response(content=body, media_type=content_type)

    # ----- OPTIONAL DATA BUILD -----
    optional_chunks: list[str] = []

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

    # ==============================
    #  SPECIAL CASE: PNG GENERATION
    # ==============================
    if url_path.lower().endswith(".png"):
        disk_path = os.path.join(IMAGE_CACHE_DIR, url_path.replace("/", "_"))

        # RAM cache
        if url_path in image_cache:
            return Response(content=image_cache[url_path], media_type="image/png", status_code=200)

        # Disk cache
        if os.path.exists(disk_path):
            with open(disk_path, "rb") as f:
                img_bytes = f.read()
            image_cache[url_path] = img_bytes
            return Response(content=img_bytes, media_type="image/png", status_code=200)

        # Generate fresh image via RANDOM_MODEL → IMAGE_GEN_MODEL
        image_bytes, status_code = await generate_png_for_path(
            url_path=normalized_path,
            optional_data=optional_data,
            mood_instruction=(mood or "").strip(),
        )

        if status_code == 200 and image_bytes:
            image_cache[url_path] = image_bytes
            tmp = disk_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(image_bytes)
            os.replace(tmp, disk_path)

        return Response(content=image_bytes, media_type="image/png", status_code=status_code)


    # ----- NORMAL TEXT/HTML/JSON GENERATION PATH -----
    max_tokens = get_max_tokens_for_path(url_path)

    # ----- STREAM FROM MODEL -----
    status_code, media_type, body_stream = await stream_page_for_path(
            url_path=url_path,
            model=MAIN_MODEL,
            optional_data=optional_data,
            mood_instruction=(mood or "").strip(),
            max_tokens=max_tokens,
    )


    # ----- RULE: DO NOT STREAM JSON OR XML -----
    if media_type.startswith("application/json") or media_type.endswith("json") or media_type.endswith("xml") or media_type.startswith("text/xml") or "xml" in media_type:

        parts = []
        async for chunk in body_stream:
            parts.append(chunk)
        full_body = "".join(parts)

        asyncio.create_task(remember_page(normalized_path, full_body, media_type))

        if request.method == "GET":
            cache[cache_key] = (media_type, full_body)

        return Response(full_body, media_type=media_type, status_code=status_code)


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

    return StreamingResponse(tee(), media_type=media_type, status_code=status_code)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=True)
