import os
import hashlib
import json
import logging
import shutil
from ..core import calculate_structure_path, PREVIEW_EXTENSIONS, CACHE_DIR_NAME

class FileService:
    """
    Handles file operations: hashing, caching metadata, preview management.
    """
    def __init__(self, cache_root=None):
        self.cache_root = cache_root if cache_root else CACHE_DIR_NAME

    def calculate_sha256(self, path, progress_callback=None, stop_event=None):
        """
        Calculates SHA256 of a file.
        stop_event: Object with .is_app_running() or similar method/flag if needed, 
                    or simply a callable that returns bool.
        """
        sha256 = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1048576), b""):
                    if stop_event and stop_event(): return ""
                    sha256.update(chunk)
            return sha256.hexdigest().upper()
        except OSError as e:
            logging.error(f"[FileService] Hash calculation error: {e}")
            return ""

    def get_cached_hash(self, model_path, directories, cache_mode="model", status_signal=None):
        """
        Returns (hash, is_cached_bool).
        Manages the .json cache sidecard in the cache structure.
        """
        cache_dir = calculate_structure_path(model_path, self.cache_root, directories, mode=cache_mode)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        json_path = os.path.join(cache_dir, model_name + ".json")
        
        try:
            file_mtime = os.path.getmtime(model_path)
        except OSError: return None, False

        # Read Cache
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cached_hash = data.get("sha256")
                    cached_mtime = data.get("mtime_check")
                    if cached_hash and cached_mtime == file_mtime:
                        return cached_hash, True
            except (OSError, json.JSONDecodeError): pass

        # Calculate
        if status_signal: status_signal.emit("Calculating SHA256 (First run)...")
        
        calculated_hash = self.calculate_sha256(model_path)
        if not calculated_hash: return None, False

        # Write Cache
        try:
            new_data = {}
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f: new_data = json.load(f)
                except Exception: pass
            
            new_data["sha256"] = calculated_hash
            new_data["mtime_check"] = file_mtime
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.warning(f"[FileService] Failed to save hash cache: {e}")

        return calculated_hash, False

    def check_metadata_exists(self, model_path, directories, cache_mode="model"):
        """Checks if metadata json or preview exists in cache."""
        cache_dir = calculate_structure_path(model_path, self.cache_root, directories, mode=cache_mode)
        if not os.path.exists(cache_dir): return False
        
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        json_file = os.path.join(cache_dir, model_name + ".json")
        
        has_json = os.path.exists(json_file)
        
        preview_dir = os.path.join(cache_dir, "preview")
        has_preview = False
        if os.path.exists(preview_dir) and os.listdir(preview_dir):
            has_preview = True
            
        return has_json or has_preview

    def get_cache_paths(self, model_path, directories, cache_mode="model"):
        cache_dir = calculate_structure_path(model_path, self.cache_root, directories, mode=cache_mode)
        return {
            "root": cache_dir,
            "preview": os.path.join(cache_dir, "preview"),
            "embedded": os.path.join(cache_dir, "embedded")
        }

    def try_set_thumbnail_from_cache(self, model_path, directories, cache_mode="model"):
        """Attempts to copy a cached preview image to the model directory."""
        try:
            base_dir = os.path.dirname(model_path)
            model_name = os.path.splitext(os.path.basename(model_path))[0]
            
            # Check if exists
            for ext in PREVIEW_EXTENSIONS:
                if os.path.exists(os.path.join(base_dir, model_name + ext)):
                    return False

            cache_dir = calculate_structure_path(model_path, self.cache_root, directories, mode=cache_mode)
            cache_preview_dir = os.path.join(cache_dir, "preview")
            
            found_file = None
            if os.path.exists(cache_preview_dir):
                 files = os.listdir(cache_preview_dir)
                 if files:
                     found_file = os.path.join(cache_preview_dir, files[0])
            
            if found_file:
                ext = os.path.splitext(found_file)[1].lower()
                dest_path = os.path.join(base_dir, model_name + ext)
                shutil.copy2(found_file, dest_path)
                return dest_path
        except Exception as e:
            logging.warning(f"[FileService] Failed to auto-set thumbnail: {e}")
        return None
