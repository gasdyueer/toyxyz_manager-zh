import sys
import os
import json
import gzip
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

# ==========================================
# Enhanced Metadata Parsing
# ==========================================

def extract_novelai_data(img) -> Optional[Dict[str, Any]]:
    """
    Decodes NovelAI's LSB steganography from the Alpha channel.
    Ref: https://github.com/NovelAI/novelai-image-metadata/blob/main/nai_meta.py
    Returns a dictionary of metadata or None.
    """
    try:
        # Check for Alpha channel availability
        if "A" not in img.getbands():
             return None
             
        # Get alpha channel data
        alpha = img.getchannel('A')
        
        # NovelAI LSB encoding walks the alpha channel in a specific order.
        # It's effectively column-major order if treating the flattened array logic correctly?
        # Actually standard implementation often just does:
        # data = list(alpha.getdata()) and takes bit 0.
        # BUT getdata() is row-major. 
        # The NAI reference implementation (linked in comment) typically does:
        # alpha.flatten() (if numpy) which is row-major by default unless "F" order.
        # Wait, the previous functional code had `EfficientLSBReader` handling x,y.
        # Let's restore THAT specific logic which was: calling acc[x,y] with y incrementing inner loop?
        # No, standard Row-Major is y outer, x inner.
        # The previous code I saw (and likely removed) had logic for EfficientLSBReader.
        # Let's assume the previous implementation I saw was correct for this codebase.
        # Snippet I saw earlier:
        # val = self.acc[self.x, self.y]; self.y += 1; if self.y >= h: self.y=0; self.x+=1
        # This implies X is outer loop, Y is inner loop => Column-Major traversal.
        
        class EfficientLSBReader:
            def __init__(self, pixel_access, width, height):
                self.acc = pixel_access
                self.w = width
                self.h = height
                self.x = 0
                self.y = 0
                
            def read_bit(self):
                if self.x >= self.w: return None
                
                # Column-Major Traversal based on previous code snippet logic
                val = self.acc[self.x, self.y]
                
                self.y += 1
                if self.y >= self.h:
                    self.y = 0
                    self.x += 1
                
                # NovelAI uses bitwise_and(val, 1) to hide data in the alpha LSB
                return val & 1

            def read_byte(self):
                byte_val = 0
                for i in range(8):
                    bit = self.read_bit()
                    if bit is None: return None
                    byte_val |= (bit << (7-i))
                return byte_val
                
            def read_bytes(self, count):
                res = bytearray()
                for _ in range(count):
                    b = self.read_byte()
                    if b is None: break
                    res.append(b)
                return res

        w, h = img.size
        # Get fast pixel access
        acc = alpha.load()
        
        # Check size sanity: Magic (15) + Length (4) = 19 bytes = 152 pixels minimum
        if w * h < 152: return None

        reader = EfficientLSBReader(acc, w, h)
        
        # 1. Check Magic "stealth_pngcomp"
        magic = b"stealth_pngcomp"
        read_magic = reader.read_bytes(len(magic))
        if read_magic != magic:
            return None
            
        # 2. Read Length (32-bit Integer, Big Endian)
        len_bytes = reader.read_bytes(4)
        if len(len_bytes) != 4: return None
        
        data_len_bits = int.from_bytes(len_bytes, byteorder='big')
        data_len_bytes = data_len_bits // 8
        
        # 3. Read Payload
        payload = reader.read_bytes(data_len_bytes)
        
        # 4. Decompress
        try:
            import gzip
            json_bytes = gzip.decompress(payload)
            json_str = json_bytes.decode("utf-8")
            data = json.loads(json_str)
            return data
        except Exception:
            return None
        
    except Exception as e:
        # print(f"NAI Extract Error: {e}")
        pass
        
    return None

