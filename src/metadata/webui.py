
def parse_webui_parameters(text: str) -> str:
    """
    Parses A1111's parameters string.
    Currently just returns the raw string as it's unstructured text, 
    but this placeholder allows future structured parsing.
    """
    return text

def extract_webui_parameters(img) -> str:
    """
    Extracts raw parameters string from image info or Exif.
    Scans multiple sources to ensure robustness (PNG/JPEG/WEBP).
    """
    candidates = []

    # 1. Scan img.info values (Standard + Comments)
    if "parameters" in img.info and isinstance(img.info["parameters"], str):
        candidates.append(img.info["parameters"])
    
    for k, v in img.info.items():
        if k == "parameters": continue
        if isinstance(v, str): candidates.append(v)
    
    # helper to check string
    def is_valid_params(text):
        if not text: return False
        s = text.lower()
        # "Steps: 20, Sampler: Euler a"
        if text.strip().startswith("{") and text.strip().endswith("}"): return True
        return "steps:" in s and "sampler:" in s

    # Check candidates from info
    for c in candidates:
        if is_valid_params(c): return c

    # 2. Exif Parsing
    # We collect all potential user comments from various Exif sources
    exif_values = []

    # Source A: Modern getexif() + Exif IFD
    if hasattr(img, "getexif"):
        try:
            exif = img.getexif()
            if exif:
                # Base IFD
                for k, v in exif.items():
                    if k in [37510, 0x9286, 0x9c9c]: exif_values.append(v)
                
                # Exif IFD (0x8769 = 34665)
                if 34665 in exif:
                    try:
                        exif_ifd = exif.get_ifd(34665)
                        if exif_ifd:
                            for k, v in exif_ifd.items():
                                if k in [37510, 0x9286, 0x9c9c]: exif_values.append(v)
                    except: pass
        except: pass

    # Source B: Legacy _getexif() (Flattened)
    if hasattr(img, "_getexif"):
        try:
            legacy = img._getexif()
            if legacy:
                 for k, v in legacy.items():
                    if k in [37510, 0x9286, 0x9c9c]: exif_values.append(v)
        except: pass
    
    # Process Exif Candidates
    for val in exif_values:
        decoded = ""
        if isinstance(val, bytes):
            # Strip Headers
            payload = val
            if payload.startswith(b'UNICODE\0'): payload = payload[8:]
            elif payload.startswith(b'ASCII\0\0\0'): payload = payload[8:]
            
            # Decode
            for enc in ['utf-8', 'utf-16le', 'utf-16be', 'ascii']:
                try:
                    res = payload.decode(enc)
                    # Key Fix: Only accept if it looks like parameters
                    if is_valid_params(res):
                        decoded = res
                        break
                    # Soft Fallback: If we assume it's just a prompt but valid text, capture it?
                    # But for now, we want to return the PARAMS. 
                    # If we return partial text, it might fail the check later.
                    # Let's trust is_valid_params.
                except: pass
        elif isinstance(val, str):
            decoded = val
            
        if is_valid_params(decoded):
            return decoded

    return ""
