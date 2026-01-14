import os
import time
import shutil
import re
import hashlib
import json
import concurrent.futures
from collections import deque, OrderedDict

from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition, Qt, QBuffer, QByteArray
from PySide6.QtGui import QImage, QImageReader

from .core import (
    QMutexWithLocker, 
    sanitize_filename, 
    calculate_structure_path,
    HAS_MARKDOWNIFY,
    SUPPORTED_EXTENSIONS,
    PREVIEW_EXTENSIONS,
    VIDEO_EXTENSIONS,
    CACHE_DIR_NAME,
    BASE_DIR
)
from .utils.network import NetworkClient

# Optional dependencies
if HAS_MARKDOWNIFY:
    import markdownify

#Fn: Utility
def format_size(s):
    p=2**10; n=0; l={0:'', 1:'K', 2:'M', 3:'G'}
    while s > p: s/=p; n+=1
    return f"{s:.2f} {l.get(n,'T')}B"

# ==========================================
# Region: Media Workers (Image, Thumbnail)
# ==========================================
class ImageLoader(QThread):
    image_loaded = Signal(str, QImage) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = deque()
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self._is_running = True
        
        # [Cache] LRU Cache
        self.cache = OrderedDict()
        self.CACHE_SIZE = 2   # Only keep very recent history (Min capability for comparison)

    def load_image(self, path, target_width=None):
        with QMutexWithLocker(self.mutex):
             # Check cache first
             if path in self.cache:
                 self.cache.move_to_end(path) # Mark as recently used
                 self.image_loaded.emit(path, self.cache[path])
                 return
        
             if os.path.isdir(path):
                 return # Skip directories

             self.queue.clear() # Already locked
             self.queue.append((path, target_width))
             self.condition.wakeOne()
            
    def clear_queue(self):
        with QMutexWithLocker(self.mutex):
            self.queue.clear()

    def remove_from_cache(self, path):
        with QMutexWithLocker(self.mutex):
             if path in self.cache:
                 del self.cache[path]

    def stop(self):
        self._is_running = False
        with QMutexWithLocker(self.mutex):
            self.condition.wakeAll()

    def run(self):
        while self._is_running:
            self.mutex.lock()
            if not self.queue:
                self.condition.wait(self.mutex)
            
            if not self._is_running:
                self.mutex.unlock()
                break

            if self.queue:
                path, target_width = self.queue.popleft()
            else:
                path = None
                target_width = None
            self.mutex.unlock()

            if path:
                t_start = time.time()
                image = QImage()
                if os.path.exists(path):
                    # [Safety] Check file size before full read
                    try:
                        f_size = os.path.getsize(path)
                        if f_size > 200 * 1024 * 1024:
                             # Skip heavy image load
                             pass
                        else:
                            with open(path, "rb") as f:
                                raw_data = f.read()
                            
                            byte_array = QByteArray(raw_data)
                            buffer = QBuffer(byte_array)
                            buffer.open(QBuffer.ReadOnly)
                            
                            reader = QImageReader(buffer)
                            reader.setAutoTransform(True)
                            
                            orig_size = reader.size()
                            tw = target_width if target_width else 1024
                            if orig_size.width() > tw or orig_size.height() > tw:
                                reader.setScaledSize(orig_size.scaled(tw, tw, Qt.KeepAspectRatio))
                            
                            loaded = reader.read()
                            if not loaded.isNull():
                                # [Optimization] Convert to RGB888 (24-bit) to save memory (vs 32-bit ARGB)
                                # Unless it demands transparency, but for thumbnails usually opaque is fine.
                                # If we want to be safe for PNGs with transparency, we might check hasAlphaChannel()
                                if not loaded.hasAlphaChannel():
                                     image = loaded.convertToFormat(QImage.Format_RGB888)
                                else:
                                     # Keep alpha but maybe optimize if needed (Format_ARGB32 is standard)
                                     image = loaded
                            
                            buffer.close()
                    except Exception as e:
                        print(f"Image load error: {e}")

                self.image_loaded.emit(path, image)
                
                # Update Cache
                with QMutexWithLocker(self.mutex):
                    if not image.isNull():
                        self.cache[path] = image
                        self.cache.move_to_end(path)
                        if len(self.cache) > self.CACHE_SIZE:
                            self.cache.popitem(last=False)