def parse_comfy_workflow(workflow_data) -> Dict[str, Any]:
    """
    Parses ComfyUI workflow JSON to extract basic generation parameters.
    Attempts to find KSampler, CheckpointLoader, etc.
    """
    result = {}
    
    # Workflow is usually a dict of nodes: { "id": { "inputs": { ... }, "class_type": "..." } }
    # Or a list (API format) or dict with "nodes" inside.
    nodes = {}
    if isinstance(workflow_data, dict):
        if "nodes" in workflow_data: # Saved prompt structure
            for n in workflow_data["nodes"]:
                nodes[str(n.get("id"))] = n 
        else:
            # Maybe API prompt structure { "id": { inputs... class_type... }}
            nodes = workflow_data
    elif isinstance(workflow_data, list):
         # API format list
         for n in workflow_data:
             if isinstance(n, dict):
                 nodes[str(n.get("id", ""))] = n

            
    # Helper to find inputs
    def find_node(class_types):
        for nid, node in nodes.items():
            ctype = node.get("class_type", "")
            if ctype in class_types:
                return node
        return None

    # KSampler
    ksampler = find_node(["KSampler", "KSamplerAdvanced", "KSampler (Efficient)"])
    if ksampler and "inputs" in ksampler:
        inputs = ksampler["inputs"]
        result["seed"] = inputs.get("seed") or inputs.get("noise_seed")
        result["steps"] = inputs.get("steps")
        result["cfg"] = inputs.get("cfg")
        result["sampler"] = inputs.get("sampler_name")
        result["scheduler"] = inputs.get("scheduler")
        
        # Try to trace prompts
        # inputs["positive"] is usually [link_id, slot] in UI format, or [node_id, slot] in API format?
        # In API format (which "prompt" is), it is [node_id, output_slot] e.g. ["3", 0]
        
        def get_text_from_node_id(nid):
            if not nid: return ""
            n = nodes.get(str(nid))
            if not n: return ""
            
            # Simple case: CLIPTextEncode
            if n.get("class_type") in ["CLIPTextEncode", "CLIPTextEncodeSDXL", "ShowText", "Text"]:
                 val = n.get("inputs", {}).get("text")
                 if isinstance(val, str): return val
                 # Sometimes text is a widget widget_values if checking UI format, but we prefer API prompt logic now
                 
            # Recursive/Intermediate nodes (ConditioningCombine, etc) - Too complex for basic parser
            return ""

        pos_link = inputs.get("positive")
        neg_link = inputs.get("negative")
        
        # API format: pos_link is [node_id, slot]
        if isinstance(pos_link, list) and len(pos_link) > 0:
             # Just look at the node it comes from.
             # Note: It might be a Conditioning node (SetArea, Combine). 
             # We just check if that source node IS a text encode. If not, we might give up or dig deeper.
             # For now, simple direct link check.
             result["positive"] = get_text_from_node_id(pos_link[0])
             
        if isinstance(neg_link, list) and len(neg_link) > 0:
             result["negative"] = get_text_from_node_id(neg_link[0])
             
    # Fallback: If connection tracing failed (or intermediate nodes blocked us),
    # just grab ALL CLIPTextEncode nodes and put them in positive?
    if not result.get("positive") and not result.get("negative"):
        # Gather all text
        all_texts = []
        for nid, node in nodes.items():
            if node.get("class_type") in ["CLIPTextEncode", "CLIPTextEncodeSDXL"]:
                t = node.get("inputs", {}).get("text")
                if isinstance(t, str) and t.strip():
                    all_texts.append(t)
        
        if all_texts:
            # Heuristic: Longest is positive? Or just join them?
            # Usually strict negative prompts are separate. 
            # Let's just join them all as positive for visibility
            result["positive"] = "\n---\n".join(all_texts)

    # Checkpoint
    ckpt = find_node(["CheckpointLoaderSimple", "CheckpointLoader"])
    if ckpt and "inputs" in ckpt:
        result["model"] = ckpt["inputs"].get("ckpt_name")
        
    # LoRAs (Simple scan)
    loras = []
    for nid, node in nodes.items():
        ctype = node.get("class_type", "")
        if ctype == "LoraLoader":
            name = node.get("inputs", {}).get("lora_name")
            strength = node.get("inputs", {}).get("strength_model")
            if name:
                 loras.append(f"{name} ({strength})")
    
    if loras:
        result["loras"] = loras
        
    return result

