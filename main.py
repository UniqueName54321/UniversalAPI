import flask
import ai
import json
import os
import re
import time
import threading
import hashlib

RANDOM_MODEL = "meituan/longcat-flash-chat:free"   # or whatever cheap/fast model you like
MAIN_MODEL   = "x-ai/grok-4.1-fast:free"           # for serious pages

AI_PERSONALITY = """
You are friendly, helpful, a little humorous, and you keep explanations simple.
Avoid being overly formal. Be clear, human-like, and engaging.
"""

BASE_PROMPT = """You are a universal content generator. Your job is to create a response document that matches the topic, meaning, or purpose of the following URL path:

    {{URL_PATH}}

Your response MUST obey the following strict output format:

1. The first line MUST contain ONLY a valid MIME type. No labels, no explanation, no colon, no backticks, no code fences.
   Examples:
   text/html
   text/plain
   application/json
   text/markdown

2. The rest of the output is the body of the response.

-------------------------------------------------------------------------------
PERSONALITY SYSTEM
-------------------------------------------------------------------------------
Base personality:
You are helpful, clear, slightly humorous, friendly, and conversational. You avoid excessive formality. You explain things in simple, human-like language and avoid sounding robotic.

If {{MOOD_OVERRIDE}} is provided, modify your tone to match it. This override should influence writing style, but NOT break formatting rules.

Examples of moods:
- "chaotic", "gen-z", "grumpy professor", "excited", "soft and cozy", 
- "sassy", "poetic", "gentle", "sarcastic but informative", etc.

-------------------------------------------------------------------------------
URL INTERPRETATION RULES
-------------------------------------------------------------------------------

Analyze the URL path and decide the correct type of response:

1. If the URL resembles a webpage path:
   Examples: "/", "/index", "/index.html", "/about", "/help", "/contact", "/page/*"
   → Produce a full HTML page.

2. If the URL is a noun, concept, idea, or topic:
   Examples: "/cat", "/entropy", "/python", "/nebula"
   → Produce an informational explanation.

3. If the URL is written like a question:
   Examples: "/why-is-the-sky-blue", "/how-do-rockets-work"
   → Provide a clear and direct answer.

4. If the URL resembles an API/data path:
   Examples: "/api/*", "/data/*", "/json/*"
   → Return JSON unless another MIME type is obviously more appropriate.

5. If the URL looks like a file extension:
   - "/robots.txt" → treat as plain text
   - "/sitemap.xml" → XML format
   - "/readme.md"  → Markdown
   - "/config.json" → JSON

6. If unsure:
   → Make the most reasonable guess and produce a meaningful answer.

-------------------------------------------------------------------------------
HTML GENERATION RULES (when MIME = text/html)
-------------------------------------------------------------------------------

When producing HTML:

- Use valid UTF-8 HTML:
    <html>
    <head>
      <meta charset="utf-8">
      <title>...</title>
      <style>
        body {
          font-family: Arial, sans-serif;
          max-width: 900px;
          margin: auto;
          padding: 2rem;
          line-height: 1.6;
        }
        nav a {
          margin-right: 1rem;
          text-decoration: none;
          color: #0645AD;
        }
        nav a:hover {
          text-decoration: underline;
        }
        h1, h2, h3 {
          font-weight: 600;
        }
        .section { margin-top: 2rem; }
        .edit-link {
          font-size: 0.9rem;
          color: #777;
          display: inline-block;
          margin-top: 1rem;
        }
      </style>
    </head>
    <body>...</body>
    </html>

- Always include a navigation bar at the top with links to:
    "/", "/about", "/help", "/contact", "/topics", "/random", "/api"

- Include a "Related Pages" section with 3–6 relevant links.
  These should be reasonable guesses based on the topic.
  Examples:
  "/stars", "/light", "/chemistry", "/history", "/math", "/clouds"

- Include an "Explore More" section with 3–5 general-purpose links such as:
  "/", "/science", "/technology", "/fun-facts", "/articles", "/learn"

- For homepage-like pages ("/", "/index", "/index.html"):
    → Generate a clean homepage layout with welcome text, sections, and useful guidance.

- For HTML pages, include a small "Edit this page" link somewhere near the top or bottom,
  pointing to "/edit{{URL_PATH}}".
  Example: <a href="/edit/nebula" class="edit-link">Edit this page</a>

- Avoid unnecessary verbosity.

-------------------------------------------------------------------------------
RANDOM TOPIC GENERATION
-------------------------------------------------------------------------------
SPECIAL BEHAVIOR FOR /random:
If the URL_PATH (or the provided path) is "!!GENERATE_RANDOM_TOPIC!!", you MUST:

1. Invent a brand new fictional topic, concept, creature, phenomenon, or invention.
   Examples:
       "Quantum Marshmallow Drift"
       "The Midnight Sock Thief Paradox"
       "Chrono-Waffle Compression Syndrome"
       "The Great Cosmic Napping Festival"

2. Treat it EXACTLY as if the user had visited a real page for it.
   → If HTML is appropriate, make a full beautiful HTML page.
   → Include:
       - Title
       - Explanation
       - Sections
       - Fun facts
       - Origin lore
       - Related Pages (also invented!)
       - Explore More links

3. It must NOT look like a random fact.
4. It must NOT be something real.
5. Make it entertaining, imaginative, and cohesive.

6. Apply personality and mood override normally.

SPECIAL RULE FOR RANDOM TOPICS:
When URL_PATH is "!!GENERATE_RANDOM_TOPIC!!":

- The topic is entirely fictional.
- You MUST NOT include an "External Links" section.
- DO NOT attempt to create hypothetical or placeholder real-world URLs.
- Internal links ("Related Pages", "Explore More") are still required.

-------------------------------------------------------------------------------
JSON RULES (when MIME = application/json)
-------------------------------------------------------------------------------

- Produce valid parseable JSON.
- No comments, no trailing commas, no text outside the JSON.
- Keep structure simple unless complexity is meaningful.

-------------------------------------------------------------------------------
MARKDOWN RULES (when MIME = text/markdown)
-------------------------------------------------------------------------------

- Use clean, standard Markdown.
- Heading hierarchy MUST be consistent.

-------------------------------------------------------------------------------
OPTIONAL DATA (POST requests and site memory)
-------------------------------------------------------------------------------

OPTIONAL_DATA may contain:

- POST_DATA: raw data from POST requests.
- SITE_MEMORY: summaries of other related pages on this site.
- EDIT_INSTRUCTIONS: user instructions for how to revise or reshape the page.

You MUST:
- Use SITE_MEMORY to keep information consistent across related pages.
- Respect EDIT_INSTRUCTIONS when present, while still obeying URL_PATH rules.
- Incorporate POST_DATA meaningfully when provided.
- Never break the required output format.

------------------------------------------------------------------------------
TERMS OF SERVICE AND OTHER LEGALITIES
-------------------------------------------------------------------------------

SPECIAL LEGAL PAGE RULES
-------------------------------------------------------------------------------

If the URL_PATH includes terms such as "terms", "policy", "legal", 
"privacy", or "conditions":

- DO NOT use humor unless explicitly instructed via MOOD_OVERRIDE.
- Tone must be formal, clear, and legally appropriate.
- Do not include jokes, casual phrasing, or conversational fluff.
- Focus on clarity, correctness, and structure.

-------------------------------------------------------------------------------
EXTERNAL LINKS RULES
-------------------------------------------------------------------------------

If the URL_PATH clearly refers to a real-world topic, product, brand, media
franchise, game, book, comic, company, person, technology, or any subject 
that exists outside this site:

1. Include a section titled "External Links" AFTER "Related Pages" but BEFORE
   "Explore More".

2. External links MUST be real URLs relevant to the topic. Examples:
   - Official websites
   - Wikipedia
   - Fandom/Wikia pages
   - Author/artist pages
   - Official social media
   - GitHub repos (if software-related)
   - Documentation pages
   - Stores or archives hosting the real media

3. Only include **2–4** highly relevant external links.

4. DO NOT hallucinate URLs. Use the most well-known existing ones.

5. If the topic is fictional and has no real-world references, do NOT create an
   External Links section.

6. Internal navigation (Related Pages, Explore More) MUST still use internal
   site paths.

-------------------------------------------------------------------------------
OUTPUT SUMMARY
-------------------------------------------------------------------------------

FIRST LINE: strictly the MIME type ONLY  
FOLLOWING LINES: the content body  
NO code fences  
NO commentary outside the body  
No “Here is your response” phrasing  
"""

