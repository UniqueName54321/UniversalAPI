"""
Utility routes for the UniversalAPI application.

This module handles search functionality and page editing:
- /go endpoint for search and query processing
- /edit/{url_path} endpoints for page editing (GET form, POST regeneration)
"""

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from ..generator import generate_page_for_path
from ..memory import remember_page
from ..config import MAIN_MODEL
import re
from typing import Tuple
from ..ai_client import generate_text_response


async def map_query_to_path(user_input: str) -> str:
    """
    Use the main LLM to turn messy natural language into a clean URL path
    that your catch-all handler will process.
    """
    raw = user_input.strip()

    # If user already typed a path, just clean it up a bit and trust them.
    if raw.startswith("/"):
        path = raw.lower()
        path = re.sub(r"\s+", "-", path)                 # spaces -> hyphens
        path = re.sub(r"[^a-z0-9/_\-.]", "", path)       # allowed chars only
        path = re.sub(r"-+", "-", path).strip()
        if not path or path == "/":
            return "/home"
        if not path.startswith("/"):
            path = "/" + path
        return path

    system_prompt = """
You are a strict URL router for a web app called UniversalAPI.

Your ONLY job is to convert a natural language request into a SINGLE URL PATH STRING.

Rules:
- Output ONLY the path. No explanations. No quotes. No backticks. No extra text.
- The path MUST:
  - Start with "/"
  - Be all lowercase
  - Use only: letters a-z, digits 0-9, "/", "-", "_", and "."
  - Use "-" instead of spaces.
- Do NOT include a domain, protocol, or query string (no "http://", no "https://", no "?").

- If the user clearly wants an image (asks for a picture, image, icon, logo, drawing, illustration, meme, etc.),
  then end the path with ".png".

- If the user explicitly mentions a rating tag (G, T, M, A, X) and is asking for a STORY,
  then use this structure:
    /story/<rating>/<slug>
  Example:
    input: "write a T-rated sci-fi story about space pirates"
    path:  "/story/t/space-pirates-sci-fi"

- If the user clearly wants a general explanation or info, you can do something like:
    "/black-holes-explained"

- If the user clearly wants an API-style response, you can do something like:
    "/api/black-holes"

- If the user clearly wants to edit or refine an existing concept, you MAY use:
    "/edit/<slug>"

- If the input is completely unclear, default to:
    "/home"

- If the user clearly wants to edit or refine an existing concept, you MAY use:
    "/edit/<slug>"

Examples (for your understanding; do NOT repeat them in the output):

User: "explain black holes like I'm 10"
Path:  "/black-holes-for-kids"

User: "T-rated fantasy story about a cursed forest"
Path:  "/story/t/cursed-forest-fantasy"

User: "draw a cute golden retriever wearing sunglasses png"
Path:  "/golden-retriever-sunglasses.png"

User: "give me a JSON-style summary of quantum computing"
Path:  "/api/quantum-computing-summary"

User: "edit the cat explanation to be funnier"
Path:  "/edit/cat"

Remember: respond with ONE path string ONLY.
"""

    user_prompt = f"User request: {user_input!r}\n\nReturn ONLY the URL path."

    ai_output = await generate_text_response(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        model=MAIN_MODEL,
        max_tokens=64,
        temperature=0.2,
    )

    # Use first non-empty line
    candidate = ""
    for line in ai_output.splitlines():
        line = line.strip()
        if line:
            candidate = line
            break

    if not candidate:
        return "/home"

    # If the model got too helpful and returned a full URL, strip host
    candidate = re.sub(r"^https?://[^/]+", "", candidate, flags=re.IGNORECASE)

    # Force leading slash
    if not candidate.startswith("/"):
        candidate = "/" + candidate

    # Normalize: lowercase, hyphens, allowed chars only
    candidate = candidate.lower()
    candidate = re.sub(r"\s+", "-", candidate)
    candidate = re.sub(r"[^a-z0-9/_\-.]", "-", candidate)
    candidate = re.sub(r"-+", "-", candidate).strip()
    candidate = re.sub(r"^/-+", "/", candidate)

    if not candidate or candidate == "/":
        candidate = "/home"

    # Clean trailing hyphens and before .png
    candidate = re.sub(r"-+(\.png)$", r"\1", candidate)
    candidate = re.sub(r"-+$", "", candidate) or "/home"

    return candidate


def register_routes(app: FastAPI) -> None:
    """Register utility routes with the FastAPI application."""
    
    @app.get("/go")
    async def go(request: Request):
        """
        Take natural language ?q=..., turn it into a path via LLM, and redirect there.
        """
        q = (request.query_params.get("q") or "").strip()
        if not q:
            # no input? just send them home
            return RedirectResponse(url="/", status_code=307)

        target_path = await map_query_to_path(q)
        return RedirectResponse(url=target_path, status_code=307)

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
        max_tokens = 2048  # get_max_tokens_for_path(url_path)

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
        # cache[cache_key] = (media_type, full_body)  # TODO: Need to access cache from state

        # Defer memory work (summarization + links)
        # TODO: Need to access cache from state
        # cache[cache_key] = (media_type, full_body)

        # Defer memory work (summarization + links)
        # asyncio.create_task(remember_page(normalized_path, full_body, media_type))

        return RedirectResponse(url=normalized_path, status_code=302)


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

    # Normalize MIME
    mime = mime_part
    if not mime or "/" not in mime:
        mime = "text/html"

    # Add charset for text/* if missing
    lower = mime.lower()
    if mime.startswith("text/") and "charset" not in lower:
        mime = f"{mime}; charset=utf-8"

    return status, mime