
import sys
import os
import json
import gzip
from PIL import Image
import traceback

def extract_novelai_debug(img):
    print("\n--- NovelAI Debug ---")
    if "A" not in img.getbands():
        print("No Alpha channel found.")
        return None
        
    alpha = img.getchannel('A')
    
    # Check Magic first with simple iterator
    # Try Both Row-Major and Column-Major (Transposed)
    
    modes = [("Row-Major", list(alpha.getdata())), 
             ("Column-Major", [alpha.getpixel((x, y)) for x in range(img.width) for y in range(img.height)])]
             
    for name, pixels in modes:
        print(f"Testing {name}...")
        try:
             # Extract first 30 bytes
            bits = []
            for p in pixels[:240]: # 30 bytes * 8
                bits.append(str(p & 1))
            
            chars = []
            for i in range(0, len(bits), 8):
                byte = bits[i:i+8]
                if len(byte)<8: break
                chars.append(int("".join(byte), 2))
                
            raw_bytes = bytes(chars)
            print(f"First 30 bytes ({name}): {raw_bytes}")
            
            if b"stealth_pngcomp" in raw_bytes:
                print(f"MATCH FOUND in {name}!")
                
                # Check Magic strictly
                # We need to create a reader similar to core.py logic to be precise
                # Or just quick hack: find index of magic, read length, decode.
                
                magic_idx = raw_bytes.find(b"stealth_pngcomp")
                # Magic (15) + Length (4)
                # Need consistent bitstream.
                
                # Let's reconstruct the bits fully for this mode
                full_bits = []
                for p in pixels:
                    full_bits.append(str(p & 1))
                
                # Chars
                full_chars = []
                for i in range(0, len(full_bits), 8):
                    byte = full_bits[i:i+8]
                    if len(byte) < 8: break
                    full_chars.append(chr(int("".join(byte), 2)))
                full_stream_str_latin = "".join(full_chars)
                # This is a string representation of bytes.
                # Convert back to bytes for finding offsets easily?
                # Actually, let's use the byte array method from before but for ALL pixels.
                
                # Better: Use the same helper class approach as core.py for clarity
                class DBGReader:
                    def __init__(self, pixels):
                        self.pixels = pixels
                        self.idx = 0
                        self.total = len(pixels)
                    def read_bytes(self, count):
                        val = bytearray()
                        for _ in range(count):
                            if self.idx + 8 > self.total: break
                            b_val = 0
                            for k in range(8):
                                bit = self.pixels[self.idx+k] & 1
                                b_val |= (bit << (7-k))
                            self.idx += 8
                            val.append(b_val)
                        return val

                r = DBGReader(pixels)
                # 1. Magic
                magic = b"stealth_pngcomp"
                rm = r.read_bytes(len(magic))
                if rm == magic:
                    print("  Magic verified.")
                    # 2. Length
                    lb = r.read_bytes(4)
                    dl_bits = int.from_bytes(lb, 'big')
                    dl_bytes = dl_bits // 8
                    print(f"  Payload Length: {dl_bytes} bytes")
                    
                    # 3. Payload
                    payload = r.read_bytes(dl_bytes)
                    
                    try:
                        import gzip
                        json_bytes = gzip.decompress(payload)
                        json_str = json_bytes.decode("utf-8")
                        data = json.loads(json_str)
                        print(f"  DECODED JSON KEYS: {list(data.keys())}")
                        print(f"  FULL JSON: {json.dumps(data, indent=2)}")
                    except Exception as e:
                        print(f"  Decompression Failed: {e}")
                else:
                    print(f"  Magic mismatch in detailed read: {rm}")
                    
                break # Matched one mode, stop.
        except Exception as e:
            print(f"Error in {name}: {e}")
            
    return None

def analyze_image(path):
    print(f"Analyzing: {path}")
    if not os.path.exists(path):
        print("File not found.")
        return

    try:
        with Image.open(path) as img:
            print(f"Format: {img.format}, Mode: {img.mode}, Size: {img.size}")
            print(f"Info Keys: {list(img.info.keys())}")
            
            if "parameters" in img.info:
                print(f"Parameters (First 100 chars): {img.info['parameters'][:100]}...")
                
            if "workflow" in img.info:
                print("\n--- ComfyUI Debug ---")
                try:
                    wf = json.loads(img.info["workflow"])
                    print(f"Workflow Keys: {list(wf.keys())}")
                    
                    # Dump Nodes and their Types
                    nodes = {}
                    if "nodes" in wf:
                        # API format usually has "nodes" as list? Or "nodes" as dict?
                        # Standard .png save from Comfy is API format (workflow object) OR prompt object?
                        # Actually img.info['workflow'] is usually the UI graph (nodes list).
                        # img.info['prompt'] is the execution graph (id -> inputs).
                        
                        # Let's check what we have.
                        if isinstance(wf, dict) and "nodes" in wf:
                            # UI Format
                            print("Format: UI Graph (nodes list)")
                            for n in wf["nodes"]:
                                n_type = n.get("type", "Unknown")
                                n_id = n.get("id", "?")
                                print(f"  Node {n_id}: {n_type}")
                                # Check for widgets values
                                if "widgets_values" in n:
                                    print(f"    Widgets: {n['widgets_values']}")
                        elif isinstance(wf, dict):
                            # Maybe API Format (ID -> ClassType)?
                            print("Format: API Graph (or unknown dict)")
                            for nid, nval in wf.items():
                                if isinstance(nval, dict):
                                    ctype = nval.get("class_type", "Unknown")
                                    print(f"  Node {nid}: {ctype}")
                                    if "inputs" in nval:
                                        print(f"    Inputs: {nval['inputs']}")
                                        
                except Exception as e:
                    print(f"Workflow parse error: {e}")

            if "prompt" in img.info:
                 print("\n--- ComfyUI Prompt (API) Debug ---")
                 try:
                     pr = json.loads(img.info["prompt"])
                     print("Format: API Format")
                     for nid, nval in pr.items():
                        c = nval.get("class_type", "?")
                        print(f"  Node {nid}: {c}")
                        if "inputs" in nval:
                             # Print only interesting inputs
                             inp = nval["inputs"]
                             interesting = {k: v for k, v in inp.items() if k in ["steps", "seed", "cfg", "sampler_name", "scheduler", "ckpt_name"]}
                             if interesting:
                                 print(f"    Relevant Inputs: {interesting}")
                 except: pass

            # Exif
                
            # Exif
            if hasattr(img, "_getexif"):
                exif = img._getexif()
                if exif:
                    print("Exif found.")
                    # 37510 UserComment
                    if 37510 in exif:
                        print("UserComment tag present.")
                        
            extract_novelai_debug(img)
            
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_metadata.py <image_path>")
    else:
        analyze_image(sys.argv[1])