# ==========================================
# Thumbnail Worker
# ==========================================
class ThumbnailWorker(QThread):
    finished = Signal(bool, str) # success, message

    def __init__(self, source_path, dest_path, is_video):
        super().__init__()
        self.source_path = source_path
        self.dest_path = dest_path
        self.is_video = is_video

    def run(self):
        try:
            shutil.copy2(self.source_path, self.dest_path)
            if self.is_video:
                self.finished.emit(True, "Video set.")
                return
            self.finished.emit(True, "Thumbnail updated.")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# Region: File System Workers
# ==========================================
class FileScannerWorker(QThread):
    batch_ready = Signal(str, list, list) 
    finished = Signal(dict)

    def __init__(self, base_path, extensions, recursive=True):
        super().__init__()
        self.base_path = base_path
        self.extensions = extensions
        self.recursive = recursive
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        if not os.path.exists(self.base_path):
            self.finished.emit({})
            return

        stack = [self.base_path]
        
        while stack:
            if not self._is_running: return
            
            current_dir = stack.pop()
            
            try:
                with os.scandir(current_dir) as it:
                    dirs_buffer = []
                    files_buffer = []
                    
                    for entry in it:
                        if not self._is_running: return
                        
                        if entry.is_dir():
                            dirs_buffer.append(entry.name)
                            if self.recursive:
                                stack.append(entry.path)
                        
                        elif entry.is_file():
                             if os.path.splitext(entry.name)[1].lower() in self.extensions:
                                 try:
                                     st = entry.stat()
                                     sz = format_size(st.st_size)
                                     dt = time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))
                                     files_buffer.append({
                                         "name": entry.name, 
                                         "path": entry.path, 
                                         "size": sz, 
                                         "date": dt
                                     })
                                 except OSError: 
                                     pass
                    
                    if dirs_buffer or files_buffer:
                         self.batch_ready.emit(current_dir, dirs_buffer, files_buffer)
            
            except OSError:
                continue
                
        if self._is_running:
            self.finished.emit({}) 

# ==========================================
# Search Worker
# ==========================================
class FileSearchWorker(QThread):
    finished = Signal(list) 
    
    def __init__(self, roots, query, extensions):
        super().__init__()
        self.roots = roots if isinstance(roots, list) else [roots]
        self.query = query.lower()
        self.extensions = extensions
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        results = []
        def scan_dir(path):
            if not self._is_running: return
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if not self._is_running: return
                        if entry.is_dir():
                            scan_dir(entry.path)
                        elif entry.is_file():
                             name_lower = entry.name.lower()
                             ext = os.path.splitext(name_lower)[1]
                             if ext in self.extensions:
                                 if self.query in name_lower:
                                     try:
                                         st = entry.stat()
                                         results.append((entry.path, "file", st.st_size, st.st_mtime))
                                     except OSError:
                                         results.append((entry.path, "file", 0, 0))
            except OSError: pass

        for root in self.roots:
            if os.path.exists(root):
                scan_dir(root)
        
        if self._is_running:
            self.finished.emit(results)

# ==========================================
# Region: Network & Metadata Workers
# ==========================================
class ApiClient:
    """Helper class for API interactions"""
    def __init__(self, client: NetworkClient):
        self.client = client

    def fetch_civitai_version(self, file_hash):
        data = self.client.get(f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}").json()
        return data

    def fetch_civitai_model(self, model_id):
        return self.client.get(f"https://civitai.com/api/v1/models/{model_id}").json()

    def fetch_civitai_version_by_id(self, version_id):
        return self.client.get(f"https://civitai.com/api/v1/model-versions/{version_id}").json()

    def fetch_hf_model(self, repo_id):
        return self.client.get(f"https://huggingface.co/api/models/{repo_id}").json()

    def fetch_hf_readme(self, repo_id):
        url = f"https://huggingface.co/{repo_id}/resolve/main/README.md"
        try:
            return self.client.get(url).text
        except Exception:
            return "*No README.md found.*"


