import json
import os
import base64

class ComfyNodeBuilder:
    """
    Helper class to generate ComfyUI Node JSON structure for clipboard copy/paste.
    Similar to how ComfyUI-Model-Manager does it.
    """

    NODE_TYPE_MAPPING = {
        "checkpoints": "CheckpointLoaderSimple",
        "loras": "LoraLoaderModelOnly",
        "vae": "VAELoader",
        "controlnet": "ControlNetLoader",
        "clip": "CLIPLoader",
        "unet": "UNETLoader",
        "upscale_models": "UpscaleModelLoader",
        "diffusers": "DiffusersLoader",
        "diffusion_models": "UNETLoader",
    }

    @staticmethod
    def create_node_json(file_path, model_type, root_dir=None):
        """
        Generates a JSON string compatible with ComfyUI's clipboard paste format.
        """
        if root_dir:
            try:
                # Calculate relative path
                filename = os.path.relpath(file_path, root_dir)
                # [Fix] ComfyUI expects standard separators (often forward slashes work best even on Win)
                # But let's keep it native or just ensure it's not absolute.
                # Actually, ComfyUI on Windows is fine with backslashes, but we should ensure.
            except ValueError:
                filename = os.path.basename(file_path)
        else:
            filename = os.path.basename(file_path)
        
        # Special Case: Embeddings -> Just return the embedding string
        if model_type == "embeddings":
             name_without_ext = os.path.splitext(os.path.basename(filename))[0]
             return f"embedding:{name_without_ext}"

        # Standard Node Types
        node_type = ComfyNodeBuilder.NODE_TYPE_MAPPING.get(model_type)
        
        if not node_type:
            # Fallback
            return filename

        # Construct Node Data
        # We create a single node structure.
        
        node_data = {
            "id": 0,
            "type": node_type,
            "pos": [0, 0],
            "size": {"0": 300, "1": 100},
            "flags": {},
            "order": 0,
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {},
            "widgets_values": [filename] 
        }
        
        # ComfyUI clipboard format (minimal)
        payload = {
            "nodes": [node_data],
            "links": [],
            "groups": []
            # NO "version" field to ensure "Append" behavior
        }
        
        return payload

    @staticmethod
    def create_html_clipboard(file_path, model_type, root_dir=None):
        """
        Generates the HTML format required by ComfyUI (hidden span with base64 metadata).
        """
        payload = ComfyNodeBuilder.create_node_json(file_path, model_type, root_dir)
        if isinstance(payload, str) and payload.startswith("embedding:"):
            # Embeddings are just text
            return payload, "text/plain"
            
        json_str = json.dumps(payload)
        b64_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        
        # Exact format from clipboard dump
        # Important: StartFragment/EndFragment comments are used by Chromium to identify the copy paste region
        html = (
            "<html><body>"
            "<!--StartFragment-->"
            f"""<meta charset="utf-8"><div><span data-metadata="{b64_data}"></span></div>"""
            "<!--EndFragment-->"
            "</body></html>"
        )
        
        return html, "text/html"
