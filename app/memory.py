import json
import os
import re
import time
import threading
import hashlib
from typing import List, Dict, Tuple

from .config import MEMORY_FILE, RANDOM_MODEL
from .ai_client import generate_text_response

# Thread lock is fine here; we only use it around dict/file ops.
memory_lock = threading.Lock()

# page_memory structure:
# {
#   "/path": {
#       "summary": str,
#       "links": ["/other", "/paths"],
#       "last_updated": float_timestamp,
#       "hash": str
#   },
#   ...
# }
page_memory: Dict[str, Dict] = {}


def _load_memory() -> None:
    global page_memory
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                page_memory = json.load(f)
        else:
            page_memory = {}
    except Exception:
        page_memory = {}


_load_memory()


def _extract_internal_links_from_html(html: str) -> List[str]:
    """
    Very simple href extractor for internal links like href="/something".
    Not a full HTML parser, but good enough for our use.
    """
    hrefs = re.findall(r'href="(/[^"#?"]*)"', html)
    seen = set()
    result: List[str] = []
    for h in hrefs:
        if h not in seen:
            seen.add(h)
            result.append(h)
    return result


async def summarize_page_with_ai(body: str, max_chars: int = 6000) -> str:
    """
    Use the RANDOM_MODEL to generate a concise summary of a page's body.
    Output should be plain text, a few sentences, no markdown.
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
        summary = await generate_text_response(
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


async def remember_page(url_path: str, body: str, content_type: str) -> None:
    """
    Store a summarized memory + internal links for this page.
    Uses LLM-based summarization and caches by content hash.
    """
    ct_lower = content_type.lower()

    # Only store text-ish content
    if not (ct_lower.startswith("text/") or ct_lower.startswith("application/json")):
        return

    try:
        body_hash = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()
    except Exception:
        body_hash = ""

    links: List[str] = []
    if ct_lower.startswith("text/html"):
        links = _extract_internal_links_from_html(body)

    # Read existing entry (no long work under lock)
    with memory_lock:
        old_entry = page_memory.get(url_path)

    need_summary = True
    summary = ""

    if old_entry and old_entry.get("hash") == body_hash and old_entry.get("summary"):
        summary = old_entry.get("summary", "")
        need_summary = False

    if need_summary:
        summary = await summarize_page_with_ai(body)

    # Update memory + file under lock
    with memory_lock:
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


def get_related_memory(url_path: str, limit: int = 5) -> List[Tuple[str, Dict]]:
    """
    Super simple relatedness:
    - Shared tokens in the path (split on / and -)
    - Backlink style: pages that link to this one
    """
    with memory_lock:
        if not page_memory:
            return []

        tokens = {
            t
            for t in re.split(r"[/\-]+", url_path.lower())
            if t and t not in {"api", "data", "json"}
        }

        scores: List[Tuple[float, str]] = []

        # Precompute backlinks
        backlinks: Dict[str, int] = {}
        for path, entry in page_memory.items():
            for link in entry.get("links", []):
                backlinks[link] = backlinks.get(link, 0) + 1

        for path, entry in page_memory.items():
            if path == "/" or path == url_path:
                continue

            other_tokens = {
                t for t in re.split(r"[/\-]+", path.lower()) if t
            }
            token_score = len(tokens & other_tokens)

            backlink_score = 0.0
            if url_path in backlinks:
                backlink_score = float(backlinks.get(url_path, 0))

            score = token_score + 0.5 * backlink_score
            if score > 0:
                scores.append((score, path))

        scores.sort(key=lambda x: x[0], reverse=True)

        results: List[Tuple[str, Dict]] = []
        for _, path in scores[:limit]:
            results.append((path, page_memory[path]))
        return results
