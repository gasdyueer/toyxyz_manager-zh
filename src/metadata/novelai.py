import json
from typing import Optional, Dict, Any

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
        # print(f"NAI Extract 错误: {e}")
        pass
        
    return None
