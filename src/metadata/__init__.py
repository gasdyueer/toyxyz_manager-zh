import json
from typing import Dict, Any

from .comfy import parse_comfy_workflow
from .novelai import extract_novelai_data
from .webui import extract_webui_parameters

def validate_metadata_type(img):
    """
    Validates if the image contains workflow metadata and identifies source.
    Returns:
        "comfy": ComfyUI workflow (JSON in 'workflow', 'prompt', or Exif)
        "webui": Automatic1111/WebUI parameters (in 'parameters')
        None: No supported metadata found
    """
    try:
        # 1. Check PNG standard keys
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
    except Exception:
        pass
        
    return None

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
            
    # Fallback: Check LSB (Steganography)
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
                if isinstance(v, (dict, list)):
                    try: v = json.dumps(v)
                    except: pass
                res["etc"][k] = v

    # 3. Check A1111 (Parameters String) fallback
    raw_params = extract_webui_parameters(img)
    
    if raw_params and res["type"] == "unknown":
         res["type"] = "a1111"
         
    res["raw_text"] = raw_params
    return res
