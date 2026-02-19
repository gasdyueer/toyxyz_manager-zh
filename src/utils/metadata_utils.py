import re
import json

def parse_generation_parameters(text):
    """
    Parses generation parameters from a string (A1111 format or similar).
    Returns a dictionary with keys:
    - positive (str)
    - negative (str)
    - parameters (dict): Key-Value pairs of parameters (步数, CFG, etc.)
    - raw_resources (str or None): Raw string of Civitai resources if found
    """
    if not text:
        return {"positive": "", "negative": "", "parameters": {}, "raw_resources": None}

    pos = ""
    neg = ""
    params_str = ""
    
    # Regex split for "Negative prompt:" (case-insensitive)
    parts = re.split(r"Negative prompt:", text, flags=re.IGNORECASE)
    
    if len(parts) > 1:
        pos = parts[0].strip()
        # The rest might contain 步数, so we look into the last part
        remainder = parts[1]
    else:
        # Check if "步数:" exists directly without negative prompt
        steps_match = re.search(r"\b步数:", text, flags=re.IGNORECASE)
        if steps_match:
            pos = text[:steps_match.start()].strip()
            remainder = text[steps_match.start():]
        else:
            pos = text
            remainder = ""
    
    # Now split remainder for "步数:"
    steps_parts = re.split(r"\b步数:", remainder, flags=re.IGNORECASE, maxsplit=1)
    if len(steps_parts) > 1:
        neg = steps_parts[0].strip()
        params_str = "步数:" + steps_parts[1]
    else:
        neg = remainder.strip()
        
    # Parse parameters string
    p_map, raw_resources = _parse_parameters_robust(params_str)
    
    return {
        "positive": pos,
        "negative": neg,
        "parameters": p_map,
        "raw_resources": raw_resources
    }

def _parse_parameters_robust(params_str):
    """
    Parses the parameter string handling JSON arrays/objects correctly.
    Returns: (dict of lowercased keys -> values, raw_civitai_resources string or None)
    """
    if not params_str: return {}, None
    
    result = {}
    raw_resources = None
    
    # State machine for parsing "Key: Value, Key2: Value2"
    # Handling quoted strings and nested JSON brackets/braces
    
    buffer = []
    # We need to split by comma, but NOT inside quotes or brackets
    
    # Actually, the previous logic implementation in ExampleTabWidget was a bit complex state machine.
    # Let's replicate it but improved for standalone use.
    
    # A1111 params are comma-separated "Key: Value" pairs.
    # Value can contain commas if quoted or in JSON.
    
    current_key = None
    current_val_buffer = []
    
    # We effectively want to split by ", " where it signifies a new key.
    # But keys are not known ahead of time.
    # "步数: 20, 采样器: Euler a, ..."
    
    # Let's use the buffer approach from the source file
    
    buffer = []
    stack = [] # For [], {}
    in_quote = False
    
    def commit_buffer(buf):
        full_str = "".join(buf).strip()
        if not full_str: return
        
        # Split by first colon
        if ':' in full_str:
            k, v = full_str.split(':', 1)
            key = k.strip().lower()
            val = v.strip()
            result[key] = val
            
            if key == "civitai resources":
                nonlocal raw_resources
                raw_resources = val
        
    for char in params_str:
        if in_quote:
            buffer.append(char)
            if char == '"': in_quote = False
            continue
            
        if char == '"':
            in_quote = True
            buffer.append(char)
            continue
            
        if char in "[{":
            stack.append(char)
            buffer.append(char)
            continue
            
        if char in "]}":
            if stack: stack.pop()
            buffer.append(char)
            continue
            
        if char == ',':
            if not stack and not in_quote:
                # Potential delimiter
                # A1111 adds space after comma, usually. 
                # commit current buffer
                commit_buffer(buffer)
                buffer = []
                continue
                
        buffer.append(char)
        
    # Commit remaining
    if buffer:
        commit_buffer(buffer)
        
    return result, raw_resources
