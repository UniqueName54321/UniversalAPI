import os
from .config import IMAGE_CACHE_DIR_STR

os.makedirs(IMAGE_CACHE_DIR_STR, exist_ok=True)