# --------- CACHED SYSTEM MESSAGE (BUILT ONCE AT IMPORT) ---------
SYSTEM_MESSAGE = {
    "role": "system",
    "content": AI_PERSONALITY + "\n\n" + BASE_PROMPT,
}

cache: dict[str, tuple[str, str]] = {}

# --------- SIMPLE PAGE MEMORY (WITH LLM SUMMARIES) -------------
MEMORY_FILE = "page_memory.json"
memory_lock = threading.Lock()

# page_memory structure:
# {
#   "/path": {
#       "summary": str,
#       "links": ["/other", "/paths"],
#       "last_updated": float_timestamp,
#       "hash": str  # hash of body content to avoid re-summarizing unchanged pages
#   },
#   ...
# }
try:
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            page_memory: dict[str, dict] = json.load(f)
    else:
        page_memory = {}
except Exception:
    page_memory = {}


def _extract_internal_links_from_html(html: str) -> list[str]:
    """
    Very simple href extractor for internal links like href="/something".
    Not a full HTML parser, but good enough for our use.
    """
    hrefs = re.findall(r'href="(/[^"#?"]*)"', html)
    seen = set()
    result = []
    for h in hrefs:
        if h not in seen:
            seen.add(h)
            result.append(h)
    return result


def summarize_page_with_ai(body: str, max_chars: int = 6000) -> str:
    """
    Use the RANDOM_MODEL to generate a concise summary of a page's body.
    Output should be plain text, a few sentences, no markdown or extra metadata.
    """
    text = body.strip()
    if len(text) > max_chars:
        text = text[:max_chars]

    if not text:
        return ""

    system_msg = (
        "You are a concise summarization engine.\n"
        "Your job is to read page content and produce a short, clear summary "
        "(2–5 sentences). Return only the summary as plain text. "
        "Do not include headings, bullet points, or labels. No markdown."
    )

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": (
                "Summarize the following page content for later site-wide reference:\n\n"
                f"{text}"
            ),
        },
    ]

    try:
        summary = ai.generate_text_response(
            messages=messages,
            model=RANDOM_MODEL,
            max_tokens=256,
            temperature=0.3,
        )
        return summary.strip()
    except Exception as e:
        print(f"[MEMORY] Summarization error: {e}")
        # Fallback: crude snippet
        snippet = text[:800]
        if len(text) > 800:
            snippet += " ..."
        return snippet


