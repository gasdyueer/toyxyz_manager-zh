
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
    """
    raw_params = ""
    if "parameters" in img.info: 
        raw_params = img.info["parameters"]
    elif img.format in ["JPEG", "WEBP"] and hasattr(img, "_getexif"):
        # Try Exif
        try:
             exif_data = img._getexif()
             if exif_data:
                # 37510 = 0x9286 = UserComment
                user_comment = exif_data.get(37510)
                if user_comment:
                    payload = user_comment
                    if isinstance(user_comment, bytes):
                        if user_comment.startswith(b'UNICODE\0'): payload = user_comment[8:]
                        elif user_comment.startswith(b'ASCII\0\0\0'): payload = user_comment[8:]
                        # Try decoding
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
    return raw_params
