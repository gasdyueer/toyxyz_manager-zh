import sys
import os
import json
import re
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

# Extension Definitions
EXT_MODEL = {".ckpt", ".pt", ".bin", ".safetensors", ".gguf"}
EXT_WORKFLOW = {".json"}
EXT_PROMPT = {".txt"} # Placeholder

# Mode Mapping
SUPPORTED_EXTENSIONS = {
    "model": EXT_MODEL,
    "workflow": EXT_WORKFLOW,
    "prompt": EXT_PROMPT
}

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

def calculate_structure_path(model_path: str, cache_root: str, directories: Dict[str, Any]) -> str:
    """
    Calculates the structured cache path.
    directories value can be string (legacy) or dict (new).
    """
    model_abs = os.path.abspath(model_path)
    model_dir = os.path.dirname(model_abs)
    model_name = os.path.splitext(os.path.basename(model_path))[0]
    
    root_alias = "Uncategorized"
    rel_path = ""
    
    for alias, data in directories.items():
        # Handle both string (legacy) and dict (new) formats
        if isinstance(data, dict):
            root_path = data.get("path", "")
        else:
            root_path = str(data)
            
        root_abs = os.path.abspath(root_path)
        if model_abs.startswith(root_abs):
            root_alias = alias
            try:
                rel_path = os.path.relpath(model_dir, root_abs)
                if rel_path == ".": rel_path = ""
            except ValueError: 
                rel_path = ""
            break
            
    return os.path.join(cache_root, root_alias, rel_path, model_name)

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
            print(f"Failed to load config: {e}")
            return {}

    # --- Migration Logic ---
    settings = data.get("__settings__", {})
    directories = settings.get("directories", {})
    
    migrated = False
    new_directories = {}
    
    for alias, val in directories.items():
        if isinstance(val, str):
            # Legacy: "Alias": "Path" -> "Alias": {"path": "Path", "mode": "model"}
            new_directories[alias] = {"path": val, "mode": "model"}
            migrated = True
        else:
            new_directories[alias] = val
            
    if migrated:
        settings["directories"] = new_directories
        data["__settings__"] = settings
        save_config(data, config_path)
        print("Config migrated to new structure.")
        
    return data

def save_config(data: Dict[str, Any], config_path=CONFIG_FILE):
    """Saves the configuration dict to JSON file."""
    try:
        with open(config_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            # Ensure_ascii=False is good for Non-English characters, adding it since original had it in one place
    except Exception as e:
        print(f"Failed to save config: {e}")
        raise e

# ==========================================
# Workflow Logic
# ==========================================
def validate_comfy_metadata(img):
    """
    Validates if the image contains workflow metadata and identifies source.
    Returns:
        "comfy": ComfyUI workflow (JSON in 'workflow', 'prompt', or Exif)
        "webui": Automatic1111/WebUI parameters (in 'parameters')
        None: No supported metadata found
    """
    try:
        # 1. Check PNG standard keys
        
        # ComfyUI
        if "workflow" in img.info:
            try:
                json.loads(img.info["workflow"])
                return "comfy"
            except: pass
            
        if "prompt" in img.info:
            try:
                json.loads(img.info["prompt"])
                return "comfy"
            except: pass

        # A1111 / WebUI
        # A1111 stores generation info in 'parameters' text chunk. Not JSON.
        if "parameters" in img.info and isinstance(img.info["parameters"], str) and img.info["parameters"].strip():
            return "webui"

        # 2. Check Exif (UserComment)
        if hasattr(img, "_getexif"):
            exif_data = img._getexif()
            if exif_data:
                # 37510 = 0x9286 = UserComment
                user_comment = exif_data.get(37510)
                if user_comment:
                    payload = user_comment
                    # Strip header if present
                    if isinstance(user_comment, bytes):
                        if user_comment.startswith(b'UNICODE\0'):
                            payload = user_comment[8:]
                        elif user_comment.startswith(b'ASCII\0\0\0'):
                            payload = user_comment[8:]
                        
                        # Try decoding
                        candidates = []
                        for enc in ['utf-8', 'utf-16le', 'utf-16be']:
                            try:
                                decoded = payload.decode(enc)
                                if decoded.strip(): candidates.append(decoded)
                            except: pass
                        
                        if candidates:
                            for cand in candidates:
                                s = cand.strip()
                                # Check for ComfyUI JSON
                                if s.startswith("{"):
                                    try:
                                        data = json.loads(s)
                                        if isinstance(data, dict): return "comfy"
                                    except: pass
                                
                                # Check for A1111 Parameters
                                # Heuristic: contains "Steps:" and "Sampler:"
                                if "Steps:" in s and "Sampler:" in s:
                                    return "webui"
                    
                    elif isinstance(user_comment, str):
                        s = user_comment.strip()
                        if s.startswith("{"):
                            try:
                                data = json.loads(s)
                                if isinstance(data, dict): return "comfy"
                            except: pass
                        if "Steps:" in s and "Sampler:" in s:
                            return "webui"

    except Exception as e:
        pass
        
    return None