class MetadataWorker(QThread):
    batch_started = Signal(list) 
    task_progress = Signal(str, str, int) 
    status_update = Signal(str) 
    model_processed = Signal(bool, str, dict, str) 
    ask_overwrite = Signal(str)

    def __init__(self, mode="auto", targets=None, manual_url=None, civitai_key="", hf_key="", cache_root=None, directories=None, overwrite_behavior='ask'):
        super().__init__()
        self.mode = mode 
        self.targets = targets if targets else []
        self.manual_url = manual_url
        self.overwrite_behavior = overwrite_behavior
        self.directories = directories.copy() if directories else {} 
        self._is_running = True 
        
        self._overwrite_decision = None
        self._wait_mutex = QMutex()
        self._wait_condition = QWaitCondition()
        
        if cache_root:
            self.cache_root = cache_root
        else:
            self.cache_root = CACHE_DIR_NAME

        # [Refactor] Use NetworkClient and ApiClient
        self.net_client = NetworkClient(civitai_key, hf_key)
        self.api_client = ApiClient(self.net_client)

    def stop(self):
        self._is_running = False
        self._resume() 

    def set_overwrite_response(self, response):
        self._overwrite_decision = response
        self._resume()

    def _resume(self):
        self._wait_mutex.lock()
        self._wait_condition.wakeAll()
        self._wait_mutex.unlock()

    def _wait_for_user(self):
        self._wait_mutex.lock()
        self._wait_condition.wait(self._wait_mutex)
        self._wait_mutex.unlock()

    def _check_exists(self, model_path):
        cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
        if not os.path.exists(cache_dir): return False
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        json_file = os.path.join(cache_dir, model_name + ".json")
        has_json = os.path.exists(json_file)
        # Also check for preview
        preview_dir = os.path.join(cache_dir, "preview")
        has_preview = False
        if os.path.exists(preview_dir) and os.listdir(preview_dir):
            has_preview = True
        return has_json or has_preview

    def run(self):
        total_files = len(self.targets)
        success_count = 0
        
        # Initialize global overwrite decision from init param
        global_overwrite = None
        if self.overwrite_behavior in ['yes_all', 'no_all']:
            global_overwrite = self.overwrite_behavior

        self.batch_started.emit(self.targets)

        for idx, model_path in enumerate(self.targets):
            if not self._is_running: break

            try:
                if not model_path or not os.path.exists(model_path): continue

                filename = os.path.basename(model_path)
                
                # Overwrite Check Logic
                if self._check_exists(model_path):
                    should_skip = False
                    if global_overwrite == 'no_all': should_skip = True
                    elif global_overwrite == 'yes_all': should_skip = False
                    else:
                        self.ask_overwrite.emit(filename)
                        self._wait_for_user() 
                        resp = self._overwrite_decision
                        if resp == 'no': should_skip = True
                        elif resp == 'no_all':
                            global_overwrite = 'no_all'
                            should_skip = True
                        elif resp == 'yes_all':
                            global_overwrite = 'yes_all'
                            should_skip = False
                        elif resp == 'cancel': 
                            self.stop()
                            break
                        
                    if should_skip:
                        self.task_progress.emit(model_path, "Skipped (Exists)", 100)
                        self.status_update.emit(f"Skipped: {filename}")
                        continue

                self.task_progress.emit(model_path, "Starting...", 0)
                self.status_update.emit(f"Processing ({idx+1}/{total_files}): {filename}")

                # HuggingFace Processing
                if self.mode == "manual" and self.manual_url and "huggingface.co" in self.manual_url:
                    self._process_huggingface(model_path, self.manual_url)
                    success_count += 1
                    continue

                # Civitai Processing
                model_id = None
                version_id = None

                if self.mode == "auto":
                    self.task_progress.emit(model_path, "Checking Hash...", 10)
                    file_hash, is_cached = self._get_cached_hash(model_path)
                    
                    if not self._is_running: break
                    if is_cached: 
                        self.task_progress.emit(model_path, "Hash Cached", 30)
                    else: 
                        self.task_progress.emit(model_path, "Hashing Done", 30)

                    self.task_progress.emit(model_path, "Searching Civitai...", 40)
                    version_data = self.api_client.fetch_civitai_version(file_hash)
                    model_id = version_data.get("modelId")
                    version_id = version_data.get("id")
                else:
                    if not self.manual_url: raise Exception("No URL.")
                    match_m = re.search(r'models/(\d+)', self.manual_url)
                    match_v = re.search(r'modelVersionId=(\d+)', self.manual_url)
                    if match_m: model_id = match_m.group(1)
                    if match_v: version_id = match_v.group(1)
                
                if not model_id: 
                    self.task_progress.emit(model_path, "Not Found", 0)
                    continue
                
                self.task_progress.emit(model_path, "Fetching Details...", 50)
                model_data = self.api_client.fetch_civitai_model(model_id)
                if not self._is_running: break

                all_versions = model_data.get("modelVersions", [])
                target_version = None
                if version_id:
                     for v in all_versions:
                         if str(v.get("id")) == str(version_id):
                             target_version = v; break
                if not target_version and all_versions: target_version = all_versions[0]

                # Extract Info
                name = model_data.get("name", "Unknown")
                creator = model_data.get("creator", {}).get("username", "Unknown")
                model_url = f"https://civitai.com/models/{model_id}"
                trained_words = target_version.get("trainedWords", []) if target_version else []
                trigger_str = ", ".join(trained_words) if trained_words else "None"
                base_model = target_version.get("baseModel", "Unknown") if target_version else "Unknown"

                model_desc_html = model_data.get("description", "") or ""
                ver_desc_html = target_version.get("description", "") or "" if target_version else ""

                if HAS_MARKDOWNIFY:
                    model_desc_md = markdownify.markdownify(model_desc_html, heading_style="ATX")
                    ver_desc_md = markdownify.markdownify(ver_desc_html, heading_style="ATX")
                else:
                    model_desc_md = model_desc_html
                    ver_desc_md = ver_desc_html

                note_content = []
                note_content.append(f"# {name}")
                note_content.append(f"**Link:**\n[{model_url}]({model_url})")
                note_content.append(f"**Creator:**\n{creator}")
                note_content.append(f"**Base Model:**\n{base_model}")
                note_content.append(f"**Trigger Words:**\n`{trigger_str}`")
                note_content.append("\n---")
                if ver_desc_md:
                    note_content.append("## Version Info")
                    note_content.append(ver_desc_md)
                    note_content.append("\n---")
                note_content.append("## Model Description")
                note_content.append(model_desc_md)

                full_desc = "\n\n".join(note_content)

                self.task_progress.emit(model_path, "Downloading...", 70)
                full_desc = self._process_embedded_images(full_desc, model_path)

                preview_urls = []
                if target_version:
                    preview_urls = [img.get("url") for img in target_version.get("images", []) if img.get("url")]

                if preview_urls:
                    self._download_preview_images(preview_urls, model_path)
                    self._try_set_thumbnail(model_path, preview_urls)

                self.task_progress.emit(model_path, "Done", 100)
                self.model_processed.emit(True, "Processed", {"description": full_desc}, model_path)
                success_count += 1
                
            except Exception as e:
                print(f"Error processing {model_path}: {e}")
                self.task_progress.emit(model_path, "Error", 0)
                self.model_processed.emit(False, str(e), {}, model_path)
            
            time.sleep(0.5)
            
        if self._is_running:
            self.status_update.emit(f"Batch Done. ({success_count}/{total_files} succeeded)")
        else:
            self.status_update.emit("Batch Cancelled.")

    def _get_cached_hash(self, model_path):
        cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        json_path = os.path.join(cache_dir, model_name + ".json")
        try:
            file_mtime = os.path.getmtime(model_path)
        except OSError: return None, False

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cached_hash = data.get("sha256")
                    cached_mtime = data.get("mtime_check")
                    if cached_hash and cached_mtime == file_mtime:
                        return cached_hash, True
            except (OSError, json.JSONDecodeError): pass

        self.status_update.emit("Calculating SHA256 (First run)...")
        calculated_hash = self._calculate_sha256(model_path)
        try:
            new_data = {}
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f: new_data = json.load(f)
                except (OSError, json.JSONDecodeError): pass
            new_data["sha256"] = calculated_hash
            new_data["mtime_check"] = file_mtime
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, indent=4, ensure_ascii=False)
        except Exception as e: print(f"Failed to save hash cache: {e}")
        return calculated_hash, False

    def _process_huggingface(self, model_path, url):
        self.task_progress.emit(model_path, "Fetching HF Info...", 20)
        match = re.search(r'huggingface\.co/([^/]+)/([^/?#]+)', url)
        if not match: raise Exception("Invalid Hugging Face URL format.")
        repo_id = f"{match.group(1)}/{match.group(2)}"
        
        model_data = self.api_client.fetch_hf_model(repo_id)
        author = model_data.get("author", "Unknown")
        tags = model_data.get("tags", [])
        last_modified = model_data.get("lastModified", "Unknown")
        readme_content = self.api_client.fetch_hf_readme(repo_id)
        
        self.task_progress.emit(model_path, "Downloading...", 50)
        
        note_content = []
        note_content.append(f"# {repo_id}")
        note_content.append(f"**Link:**\n[{url}]({url})")
        note_content.append(f"**Author:** {author}")
        note_content.append(f"**Last Modified:** {last_modified}")
        note_content.append(f"**Tags:** `{', '.join(tags)}`")
        note_content.append("\n---")
        note_content.append("## Model Card (README.md)")
        note_content.append(readme_content)
        full_desc = "\n\n".join(note_content)
        
        siblings = model_data.get("siblings", [])
        image_urls = []
        for sibling in siblings:
            fname = sibling.get("rfilename", "")
            if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                img_url = f"https://huggingface.co/{repo_id}/resolve/main/{fname}"
                image_urls.append(img_url)
        if image_urls:
            self._download_preview_images(image_urls, model_path)
            self._try_set_thumbnail(model_path, image_urls)
        
        self.task_progress.emit(model_path, "Done", 100)
        self.model_processed.emit(True, "Hugging Face Data Processed", {"description": full_desc}, model_path)

    def _calculate_sha256(self, path):
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1048576), b""):
                if not self._is_running: return ""
                sha256.update(chunk)
        return sha256.hexdigest().upper()

    def _process_embedded_images(self, text, model_path):
        cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
        embed_dir = os.path.join(cache_dir, "embedded")
        if not os.path.exists(embed_dir): os.makedirs(embed_dir)
        def replace_md(match):
            alt = match.group(1); url = match.group(2)
            # Use safe download method from NetworkClient
            local_path = self.net_client.download_file(url, embed_dir)
            if local_path: return f"![{alt}]({local_path.replace(os.sep, '/')})"
            return match.group(0)
        def replace_html(match):
            pre = match.group(1); url = match.group(2); post = match.group(3)
            local_path = self.net_client.download_file(url, embed_dir)
            if local_path: return f'{pre}{local_path.replace(os.sep, "/")}{post}'
            return match.group(0)
            
        # Simplified regex replacement logic that calls _download_url via NetworkClient
        # But wait, NetworkClient.download_file is blocking, wrapping in try-catch in callback.
        # This part runs in the worker thread, so blocking is acceptable (but slows down).
        # We can accept it for now.
        
        try:
             text = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_md, text)
             text = re.sub(r'(<img[^>]+src=["\'])(.*?)(["\'][^>]*>)', replace_html, text)
        except Exception as e:
             print(f"Error processing embedded images: {e}")
             
        return text

    def _download_preview_images(self, urls, model_path):
        cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
        preview_dir = os.path.join(cache_dir, "preview")
        
        def _download_single(url):
            if not self._is_running: return
            try:
                self.net_client.download_file(url, preview_dir)
            except Exception: pass
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for _ in executor.map(_download_single, urls):
                if not self._is_running: 
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

    def _try_set_thumbnail(self, model_path, preview_urls):
        try:
            if not preview_urls: return
            base_dir = os.path.dirname(model_path)
            model_name = os.path.splitext(os.path.basename(model_path))[0]
            
            for ext in PREVIEW_EXTENSIONS:
                if os.path.exists(os.path.join(base_dir, model_name + ext)):
                    return

            cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
            cache_preview_dir = os.path.join(cache_dir, "preview")
            
            found_file = None
            
            # Simple heuristic: Check if any of the preview URL hashes exist in cache folder
            # NetworkClient uses uuid or original name, so hashing might not match 100% unless we enforced it.
            # In NetworkClient we fallback to basename or uuid.
            # BUT, previous logic used MD5 of URL as filename. 
            # To maintain compatibility or just find *any* image in that folder:
            
            if os.path.exists(cache_preview_dir):
                 files = os.listdir(cache_preview_dir)
                 if files:
                     found_file = os.path.join(cache_preview_dir, files[0])
            
            if found_file:
                ext = os.path.splitext(found_file)[1].lower()
                dest_path = os.path.join(base_dir, model_name + ext)
                shutil.copy2(found_file, dest_path)
                self.status_update.emit(f"Auto-set media: {os.path.basename(dest_path)}")

        except Exception as e: print(f"Failed to auto-set thumbnail: {e}")

