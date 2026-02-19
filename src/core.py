import sys
import os
import json
import gzip
import re
import logging
from typing import Dict, Any, Optional

from PySide6.QtCore import QMutex

# ==========================================
# Feature Flags & Imports
# ==========================================
try:
    import requests
except ImportError:
    logging.critical("'requests' library is missing. Run: pip install requests")
    sys.exit(1)

HAS_PILLOW = False
try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    HAS_PILLOW = True
except ImportError:
    logging.warning("Pillow library is missing. pip install pillow")

HAS_MARKDOWN = False
try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    pass

HAS_MARKDOWNIFY = False
try:
    import markdownify
    HAS_MARKDOWNIFY = True
except ImportError:
    pass

# ==========================================
# Constants & 路径s
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "manager_config.json")
CACHE_DIR_NAME = os.path.join(BASE_DIR, "cache")

# Extension Definitions
EXT_MODEL = {".ckpt", ".pt", ".bin", ".safetensors", ".gguf", ".pth"}
EXT_WORKFLOW = {".json"}
EXT_PROMPT = {".txt", ".json"} 

# 模式 Mapping
SUPPORTED_EXTENSIONS = {
    "model": EXT_MODEL,
    "workflow": EXT_WORKFLOW,
    "prompt": EXT_PROMPT
}

PREVIEW_EXTENSIONS = [".mp4", ".webm", ".preview.png", ".png", ".jpg", ".jpeg", ".webp"]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".preview.png"}
MAX_FILE_LOAD_MB = 200
MAX_FILE_LOAD_BYTES = MAX_FILE_LOAD_MB * 1024 * 1024

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"} 

# ==========================================
# Helper Classes
# ==========================================
class QMutexWithLocker:
    def __init__(self, mutex: QMutex):
        self.mutex = mutex
    def __enter__(self):
        self.mutex.lock()
    def __exit__(self, exc_type, exc_value, traceback):
        self.mutex.unlock()

# ==========================================
# Utility Functions
# ==========================================
def sanitize_filename(filename: str) -> str:
    """Removes invalid characters from a filename."""
    return re.sub(r'[<>:\"/\\|?*]', '', filename).strip()

def calculate_structure_path(model_path: str, cache_root: str, directories: Dict[str, Any], mode: str = "model") -> str:
    """
    Calculates the structured cache path.
    New Strategy: Flat structure based on 模式 and Filename.
    路径: cache_root/<mode>/<model_name>
    Directories argument is kept for signature compatibility but not strictly needed for flat structure logic,
    unless we want to validate something.
    """
    model_name = os.path.splitext(os.path.basename(model_path))[0]
    
    # Sanitize mode just in case
    safe_mode = sanitize_filename(mode)
    if not safe_mode: safe_mode = "model"
    
    return os.path.join(cache_root, safe_mode, model_name)

# ==========================================
# Config Management
# ==========================================
def load_config(config_path=CONFIG_FILE) -> Dict[str, Any]:
    """Loads the configuration from JSON file and handles migration."""
    data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"失败 to load config: {e}")
            return {}

    settings = data.get("__settings__", {})
    directories = settings.get("directories", {})
    
    migrated = False
    new_directories = {}
    
    for alias, val in directories.items():
        if isinstance(val, str):
            new_directories[alias] = {"path": val, "mode": "model"}
            migrated = True
        else:
            new_directories[alias] = val
            
    if migrated:
        settings["directories"] = new_directories
        data["__settings__"] = settings
        save_config(data, config_path)
        logging.info("Config migrated to new structure.")
        
    return data

def save_config(data: Dict[str, Any], config_path=CONFIG_FILE):
    """Saves the configuration dict to JSON file."""
    try:
        with open(config_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"失败 to save config: {e}")
        raise e

# ==========================================
# Metadata Imports (Refactored)
# ==========================================
from .metadata import (
    validate_metadata_type as validate_comfy_metadata,
    standardize_metadata
)
from .metadata.novelai import extract_novelai_data
from .metadata.comfy import parse_comfy_workflow
