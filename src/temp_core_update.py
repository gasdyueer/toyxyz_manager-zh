
# ==========================================
# Enhanced Metadata Parsing
# ==========================================

def extract_novelai_data(img) -> Optional[Dict[str, Any]]:
    """
    Decodes NovelAI's LSB steganography from the Alpha channel.
    Returns a dictionary of metadata or None.
    """
    try:
        # Check if alpha channel exists
        if img.mode not in ("RGBA", "LA"):
             img = img.convert("RGBA")
        
        alpha = img.split()[-1]
        # Get pixels
        pixels = list(alpha.getdata())
        
        # Read LSBs
        bits = []
        for p in pixels:
            bits.append(str(p & 1))
        
        # Convert to string (8 bits per char)
        chars = []
        for i in range(0, len(bits), 8):
            byte = bits[i:i+8]
            if len(byte) < 8: break
            char_code = int("".join(byte), 2)
            if char_code == 0: break # Null terminator
            chars.append(chr(char_code))
            
        full_text = "".join(chars)
        
        # NovelAI data is JSON
        if full_text.startswith("{"):
            return json.loads(full_text)
            
    except Exception as e:
        # print("NovelAI parse err:", e) # Too verbose for regular logs
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
            # API prompt structure?
            # Actually standard workflow.json usually has "nodes": [...]
            # But "prompt" (API) is { "id": { inputs... class_type... }}
            # Let's try to handle both if possible, or assume workflow format.
            # Assuming 'prompt' structure first as it's cleaner for params
            nodes = workflow_data
            
    # Helper to find inputs
    def find_node(class_types):
        for nid, node in nodes.items():
            ctype = node.get("class_type", "")
            if ctype in class_types:
                return node
        return None

    # KSampler
    ksampler = find_node(["KSampler", "KSamplerAdvanced"])
    if ksampler and "inputs" in ksampler:
        inputs = ksampler["inputs"]
        result["seed"] = inputs.get("seed") or inputs.get("noise_seed")
        result["steps"] = inputs.get("steps")
        result["cfg"] = inputs.get("cfg")
        result["sampler"] = inputs.get("sampler_name")
        result["scheduler"] = inputs.get("scheduler")
        
    # Checkpoint
    ckpt = find_node(["CheckpointLoaderSimple", "CheckpointLoader"])
    if ckpt and "inputs" in ckpt:
        result["model"] = ckpt["inputs"].get("ckpt_name")
        
    # LoRAs (Simple scan)
    # Finding chains is hard without graph walking. 
    # Let's just gather all LoraLoader weights.
    loras = []
    for nid, node in nodes.items():
        if node.get("class_type") == "LoraLoader":
            name = node.get("inputs", {}).get("lora_name")
            strength = node.get("inputs", {}).get("strength_model")
            if name:
                 loras.append(f"{name} ({strength})")
    
    if loras:
        result["loras"] = loras
        
    # Text Prompts (Difficult to distinguish Pos/Neg without linking)
    # Heuristic: Usually CLIPTextEncode
    # Without full graph, maybe we just grab all texts?
    # Or skip for now. The User request emphasized standard params.
    
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
    # Note: validate_comfy_metadata returns string type, but here we want data.
    workflow = None
    if "workflow" in img.info:
        try: workflow = json.loads(img.info["workflow"])
        except: pass
    elif "prompt" in img.info:
        try: workflow = json.loads(img.info["prompt"])
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
        # Prompts are hard in Comfy without walking, skipping for now
        
    # 2. Check NovelAI (Steganography)
    nai_data = extract_novelai_data(img)
    if nai_data:
        res["type"] = "novelai"
        # Map NAI fields
        res["main"] = {
            "steps": nai_data.get("steps"),
            "sampler": nai_data.get("sampler"),
            "cfg": nai_data.get("scale"),
            "seed": nai_data.get("seed"),
            "schedule": "Euler" # NAI default usually? Or in sampler
        }
        res["prompts"]["positive"] = nai_data.get("prompt", "")
        res["prompts"]["negative"] = nai_data.get("uc", "")
        # NAI Model? usually 'software' or hidden
        
        # Everything else to ETC
        exclude = {"prompt", "uc", "steps", "sampler", "scale", "seed"}
        for k, v in nai_data.items():
            if k not in exclude:
                res["etc"][k] = v

    # 3. Check A1111 (Parameters String) - Fallback/Overlay
    # Even ComfyUI/NovelAI images might have PNG text chunks for compat.
    # We allow this to overwrite/fill gaps.
    raw_params = ""
    if "parameters" in img.info: raw_params = img.info["parameters"]
    # Exif fallback handled in example.py, usually passed as text.
    # But here we are standardization logic.
    # Let's assume ExampleTabWidget logic for text extraction is moved here or we assume text is passed?
    # Actually, let's keep robust text parsing in ExampleTab, but here provide specific object extraction.
    
    # If standard A1111 found (and type is unknown or we want to mix?)
    if raw_params and res["type"] == "unknown":
         res["type"] = "a1111"
         # Parsing logic would go here, but currently it's in ExampleTabWidget._display_parameters
         # Ideally we move that here for unifying.
         # For this iteration, let's keep A1111 logic in UI layer or just flag it.
         
    return res