# ==========================================
# Model Download Worker
# ==========================================
class ModelDownloadWorker(QThread):
    progress = Signal(str, str, int)
    finished = Signal(str, str)
    error = Signal(str)
    name_found = Signal(str, str)
    ask_collision = Signal(str)

    def __init__(self, url, target_dir, api_key="", task_key=""):
        super().__init__()
        self.url = url
        self.target_dir = target_dir
        self.api_key = api_key
        self.task_key = task_key if task_key else url
        self._is_running = True
        self._decision = None
        self._wait_mutex = QMutex()
        self._wait_condition = QWaitCondition()
        
        # [Phase 2] Use NetworkClient
        self.net_client = NetworkClient(civitai_key=api_key)

    def stop(self):
        # Requests doesn't support easy cancellation of blocking IO.
        # We rely on checking self._is_running in loop (if streaming)
        # NetworkClient.download_file iterates chunks, but we don't have a callback to stop it *inside* yet
        # unless we pass a callback that raises exception?
        # For now, simplistic Stop.
        self._is_running = False
        self._resume()

    def set_collision_decision(self, decision):
        self._decision = decision
        self._resume()

    def _resume(self):
        self._wait_mutex.lock()
        self._wait_condition.wakeAll()
        self._wait_mutex.unlock()

    def run(self):
        try:
            self.progress.emit(self.task_key, "Resolving...", 0)
            
            # 1. Resolve Info (Name, etc.)
            # This logic is specific to Civitai Model IDs structure
            model_id = None
            version_id = None
            match_m = re.search(r'models/(\d+)', self.url)
            match_v = re.search(r'modelVersionId=(\d+)', self.url)
            if match_m: model_id = match_m.group(1)
            if match_v: version_id = match_v.group(1)

            # Determine actual download URL
            download_url = self.url
            if model_id and "civitai.com" in self.url:
                if version_id:
                     download_url = f"https://civitai.com/api/download/models/{version_id}"
                     # Also fetch info for name display using the API URL
                     api_url = f"https://civitai.com/api/v1/model-versions/{version_id}"
                else:
                     # If only model ID, we need to fetch model info to find latest version ID
                     api_url = f"https://civitai.com/api/v1/models/{model_id}"
                     # Default download URL might be this if version not found, but better to resolve
                     try:
                         data = self.net_client.get(api_url).json()
                         if "modelVersions" in data and data["modelVersions"]:
                             latest_ver = data["modelVersions"][0]
                             vid = latest_ver["id"]
                             download_url = f"https://civitai.com/api/download/models/{vid}"
                             version_id = vid # Update for subsequent logic
                     except: pass
            
            # Fetch Name Info (using version_id or model_id if available)
            if model_id:
                try:
                    target_api = f"https://civitai.com/api/v1/model-versions/{version_id}" if version_id else f"https://civitai.com/api/v1/models/{model_id}"
                    data = self.net_client.get(target_api).json()
                    name = data.get("name", "Unknown")
                    if "model" in data: name = f"{data['model'].get('name')} - {name}"
                    
                    self.name_found.emit(self.task_key, f"{name} / {os.path.basename(self.target_dir)}")
                except: pass 
                
            # 2. Collision Check (Pre-download)
            try:
                # Use the resolved download_url
                head = self.net_client.get(download_url, stream=True)
                from email.message import EmailMessage
                fname = None
                if "Content-Disposition" in head.headers:
                     msg = EmailMessage()
                     msg['content-disposition'] = head.headers["Content-Disposition"]
                     fname = msg['content-disposition'].params.get('filename')
                
                # If content-disposition fails, try to get from final URL (handling redirects)
                if not fname:
                     fname = os.path.basename(head.url.split('?')[0])
                
                head.close()
                
                if fname:
                    target_path = os.path.join(self.target_dir, fname)
                    if os.path.exists(target_path):
                         self.ask_collision.emit(fname)
                         self._wait_mutex.lock()
                         self._wait_condition.wait(self._wait_mutex)
                         self._wait_mutex.unlock()
                         
                         if self._decision == 'cancel':
                             self.finished.emit("Cancelled", "")
                             return
                         elif self._decision == 'rename':
                             name, ext = os.path.splitext(fname)
                             fname = f"{name}_{int(time.time())}{ext}"

            except Exception as e:
                print(f"Collision check failed: {e}")
                fname = None

            # 3. Download
            self.progress.emit(self.task_key, "Downloading...", 0)
            
            def progress_cb(dl, total):
                if total > 0:
                    pct = int((dl / total) * 100)
                    self.progress.emit(self.task_key, "Downloading", pct)
            
            final_path = self.net_client.download_file(
                download_url, self.target_dir, filename=fname, progress_callback=progress_cb
            )
            
            if final_path:
                self.finished.emit("Download Complete", final_path)
            else:
                self.error.emit("Download failed (No path returned)")

        except Exception as e:
            self.error.emit(str(e))
