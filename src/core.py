import sys
import os
import json
import re
import cv2
import shutil
from typing import Dict, Any, Optional

from PySide6.QtCore import QMutex

# ==========================================
# Feature Flags & Imports
# ==========================================
try:
    import requests
except ImportError:
    print("⚠️ Error: 'requests' library is missing. Run: pip install requests")
    sys.exit(1)

HAS_OPENCV = False
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    print("⚠️ Warning: opencv-python is missing. Video thumbnail extraction will be disabled.")

HAS_PILLOW = False
try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    HAS_PILLOW = True
except ImportError:
    print("⚠️ Warning: Pillow library is missing. pip install pillow")

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
# Constants & Paths
# ==========================================
# Assuming this file is in <ROOT>/src/core.py, so ROOT is ../
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "manager_config.json")
CACHE_DIR_NAME = os.path.join(BASE_DIR, "cache")

SUPPORTED_EXTENSIONS = {".ckpt", ".pt", ".bin", ".safetensors", ".gguf"}
PREVIEW_EXTENSIONS = [".mp4", ".webm", ".gif", ".preview.png", ".png", ".jpg", ".jpeg", ".webp"]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".preview.png"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".gif", ".mov"} 

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
def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

def extract_video_frame(video_path, output_path):
    """
    OpenCV를 사용하여 비디오 프레임을 추출합니다.
    """
    if not HAS_OPENCV: return False
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return False
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(output_path, frame)
            return True
    except Exception as e:
        print(f"Frame extraction failed: {e}")
    finally:
        if cap: cap.release()
    return False

def calculate_structure_path(model_path: str, cache_root: str, directories: Dict[str, str]) -> str:
    """
    Calculates the structured cache path for a given model.
    Replaces _get_full_structured_cache_path and _calculate_cache_path from the original code.
    """
    model_abs = os.path.abspath(model_path)
    model_dir = os.path.dirname(model_abs)
    model_name = os.path.splitext(os.path.basename(model_path))[0]
    
    root_alias = "Uncategorized"
    rel_path = ""
    
    for alias, root_path in directories.items():
        root_abs = os.path.abspath(root_path)
        if model_abs.startswith(root_abs):
            root_alias = alias
            try:
                rel_path = os.path.relpath(model_dir, root_abs)
                if rel_path == ".": rel_path = ""
            except: 
                rel_path = ""
            break
            
    return os.path.join(cache_root, root_alias, rel_path, model_name)

# ==========================================
# Config Management
# ==========================================
def load_config(config_path=CONFIG_FILE) -> Dict[str, Any]:
    """Loads the configuration from JSON file."""
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load config: {e}")
    return {}

def save_config(data: Dict[str, Any], config_path=CONFIG_FILE):
    """Saves the configuration dict to JSON file."""
    try:
        with open(config_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            # Ensure_ascii=False is good for Non-English characters, adding it since original had it in one place
    except Exception as e:
        print(f"Failed to save config: {e}")
        raise e
