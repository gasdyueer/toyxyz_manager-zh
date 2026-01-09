import os
import time
import shutil
import re
import hashlib
import json
import concurrent.futures
from collections import deque
import requests

from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition, Qt
from PySide6.QtGui import QImage, QImageReader

from .core import (
    QMutexWithLocker, 
    sanitize_filename, 
    extract_video_frame, 
    calculate_structure_path,
    HAS_MARKDOWNIFY,
    SUPPORTED_EXTENSIONS,
    PREVIEW_EXTENSIONS,
    VIDEO_EXTENSIONS,
    CACHE_DIR_NAME,
    BASE_DIR
)

# Optional dependencies
if HAS_MARKDOWNIFY:
    import markdownify

# ==========================================
# Image Loader
# ==========================================
class ImageLoader(QThread):
    image_loaded = Signal(str, QImage) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = deque()
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self._is_running = True

    def load_image(self, path):
        with QMutexWithLocker(self.mutex):
            self.queue.clear() # 빠른 반응을 위해 이전 대기열 삭제
            self.queue.append(path)
            self.condition.wakeOne()

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

            path = self.queue.popleft() if self.queue else None
            self.mutex.unlock()

            if path:
                image = QImage()
                if os.path.exists(path):
                    # [메모리 최적화] QImageReader를 사용하여 리사이징 로드
                    try:
                        reader = QImageReader(path)
                        reader.setAutoTransform(True) # EXIF 회전 반영
                        orig_size = reader.size()
                        # 미리보기용으로 너무 큰 이미지는 1024px로 제한
                        if orig_size.width() > 1024 or orig_size.height() > 1024:
                            reader.setScaledSize(orig_size.scaled(1024, 1024, Qt.KeepAspectRatio))
                        
                        loaded = reader.read()
                        if not loaded.isNull():
                            image = loaded
                    except Exception as e:
                        print(f"Image load error: {e}")

                self.image_loaded.emit(path, image)

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
                base = os.path.splitext(self.dest_path)[0]
                thumb_path = base + ".png"
                if extract_video_frame(self.dest_path, thumb_path):
                    self.finished.emit(True, "Video set & Thumbnail extracted.")
                    return
                else:
                    self.finished.emit(True, "Video set (Thumbnail extraction failed).")
                    return
            self.finished.emit(True, "Thumbnail updated.")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# File Scanner
# ==========================================
class FileScannerWorker(QThread):
    finished = Signal(dict)
    def __init__(self, base_path, extensions):
        super().__init__()
        self.base_path = base_path
        self.extensions = extensions
        self._is_running = True
    def stop(self):
        self._is_running = False
    def run(self):
        file_structure = {}
        if not os.path.exists(self.base_path):
            self.finished.emit({})
            return
        for root, dirs, files in os.walk(self.base_path):
            if not self._is_running: return
            valid_files = []
            for f in files:
                if not self._is_running: return
                if os.path.splitext(f)[1].lower() in self.extensions:
                    full_path = os.path.join(root, f)
                    try:
                        st = os.stat(full_path)
                        sz = self.format_size(st.st_size)
                        dt = time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))
                    except: sz="?"; dt="-"
                    valid_files.append({"name": f, "path": full_path, "size": sz, "date": dt})
            if valid_files or dirs:
                 file_structure[root] = {"dirs": dirs, "files": valid_files}
        if self._is_running:
            self.finished.emit(file_structure)
    def format_size(self, s):
        p=2**10; n=0; l={0:'', 1:'K', 2:'M', 3:'G'}
        while s > p: s/=p; n+=1
        return f"{s:.2f} {l.get(n,'T')}B"