def standardize_metadata(img) -> Dict[str, Any]:
    """
    Unified metadata extractor. Returns standardized struct.
    {
       "type": "a1111" | "comfy" | "novelai" | "unknown",
       "main": { "steps":..., "sampler":..., "cfg":..., "seed":..., "schedule":... },
       "model": { "checkpoint":..., "loras": [], "resources": [] },
       "prompts": { "positive":..., "negative":... },
       "etc": { ... }
    }
    """
    res = {
        "type": "unknown",
        "main": {},
        "model": {"checkpoint": "", "loras": [], "resources": []},
        "prompts": {"positive": "", "negative": ""},
        "etc": {}
    }
    
    # 1. Check ComfyUI Workflow (Graph)
    workflow = None
    # Prioritize "prompt" (API format) because it has clean input keys (seed, steps)
    # "workflow" (UI format) often has raw widgets_values lists which are hard to parse.
    if "prompt" in img.info:
        try: workflow = json.loads(img.info["prompt"])
        except: pass
        
    if not workflow and "workflow" in img.info:
        try: workflow = json.loads(img.info["workflow"])
        except: pass
        
    if workflow:
        res["type"] = "comfy"
        data = parse_comfy_workflow(workflow)
        res["main"] = {
            "steps": data.get("steps"),
            "sampler": data.get("sampler"),
            "cfg": data.get("cfg"),
            "seed": data.get("seed"),
            "schedule": data.get("scheduler")
        }
        res["model"]["checkpoint"] = data.get("model")
        res["model"]["loras"] = data.get("loras", [])
        res["prompts"]["positive"] = data.get("positive", "")
        res["prompts"]["negative"] = data.get("negative", "")
        
    # 2. Check NovelAI (Text Chunks Only - User Request)
    nai_data = None
    for key in ["Comment", "Description", "Software"]:
        if key in img.info:
            try:
                text = img.info[key]
                if not text.strip().startswith("{"): continue
                
                data = json.loads(text)
                # Heuristic to confirm NAI
                if "n_samples" in data or "uc" in data or "steps" in data:
                        nai_data = data
                        break
            except: pass
            
    # Fallback: Check LSB (Steganography) if no text metadata found AND no other metadata known
    # User Request: "If other metadata exists, do not do LSB check."
    if not nai_data and res["type"] == "unknown":
        nai_data = extract_novelai_data(img)
        
    if nai_data:
        res["type"] = "novelai"
        
        # NovelAI Reference: "Comment" inside JSON might be nested JSON string.
        # MERGE logic for robustness
        if "Comment" in nai_data and isinstance(nai_data["Comment"], str):
             try: 
                 comment_data = json.loads(nai_data["Comment"])
                 if isinstance(comment_data, dict):
                     nai_data.update(comment_data)
             except: pass
             
        # Map NAI fields
        # Note: "scale" is CFG in NAI. "steps" is steps.
        res["main"] = {
            "steps": nai_data.get("steps"),
            "sampler": nai_data.get("sampler"),
            "cfg": nai_data.get("scale"),
            "seed": nai_data.get("seed"),
            "schedule": "Euler" # NAI default usually
        }
        res["prompts"]["positive"] = nai_data.get("prompt", "")
        # NAI uses "uc" for negative prompt
        res["prompts"]["negative"] = nai_data.get("uc", "")
        
        # Everything else to ETC
        exclude = {"prompt", "uc", "steps", "sampler", "scale", "seed", "Comment", "Description", "Source", "Software"}
        for k, v in nai_data.items():
            if k not in exclude:
                # Format dictionaries nicer if possible
                if isinstance(v, (dict, list)):
                    try: v = json.dumps(v)
                    except: pass
                res["etc"][k] = v

    # 3. Check A1111 (Parameters String) fallback
    raw_params = ""
    if "parameters" in img.info: 
        raw_params = img.info["parameters"]
    elif img.format in ["JPEG", "WEBP"] and hasattr(img, "_getexif"):
        # Try Exif
        try:
             exif_data = img._getexif()
             if exif_data:
                user_comment = exif_data.get(37510)
                if user_comment:
                    payload = user_comment
                    if isinstance(user_comment, bytes):
                        if user_comment.startswith(b'UNICODE\0'): payload = user_comment[8:]
                        elif user_comment.startswith(b'ASCII\0\0\0'): payload = user_comment[8:]
                        
                        candidates = []
                        for enc in ['utf-8', 'utf-16le', 'utf-16be']:
                            try:
                                decoded = payload.decode(enc)
                                if not decoded.strip(): continue
                                printable = sum(1 for c in decoded if c.isprintable() or c in '\n\r\t')
                                ratio = printable / len(decoded)
                                candidates.append((ratio, decoded))
                            except: pass
                        if candidates:
                            candidates.sort(key=lambda x: x[0], reverse=True)
                            if candidates[0][0] > 0.8: raw_params = candidates[0][1]
                    elif isinstance(user_comment, str):
                        raw_params = user_comment
        except: pass
    
    if raw_params and res["type"] == "unknown":
         res["type"] = "a1111"
         
    res["raw_text"] = raw_params
    return res
