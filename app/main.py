import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Tuple
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse, StreamingResponse

from app.ai_client import generate_text_response

from app.config import IMAGE_CACHE_DIR_STR, MAIN_MODEL, RANDOM_MODEL
from app.config import MEMORY_FILE_STR as PAGE_MEMORY_FILE_STR
from app.config import OPENROUTER_KEY_FILE_STR

PAGE_MEMORY_FILE = Path(PAGE_MEMORY_FILE_STR)
OPENROUTER_KEY_FILE = Path(OPENROUTER_KEY_FILE_STR)
IMAGE_CACHE_DIR = Path(IMAGE_CACHE_DIR_STR)

from app.generator import generate_page_for_path, get_max_tokens_for_path, stream_page_for_path, parse_status_and_mime, generate_png_for_path
from app.memory import remember_page, get_related_memory
from app.memory import clear_page_memory  # NEW

# Import route modules
from app.routes import register_routes

app = FastAPI()

# Register all routes
register_routes(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=True)
