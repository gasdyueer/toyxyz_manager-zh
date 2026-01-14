import json
from typing import Dict, Any

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
        
        def get_text_from_node_id(nid):
            if not nid: return ""
            n = nodes.get(str(nid))
            if not n: return ""
            
            # Simple case: CLIPTextEncode
            if n.get("class_type") in ["CLIPTextEncode", "CLIPTextEncodeSDXL", "ShowText", "Text"]:
                 val = n.get("inputs", {}).get("text")
                 if isinstance(val, str): return val
                 
            return ""

        pos_link = inputs.get("positive")
        neg_link = inputs.get("negative")
        
        # API format: pos_link is [node_id, slot]
        if isinstance(pos_link, list) and len(pos_link) > 0:
             result["positive"] = get_text_from_node_id(pos_link[0])
             
        if isinstance(neg_link, list) and len(neg_link) > 0:
             result["negative"] = get_text_from_node_id(neg_link[0])
             
    # Fallback: Just grab ALL CLIPTextEncode nodes
    if not result.get("positive") and not result.get("negative"):
        all_texts = []
        for nid, node in nodes.items():
            if node.get("class_type") in ["CLIPTextEncode", "CLIPTextEncodeSDXL"]:
                t = node.get("inputs", {}).get("text")
                if isinstance(t, str) and t.strip():
                    all_texts.append(t)
        
        if all_texts:
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