def remember_page(url_path: str, body: str, content_type: str):
    """
    Store a summarized memory + internal links for this page.
    Uses LLM-based summarization (RANDOM_MODEL) and caches by content hash.
    """
    ct_lower = content_type.lower()

    # Only store text-ish content
    if not (ct_lower.startswith("text/") or ct_lower.startswith("application/json")):
        return

    # Compute content hash so we don't re-summarize unchanged pages
    try:
        body_hash = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()
    except Exception:
        body_hash = ""

    links: list[str] = []
    if ct_lower.startswith("text/html"):
        links = _extract_internal_links_from_html(body)

    with memory_lock:
        old_entry = page_memory.get(url_path)
        need_summary = True
        summary = ""

        if old_entry and old_entry.get("hash") == body_hash and old_entry.get("summary"):
            # Content seems unchanged; reuse summary
            summary = old_entry.get("summary", "")
            need_summary = False

        if need_summary:
            summary = summarize_page_with_ai(body)

        page_memory[url_path] = {
            "summary": summary,
            "links": links,
            "last_updated": time.time(),
            "hash": body_hash,
        }

        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(page_memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MEMORY] Failed to write {MEMORY_FILE}: {e}")


def get_related_memory(url_path: str, limit: int = 5) -> list[tuple[str, dict]]:
    """
    Super simple relatedness:
    - Shared tokens in the path (split on / and -)
    - Backlink style: pages that link to this one
    """
    with memory_lock:
        if not page_memory:
            return []

        tokens = set(
            t for t in re.split(r"[/\-]+", url_path.lower())
            if t and t not in {"api", "data", "json"}
        )

        scores: list[tuple[float, str]] = []

        # Precompute backlinks
        backlinks: dict[str, int] = {}
        for path, entry in page_memory.items():
            for link in entry.get("links", []):
                backlinks[link] = backlinks.get(link, 0) + 1

        for path, entry in page_memory.items():
            if path == "/" or path == url_path:
                continue

            other_tokens = set(
                t for t in re.split(r"[/\-]+", path.lower())
                if t
            )
            token_score = len(tokens & other_tokens)

            backlink_score = 0.0
            # If this page is linked from others, give a small boost
            if url_path in backlinks:
                backlink_score = float(backlinks.get(url_path, 0))

            score = token_score + 0.5 * backlink_score
            if score > 0:
                scores.append((score, path))

        scores.sort(key=lambda x: x[0], reverse=True)

        results: list[tuple[str, dict]] = []
        for _, path in scores[:limit]:
            results.append((path, page_memory[path]))
        return results


app = flask.Flask(__name__)


def get_max_tokens_for_path(url_path: str) -> int:
    """
    Rough heuristic for max_tokens based on the URL path.
    Tune this however you like.
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


def generate_request_body(
    url_path: str,
    model: str,
    optional_data: str = "",
    mood_instruction: str = "",
    max_tokens: int = 2048,
) -> str:
    """
    Build a user-level prompt that works with the cached SYSTEM_MESSAGE.

    The system message holds all the rules.
    This user message just feeds:
      - URL_PATH
      - MOOD_OVERRIDE
      - OPTIONAL_DATA
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
        SYSTEM_MESSAGE,                     # cached rules
        {"role": "user", "content": user_prompt},
    ]

    return ai.generate_text_response(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=0.7,
    )


