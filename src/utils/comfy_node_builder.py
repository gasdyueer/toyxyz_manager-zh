import json
import os
import base64

class ComfyNodeBuilder:
    """
    [Role]
    Helper class to generate ComfyUI Node JSON structure for clipboard copy/paste.
    It bridges the gap between the file manager and ComfyUI by creating a node representation
    that ComfyUI can recognize and paste directly into the canvas.

    [How it works]
    1. Maps internal model types (e.g., 'checkpoints') to ComfyUI class names (e.g., 'CheckpointLoaderSimple').
    2. Constructs a JSON object representing the node with the selected file pre-selected.
    3. Encodes this JSON into a specific HTML format that ComfyUI's clipboard handler expects.
    """

    # Mapping from internal folder types to ComfyUI Node Class 名称s
    NODE_TYPE_MAPPING = {
        "checkpoints": "CheckpointLoaderSimple",
        "loras": "LoraLoader模型Only",
        "vae": "VAELoader",
        "controlnet": "ControlNetLoader",
        "clip": "CLIPLoader",
        "unet": "UNETLoader",
        "upscale_models": "Upscale模型Loader",
        "diffusers": "DiffusersLoader",
        "diffusion_models": "UNETLoader",
    }

    @staticmethod
    def create_node_json(file_path, model_type, root_dir=None):
        """
        [Logic]
        Generates the raw JSON payload for a single ComfyUI node.
        
        Args:
            file_path: Absolute path to the model file.
            model_type: The category of the model (used to determine node type).
            root_dir: Optional root directory to calculate relative paths (if needed).
            
        Returns:
            dict: A dictionary structure matching ComfyUI's serialized node format.
        """
        if root_dir:
            try:
                # Calculate relative path
                filename = os.path.relpath(file_path, root_dir)
                # [Fix] ComfyUI expects standard separators (often forward slashes work best even on Win)
                # But let's keep it native or just ensure it's not absolute.
                # Actually, ComfyUI on Windows is fine with backslashes, but we should ensure.
            except Value错误:
                filename = os.path.basename(file_path)
        else:
            filename = os.path.basename(file_path)
        
        # Special Case: Embeddings -> Just return the embedding string
        if model_type == "embeddings":
             name_without_ext = os.path.splitext(os.path.basename(filename))[0]
             return f"embedding:{name_without_ext}"

        # Standard Node 类型s
        node_type = ComfyNodeBuilder.NODE_TYPE_MAPPING.get(model_type)
        
        if not node_type:
            # Fallback
            return filename

        # Construct Node Data
        # We create a single node structure with 'widgets_values' set to the filename.
        # This ensures that when the node is created, it automatically selects this specific model file.
        
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
            "widgets_values": [filename] # [Critical] Pre-selects the file in the node's dropdown
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
        [Logic]
        ComfyUI does not use plain JSON for pasting nodes. It inspects the clipboard for
        a specific HTML structure containing the JSON data encoded in Base64.
        
        Format:
        <html><body>
        <!--StartFragment-->
        <span data-metadata="BASE64_ENCODED_JSON"></span>
        <!--EndFragment-->
        </body></html>
        
        Returns:
            tuple: (html_string, mime_type)
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