# ==========================================
# Metadata Worker
# ==========================================
class MetadataWorker(QThread):
    batch_started = Signal(list) 
    task_progress = Signal(str, str, int) 
    status_update = Signal(str) 
    model_processed = Signal(bool, str, dict, str) 
    ask_overwrite = Signal(str)

    def __init__(self, mode="auto", targets=None, manual_url=None, civitai_key="", hf_key="", cache_root=None, directories=None):
        super().__init__()
        self.mode = mode 
        self.targets = targets if targets else []
        self.manual_url = manual_url
        self.civitai_key = civitai_key
        self.hf_key = hf_key
        self.directories = directories.copy() if directories else {} 
        self._is_running = True 
        
        self._overwrite_decision = None
        self._wait_mutex = QMutex()
        self._wait_condition = QWaitCondition()
        
        if cache_root:
            self.cache_root = cache_root
        else:
            self.cache_root = CACHE_DIR_NAME

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
        
        preview_dir = os.path.join(cache_dir, "preview")
        has_preview = False
        if os.path.exists(preview_dir) and os.listdir(preview_dir):
            has_preview = True
        return has_json or has_preview

    def run(self):
        total_files = len(self.targets)
        success_count = 0
        global_overwrite = None 

        self.batch_started.emit(self.targets)

        for idx, model_path in enumerate(self.targets):
            if not self._is_running: break

            try:
                if not model_path or not os.path.exists(model_path): continue

                filename = os.path.basename(model_path)
                
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

                if self.mode == "manual" and self.manual_url and "huggingface.co" in self.manual_url:
                    self._process_huggingface(model_path, self.manual_url)
                    success_count += 1
                    continue

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
                    version_data = self._make_request(f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}")
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
                model_data = self._make_request(f"https://civitai.com/api/v1/models/{model_id}")
                if not self._is_running: break

                all_versions = model_data.get("modelVersions", [])
                target_version = None
                if version_id:
                    for v in all_versions:
                        if str(v.get("id")) == str(version_id):
                            target_version = v; break
                if not target_version and all_versions: target_version = all_versions[0]

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
            
            time.sleep(1.0)
            
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
            except: pass

        self.status_update.emit("Calculating SHA256 (First run)...")
        calculated_hash = self._calculate_sha256(model_path)
        try:
            new_data = {}
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f: new_data = json.load(f)
                except: pass
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
        api_url = f"https://huggingface.co/api/models/{repo_id}"
        model_data = self._make_request(api_url)
        author = model_data.get("author", "Unknown")
        tags = model_data.get("tags", [])
        last_modified = model_data.get("lastModified", "Unknown")
        readme_url = f"https://huggingface.co/{repo_id}/resolve/main/README.md"
        headers = {'User-Agent': 'ComfyUI-Manager-QT'}
        if self.hf_key: headers['Authorization'] = f'Bearer {self.hf_key}'
        try:
            res = requests.get(readme_url, headers=headers, timeout=10)
            res.raise_for_status()
            readme_content = res.text
        except: readme_content = "*No README.md found.*"
        
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

    def _make_request(self, url):
        headers = {'User-Agent': 'ComfyUI-Manager-QT'}
        if "civitai.com" in url and self.civitai_key: headers['Authorization'] = f'Bearer {self.civitai_key}'
        elif "huggingface.co" in url and self.hf_key: headers['Authorization'] = f'Bearer {self.hf_key}'
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _process_embedded_images(self, text, model_path):
        cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
        embed_dir = os.path.join(cache_dir, "embedded")
        if not os.path.exists(embed_dir): os.makedirs(embed_dir)
        def replace_md(match):
            alt = match.group(1); url = match.group(2)
            local_path = self._download_file(url, embed_dir)
            if local_path: return f"![{alt}]({local_path.replace(os.sep, '/')})"
            return match.group(0)
        def replace_html(match):
            pre = match.group(1); url = match.group(2); post = match.group(3)
            local_path = self._download_file(url, embed_dir)
            if local_path: return f'{pre}{local_path.replace(os.sep, "/")}{post}'
            return match.group(0)
        text = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_md, text)
        text = re.sub(r'(<img[^>]+src=["\'])(.*?)(["\'][^>]*>)', replace_html, text)
        return text

    def _download_file(self, url, dest_dir):
        original_url = re.sub(r'/width=\d+/', '/original=true/', url)
        try:
            if not url.startswith("http"): return None
            path_part = url.split('?')[0]
            ext = os.path.splitext(path_part)[1]
            if not ext or len(ext) > 5: ext = ".jpg"
            
            filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ext
            local_path = os.path.join(dest_dir, filename)
            
            if not os.path.exists(local_path):
                headers = {'User-Agent': 'Mozilla/5.0'}
                if "huggingface.co" in url and self.hf_key: headers['Authorization'] = f'Bearer {self.hf_key}'
                
                def download_stream(target_url):
                    with requests.get(target_url, headers=headers, stream=True, timeout=15) as r:
                        r.raise_for_status()
                        content_type = r.headers.get('Content-Type')
                        
                        final_ext = ext
                        if 'image/png' in content_type: final_ext = '.png'
                        elif 'image/webp' in content_type: final_ext = '.webp'
                        elif 'image/jpeg' in content_type: final_ext = '.jpg'
                        elif 'video/mp4' in content_type: final_ext = '.mp4'
                        elif 'video/webm' in content_type: final_ext = '.webm'
                        
                        target_filename = filename
                        if final_ext != ext: 
                            target_filename = hashlib.md5(url.encode('utf-8')).hexdigest() + final_ext
                        
                        target_path = os.path.join(dest_dir, target_filename)
                        
                        if os.path.exists(target_path):
                            return target_path

                        with open(target_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                if not self._is_running: return None
                                f.write(chunk)
                        return target_path
                        
                try: return download_stream(original_url)
                except: return download_stream(url) 
            return local_path
        except Exception as e: return None

    def _download_preview_images(self, urls, model_path):
        cache_dir = calculate_structure_path(model_path, self.cache_root, self.directories)
        preview_dir = os.path.join(cache_dir, "preview")
        if not os.path.exists(preview_dir): os.makedirs(preview_dir)
        def _download_single(url):
            if not self._is_running: return
            self._download_file(url, preview_dir)
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
            
            for url in preview_urls:
                cache_filename_base = hashlib.md5(url.encode('utf-8')).hexdigest()
                if os.path.exists(cache_preview_dir):
                    for f in os.listdir(cache_preview_dir):
                        if f.startswith(cache_filename_base):
                             found_file = os.path.join(cache_preview_dir, f)
                             break
                if found_file: break
            
            if found_file:
                ext = os.path.splitext(found_file)[1].lower()
                dest_path = os.path.join(base_dir, model_name + ext)
                shutil.copy2(found_file, dest_path)
                self.status_update.emit(f"Auto-set media: {os.path.basename(dest_path)}")
                
                if ext in VIDEO_EXTENSIONS:
                    thumb_path = os.path.join(base_dir, model_name + ".png")
                    if extract_video_frame(dest_path, thumb_path):
                         self.status_update.emit(f"Extracted thumbnail: {os.path.basename(thumb_path)}")

        except Exception as e: print(f"Failed to auto-set thumbnail: {e}")

# ==========================================
# Model Download Worker
# ==========================================
class ModelDownloadWorker(QThread):
    progress = Signal(str, str, int)
    finished = Signal(str, str)
    error = Signal(str)
    name_found = Signal(str, str)
    ask_collision = Signal(str) # [신규] 중복 확인 시그널

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

    def stop(self):
        self._is_running = False
        self._resume()

    def set_collision_decision(self, decision):
        self._decision = decision
        self._resume()

    def _resume(self):
        self._wait_mutex.lock()
        self._wait_condition.wakeAll()
        self._wait_mutex.unlock()

    def _wait_for_user(self):
        self._wait_mutex.lock()
        self._wait_condition.wait(self._wait_mutex)
        self._wait_mutex.unlock()

    def run(self):
        try:
            self.progress.emit(self.task_key, "Resolving URL...", 0)
            
            model_id = None
            version_id = None
            
            match_m = re.search(r'models/(\d+)', self.url)
            match_v = re.search(r'modelVersionId=(\d+)', self.url)
            
            if match_m: model_id = match_m.group(1)
            if match_v: version_id = match_v.group(1)

            if not model_id:
                raise Exception("Cannot parse Model ID from URL")

            headers = {'User-Agent': 'ComfyUI-Manager-QT'}
            if self.api_key: headers['Authorization'] = f'Bearer {self.api_key}'

            if version_id:
                api_url = f"https://civitai.com/api/v1/model-versions/{version_id}"
            else:
                api_url = f"https://civitai.com/api/v1/models/{model_id}"
            
            resp = requests.get(api_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            display_name = ""
            if version_id:
                model_info = data.get("model", {})
                model_name = model_info.get("name", "")
                version_name = data.get("name", "")
                if model_name:
                    display_name = f"{model_name} - {version_name}"
                else:
                    display_name = version_name
            else:
                display_name = data.get("name", "Unknown Model")
            
            if display_name:
                full_display = f"{display_name} / {self.target_dir}"
                self.name_found.emit(self.task_key, full_display)


            download_url = None
            filename = "unknown_model.safetensors"

            if version_id:
                download_url = data.get("downloadUrl")
                files = data.get("files", [])
                for f in files:
                    if f.get("primary", False):
                        filename = f.get("name")
                        break
                if not filename and files: filename = files[0].get("name")
            else:
                versions = data.get("modelVersions", [])
                if not versions: raise Exception("No versions found.")
                target_ver = versions[0]
                download_url = target_ver.get("downloadUrl")
                files = target_ver.get("files", [])
                for f in files:
                    if f.get("primary", False):
                        filename = f.get("name")
                        break
                if not filename and files: filename = files[0].get("name")
            
            if not download_url:
                raise Exception("Download URL not found.")

            self.progress.emit(self.task_key, f"Connecting to {filename}...", 0)
            
            filename = sanitize_filename(filename)
            final_path = os.path.join(self.target_dir, filename)
            
            # [수정] 파일 중복 처리 로직
            if os.path.exists(final_path):
                self.ask_collision.emit(filename)
                self._wait_for_user()
                
                if self._decision == 'cancel':
                    self.finished.emit("Download Cancelled by User", "")
                    return
                elif self._decision == 'rename':
                    base, ext = os.path.splitext(filename)
                    final_path = os.path.join(self.target_dir, f"{base}_{int(time.time())}{ext}")
                elif self._decision == 'overwrite':
                    pass 
                else:
                    self.finished.emit("Download Cancelled", "")
                    return

            with requests.get(download_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                
                downloaded = 0
                last_update_time = 0
                
                with open(final_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024): 
                        if not self._is_running:
                            f.close()
                            try: os.remove(final_path)
                            except: pass
                            self.finished.emit("Download Cancelled", "")
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            current_time = time.time()
                            if total_size > 0:
                                if (current_time - last_update_time >= 0.5) or (downloaded == total_size):
                                    percent = int((downloaded / total_size) * 100)
                                    self.progress.emit(self.task_key, f"Downloading: {os.path.basename(final_path)}", percent)
                                    last_update_time = current_time
            
            self.progress.emit(self.task_key, "Download Complete", 100)
            self.finished.emit(f"Downloaded: {final_path}", final_path)

        except Exception as e:
            self.error.emit(str(e))