@app.route("/")
def home():
    html = """<!DOCTYPE html>
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
    return flask.Response(html, content_type="text/html; charset=utf-8")


@app.route("/random")
def random_page():
    # Generate fake path target for AI
    fake_path = "!!GENERATE_RANDOM_TOPIC!!"

    mood = flask.request.args.get("mood", "").strip()
    optional_data = ""  # could feed query/body later if you want

    response_body = generate_request_body(
        fake_path,
        model=RANDOM_MODEL,
        optional_data=optional_data,
        mood_instruction=mood,
        max_tokens=3072,   # give it room for a fun page
    )

    # Extract MIME and body
    first_line, _, rest = response_body.partition("\n")
    content_type = first_line.strip() or "text/html"
    if "charset" not in content_type.lower():
        content_type += "; charset=utf-8"
    body = rest.strip()

    # For now, we don't store random topics into memory, since they're one-offs.
    return flask.Response(body, content_type=content_type)


@app.route("/edit/<path:url_path>", methods=["GET", "POST"])
def edit_page(url_path):
    """
    Simple 'edit this page' interface.
    It regenerates the page with extra EDIT_INSTRUCTIONS passed via OPTIONAL_DATA.
    """
    display_path = "/" + url_path if not url_path.startswith("/") else url_path

    if flask.request.method == "GET":
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
        return flask.Response(html, content_type="text/html; charset=utf-8")

    # POST: regenerate with instructions
    instructions = flask.request.form.get("instructions", "").strip()

    optional_data = f"EDIT_INSTRUCTIONS:\n{instructions or '(no specific instructions)'}\n"

    max_tokens = get_max_tokens_for_path(url_path)

    response_body = generate_request_body(
        url_path,
        model=MAIN_MODEL,
        optional_data=optional_data,
        mood_instruction="",  # mood can be part of EDIT_INSTRUCTIONS if desired
        max_tokens=max_tokens,
    )

    raw_first_line, _, rest = response_body.partition("\n")
    first_line = raw_first_line.strip()

    # Remove "Content-Type:" prefix if the model added it
    if first_line.lower().startswith("content-type"):
        first_line = first_line.split(":", 1)[-1].strip()

    # If it's empty or invalid, default to text/plain
    if "/" not in first_line:
        first_line = "text/plain"

    content_type = first_line
    body = rest.strip()

    # If content_type lacks a charset, force UTF-8
    if "charset" not in content_type.lower():
        content_type = f"{content_type}; charset=utf-8"

    # Record new version in memory and update cache
    normalized_path = "/" + url_path if not url_path.startswith("/") else url_path
    remember_page(normalized_path, body, content_type)

    cache_key = url_path + "?"
    cache[cache_key] = (content_type, body)

    return flask.redirect(normalized_path)


@app.route('/<path:url_path>', methods=['GET', 'POST'])
def handle_request(url_path):
    query = flask.request.query_string.decode()
    cache_key = url_path + "?" + query

    # Serve from cache for GETs
    if cache_key in cache and flask.request.method == 'GET':
        content_type, body = cache[cache_key]
        return flask.Response(body, content_type=content_type)

    mood = flask.request.args.get("mood", "").strip()

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
    if flask.request.method == 'POST':
        post_body = flask.request.get_data(as_text=True)
        optional_chunks.append(f"POST_DATA:\n{post_body}\n")

    optional_data = "\n\n".join(optional_chunks) if optional_chunks else "(none)"

    max_tokens = get_max_tokens_for_path(url_path)

    response_body = generate_request_body(
        url_path,
        model=MAIN_MODEL,
        optional_data=optional_data,
        mood_instruction=mood,
        max_tokens=max_tokens,
    )

    raw_first_line, _, rest = response_body.partition("\n")
    first_line = raw_first_line.strip()

    # Remove "Content-Type:" prefix if the model added it
    if first_line.lower().startswith("content-type"):
        first_line = first_line.split(":", 1)[-1].strip()

    # If it's empty or invalid, default to text/plain
    if "/" not in first_line:
        first_line = "text/plain"

    content_type = first_line
    body = rest.strip()

    # If content_type lacks a charset, force UTF-8
    if "charset" not in content_type.lower():
        content_type = f"{content_type}; charset=utf-8"

    # Record into memory
    remember_page(normalized_path, body, content_type)

    resp = flask.Response(body, content_type=content_type)

    # Cache GET responses
    if flask.request.method == 'GET':
        cache[cache_key] = (content_type, body)

    return resp


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
