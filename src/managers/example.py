import os
import shutil
import json
import time
import gc
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, 
    QGridLayout, QGroupBox, QLineEdit, QSplitter, QFileDialog, QMessageBox, QApplication, QTabWidget
)
from PySide6.QtCore import Qt, Signal
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from ..core import calculate_structure_path, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, CACHE_DIR_NAME
from ..ui_components import SmartMediaWidget, ZoomWindow
from ..workers import LocalMetadataWorker

class ExampleTabWidget(QWidget):
    status_message = Signal(str)

    def __init__(self, directories, app_settings, parent=None, image_loader=None, cache_root=None, mode="model"):
        super().__init__(parent)
        self.directories = directories
        self.app_settings = app_settings
        self.image_loader = image_loader
        self.cache_root = cache_root or CACHE_DIR_NAME
        self.mode = mode
        self.mode = mode
        self.current_item_path = None
        self.current_cache_dir = None
        self.using_custom_path = False
        self.example_images = []
        self.current_example_idx = 0
        self._gc_counter = 0 # [Memory] Counter for periodic GC
        
        self.init_ui()
        
        # [Optimization] Async Metadata Worker
        self.metadata_worker = LocalMetadataWorker()
        self.metadata_worker.finished.connect(self._on_metadata_ready)
        self.metadata_worker.start()
    
    def closeEvent(self, event):
        """Ensure metadata worker is stopped on widget close."""
        if self.metadata_worker and self.metadata_worker.isRunning():
            self.metadata_worker.stop()
            self.metadata_worker.wait(1000)  # Wait up to 1 second
        super().closeEvent(event)

    def get_debug_info(self):
        mem_bytes = self.lbl_img.get_memory_usage()
        return {
            "file_list_count": len(self.example_images),
            "est_memory_mb": mem_bytes / 1024 / 1024,
            "gc_counter": self._gc_counter,
            "current_index": self.current_example_idx
        }

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5,5,5,5)
        
        self.splitter = QSplitter(Qt.Vertical)
        
        # [Top] Image Area
        img_widget = QWidget()
        img_layout = QVBoxLayout(img_widget)
        img_layout.setContentsMargins(0,0,0,0)
        
        self.lbl_img = SmartMediaWidget(loader=self.image_loader, player_type="example")
        self.lbl_img.setMinimumSize(100, 100)
        self.lbl_img.clicked.connect(self.on_example_click)
        
        img_layout.addWidget(self.lbl_img)
        
        # Navigation
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.lbl_count = QLabel("0/0")
        self.lbl_wf_status = QLabel("No Workflow")
        
        self.btn_prev.clicked.connect(lambda: self.change_example(-1))
        self.btn_next.clicked.connect(lambda: self.change_example(1))
        
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.lbl_count)
        nav_layout.addWidget(self.lbl_wf_status)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_next)
        img_layout.addLayout(nav_layout)
        
        # Tools
        tools_layout = QHBoxLayout()
        btn_add = QPushButton("➕")
        btn_add.setToolTip("Add Image")
        btn_add.clicked.connect(self.add_example_image)
        btn_del = QPushButton("➖")
        btn_del.setToolTip("Delete Image")
        btn_del.clicked.connect(self.delete_example_image)
        btn_open = QPushButton("📂")
        btn_open.setToolTip("Open Folder")
        btn_open.clicked.connect(self.open_example_folder)
        btn_save_meta = QPushButton("💾")
        btn_save_meta.setToolTip("Save Metadata")
        btn_save_meta.clicked.connect(self.save_example_metadata)
        
        for b in [btn_add, btn_del, btn_open, btn_save_meta]:
            b.setFixedWidth(40)
            tools_layout.addWidget(b)
        
        tools_layout.addStretch()
        img_layout.addLayout(tools_layout)
        self.splitter.addWidget(img_widget)
        
        # [Bottom] Metadata Area
        meta_widget = QWidget()
        meta_layout = QVBoxLayout(meta_widget)
        meta_layout.setContentsMargins(0,0,0,0)
        
        # Positive Prompt
        pos_header = QHBoxLayout()
        pos_header.addWidget(QLabel("Positive:"))
        btn_copy_pos = QPushButton("📋")
        btn_copy_pos.setFixedWidth(30)
        btn_copy_pos.setToolTip("Copy Positive Prompt")
        btn_copy_pos.clicked.connect(lambda: self._copy_to_clipboard(self.txt_pos.toPlainText(), "Positive Prompt"))
        pos_header.addWidget(btn_copy_pos)
        pos_header.addStretch()
        meta_layout.addLayout(pos_header)
        
        self.txt_pos = QTextEdit()
        self.txt_pos.setPlaceholderText("Positive Prompt")
        meta_layout.addWidget(self.txt_pos, 1)
        
        # Negative Prompt
        neg_header = QHBoxLayout()
        neg_header.addWidget(QLabel("Negative:"))
        btn_copy_neg = QPushButton("📋")
        btn_copy_neg.setFixedWidth(30)
        btn_copy_neg.setToolTip("Copy Negative Prompt")
        btn_copy_neg.clicked.connect(lambda: self._copy_to_clipboard(self.txt_neg.toPlainText(), "Negative Prompt"))
        neg_header.addWidget(btn_copy_neg)
        neg_header.addStretch()
        meta_layout.addLayout(neg_header)
        
        self.txt_neg = QTextEdit()
        self.txt_neg.setPlaceholderText("Negative Prompt")
        self.txt_neg.setObjectName("ExampleNegativePrompt")
        meta_layout.addWidget(self.txt_neg, 1)
        
        # Generation Settings
        self.param_widgets = {}
        grid_group = QGroupBox("Generation Settings")
        grid_layout = QGridLayout(grid_group)
        params = ["Steps", "Sampler", "CFG", "Seed", "Schedule"]
        for i, p in enumerate(params):
            grid_layout.addWidget(QLabel(p), 0, i)
            le = QLineEdit()
            self.param_widgets[p] = le
            grid_layout.addWidget(le, 1, i)
            
        meta_layout.addWidget(grid_group)
        
        # Resources (Civitai)
        # Metadata Tabs (Model / Etc)
        self.meta_tabs = QTabWidget()
        
        # Tab 1: Model
        self.tab_model = QWidget()
        tab_model_layout = QVBoxLayout(self.tab_model)
        tab_model_layout.setContentsMargins(5,5,5,5)
        self.txt_resources = QTextEdit()
        self.txt_resources.setPlaceholderText("Civitai resources info...")
        self.txt_resources.setMaximumHeight(100)
        tab_model_layout.addWidget(self.txt_resources)
        self.meta_tabs.addTab(self.tab_model, "Model")
        
        # Tab 2: Etc
        self.tab_etc = QWidget()
        tab_etc_layout = QVBoxLayout(self.tab_etc)
        tab_etc_layout.setContentsMargins(5,5,5,5)
        self.txt_etc = QTextEdit()
        self.txt_etc.setPlaceholderText("Extra parameters (NovelAI, Notes, etc)...")
        self.txt_etc.setReadOnly(True) # Mostly read-only for now
        self.txt_etc.setMaximumHeight(100)
        tab_etc_layout.addWidget(self.txt_etc)
        self.meta_tabs.addTab(self.tab_etc, "Etc")
        
        meta_layout.addWidget(self.meta_tabs)
        
        self.splitter.addWidget(meta_widget)
        
        main_layout.addWidget(self.splitter)
        self.splitter.setSizes([500, 300])

    def unload_current_examples(self):
        """Force cleanup of current examples to release memory."""
        self.lbl_img.clear_memory()
        self.example_images = []
        self.current_example_idx = 0
        self._clear_meta()
        self.lbl_count.setText("0/0")
        self.lbl_wf_status.setText("")
        
    def load_examples(self, path, target_filename=None, custom_cache_path=None):
        # Detect if this is a "reload" or "switch"
        is_reload = (path == self.current_item_path)
        self.current_item_path = path
        self.example_images = []
        self.current_example_idx = 0
        self._clear_meta()
        
        if not path:
            self._update_ui()
            return

        # Determine Cache Directory
        if custom_cache_path:
            self.current_cache_dir = custom_cache_path
            self.using_custom_path = True
        elif is_reload and getattr(self, 'using_custom_path', False):
            # Keep existing current_cache_dir
            pass
        else:
            self.using_custom_path = False
            self.current_cache_dir = calculate_structure_path(path, self.cache_root, self.directories, mode=self.mode)

        cache_dir = self.current_cache_dir
        preview_dir = os.path.join(cache_dir, "preview")
        
        if os.path.exists(preview_dir):
            valid_exts = tuple(list(IMAGE_EXTENSIONS) + list(VIDEO_EXTENSIONS))
            self.example_images = [os.path.join(preview_dir, f) for f in os.listdir(preview_dir) if f.lower().endswith(valid_exts)]
            self.example_images.sort()
            
            # Attempt to restore selection
            if target_filename:
                for i, full_path in enumerate(self.example_images):
                    if os.path.basename(full_path).lower() == target_filename.lower():
                        self.current_example_idx = i
                        break
            
        self._update_ui()

    def _update_ui(self):
        total = len(self.example_images)
        if total == 0:
            self.lbl_img.set_media(None)
            self.lbl_count.setText("0/0")
            self.lbl_wf_status.setText("")
            self._clear_meta()
        else:
            self.current_example_idx = max(0, min(self.current_example_idx, total - 1))
            self.lbl_count.setText(f"{self.current_example_idx + 1}/{total}")
            path = self.example_images[self.current_example_idx]
            self.lbl_img.set_media(path)
            
            if os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
                self._parse_and_display_meta(path)
            else:
                self._clear_meta()
                self.lbl_wf_status.setText("Video")

    def hideEvent(self, event):
        # [Memory] Stop playback when tab is hidden
        if self.lbl_img:
            self.lbl_img._stop_video_playback()
        super().hideEvent(event)

    def change_example(self, delta):
        if not self.example_images: return
        
        # [Memory] Pre-cleanup before switching
        # If we were playing video, force full cleanup to release MediaPlayer
        if self.lbl_img.is_video:
             self.lbl_img.clear_memory()
             
        self.current_example_idx = (self.current_example_idx + delta) % len(self.example_images)
        self._update_ui()
        
        # [Memory] Periodic GC
        self._gc_counter += 1
        if self._gc_counter >= 10:
            gc.collect()
            self._gc_counter = 0

    def add_example_image(self):
        if not self.current_item_path: return
        

        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", filters)
        if not files: return
        
        cache_dir = self.current_cache_dir
        if not cache_dir: return
        preview_dir = os.path.join(cache_dir, "preview")
        if not os.path.exists(preview_dir): os.makedirs(preview_dir)
        
        last_added_name = None
        for f in files:
            try: 
                shutil.copy2(f, preview_dir)
                last_added_name = os.path.basename(f)
            except OSError: pass
            
        self.load_examples(self.current_item_path)
        
        # [UX Fix] Auto-select the last added file
        if last_added_name and self.example_images:
            for idx, path in enumerate(self.example_images):
                if os.path.basename(path) == last_added_name:
                    self.current_example_idx = idx
                    self._update_ui()
                    break

    def delete_example_image(self):
        if not self.example_images: return
        path = self.example_images[self.current_example_idx]
        
        # Safety Check
        msg = "Delete this file?"
        if QMessageBox.question(self, "Delete File", msg, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        # [Fix] Release file handle & Retry logic
        try:
            # 0. Cancel any pending metadata extraction for this file
            if self.metadata_worker:
                self.metadata_worker.cancel_path(path)
                # Wait briefly for current operation to finish
                QApplication.processEvents()
                import time
                time.sleep(0.15)
            
            # 1. Unload image from UI (CLEANUP)
            self.lbl_img.clear_memory()
            QApplication.processEvents()
            
            # 2. Clear from ImageLoader cache (important!)
            if self.image_loader:
                self.image_loader.remove_from_cache(path)
            
            # 3. Simple delete with retry
            if os.path.exists(path):
                import time
                for attempt in range(3):
                    try:
                        os.remove(path)
                        break
                    except PermissionError as pe:
                        if attempt < 2:
                            time.sleep(0.1)  # 100ms delay
                            gc.collect()  # Force garbage collection
                        else:
                            raise pe

            self.load_examples(self.current_item_path)
            self.status_message.emit("File permanently deleted.")
            
        except Exception as e:
             # Restore image if failed (try to reload what we can)
             logging.warning(f"Delete failed: {e}")
             QMessageBox.warning(self, "Error", f"Failed to delete file:\n{e}")
             # Try to reload current image back if it still exists
             if os.path.exists(path):
                self.lbl_img.set_media(path)

    def open_example_folder(self):
        if not self.example_images: return
        f = os.path.dirname(self.example_images[0])
        try: os.startfile(f)
        except Exception as e: self.status_message.emit(f"Failed to open folder: {e}")

    def on_example_click(self):
        path = self.lbl_img.get_current_path()
        if not path: return
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
            return
        if os.path.exists(path):
            ZoomWindow(path, self).show()



    def save_example_metadata(self):
        if not self.example_images: return
        path = self.example_images[self.current_example_idx]
        
        ext = os.path.splitext(path)[1].lower()
        if ext in VIDEO_EXTENSIONS:
            return

        try:
            # Build parameters string
            pos = self.txt_pos.toPlainText()
            neg = self.txt_neg.toPlainText()
            
            param_parts = []
            rev_map = {"CFG": "CFG scale", "Steps": "Steps", "Sampler": "Sampler", "Seed": "Seed", "Schedule": "Schedule type", "Model": "Model"}
            for k, w in self.param_widgets.items():
                v = w.text().strip()
                if v:
                    pk = rev_map.get(k, k)
                    param_parts.append(f"{pk}: {v}")
            
            # Extract Model from Resources if manually edited
            res_content = self.txt_resources.toPlainText().strip()
            # If standard Model param wasn't in param_parts (which it isn't anymore as widget is gone)
            # We look for [checkpoint] Name
            # Simple assumption: If line starts with [checkpoint], it's the model.
            model_found = False
            for line in res_content.split('\n'):
                line = line.strip()
                if line.lower().startswith("[checkpoint]"):
                    # Extract name
                    # Format: [checkpoint] Name (Version)
                    # We want: Model: Name (Version)
                    # Just strip [checkpoint] prefix
                    model_val_extracted = line[len("[checkpoint]"):].strip()
                    if model_val_extracted:
                        param_parts.append(f"Model: {model_val_extracted}")
                        model_found = True
                    break # Assume one model
            
            # Also preserve Model hash if we ever had one? 
            # We don't have visual widget for hash, so usually relies on preservation logic or re-parsing.
            # But currently we only reconstruct from UI.
            
            full_text = pos
            if neg: full_text += f"\nNegative prompt: {neg}"
            if param_parts: full_text += "\n" + ", ".join(param_parts)

            # Append Resources
            res_content = self.txt_resources.toPlainText().strip()
            if res_content:
                # Check if resource is JSON or formatted text
                if res_content.startswith('[{"') or "Civitai resources:" in res_content:
                     full_text += f", {res_content}" # Raw JSON
                else:
                     # Filter out [checkpoint] lines (already extracted as Model param)
                     filtered_lines = [l for l in res_content.split('\n') if not l.strip().lower().startswith("[checkpoint]")]
                     cleaned_res = "\n".join(filtered_lines).strip()
                     if cleaned_res:
                         full_text += f"\nResources:\n{cleaned_res}"
             
            # Open Image and Update Metadata
            img = Image.open(path)
            img.load()
            
            metadata = PngInfo()
            
            # Preserve existing metadata except 'parameters'
            for k, v in img.info.items():
                if k == "parameters": continue
                if k in ["exif", "icc_profile"]: continue 
                if isinstance(v, str):
                    metadata.add_text(k, v)
            
            metadata.add_text("parameters", full_text)
            
            save_kwargs = {"pnginfo": metadata}
            if "exif" in img.info: save_kwargs["exif"] = img.info["exif"]
            if "icc_profile" in img.info: save_kwargs["icc_profile"] = img.info["icc_profile"]
            
            if ext == ".png":
                tmp_path = path + ".tmp.png"
                img.save(tmp_path, **save_kwargs)
                img.close()
                shutil.move(tmp_path, path)
                
                # [CACHE] Invalidate metadata cache since file was modified
                if self.metadata_worker:
                    self.metadata_worker.invalidate_cache(path)
                
                self._parse_and_display_meta(path)
                self.status_message.emit("Image metadata updated.")
            else:
                # Convert to PNG
                base = os.path.splitext(path)[0]
                new_path = base + ".png"
                
                img.save(new_path, format="PNG", **save_kwargs)
                img.close()
                
                # Delete original file safely
                try: 
                    os.remove(path)
                except Exception as e:
                    logging.warning(f"Failed to remove original file: {e}")
                
                self.status_message.emit("Converted to PNG and saved metadata.")
                # Reload list because filename changed, but try to keep selection on the new file
                # [CACHE] Invalidate old path cache (new file has different path anyway)
                if self.metadata_worker:
                    self.metadata_worker.invalidate_cache(path)
                
                self.load_examples(self.current_item_path, target_filename=os.path.basename(new_path))
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save metadata: {e}")

    def _parse_and_display_meta(self, path):
        self._clear_meta()
        self.lbl_wf_status.setText("Loading...")
        # [Optimization] Offload to worker
        if self.metadata_worker:
            self.metadata_worker.extract(path)
            
    def _on_metadata_ready(self, path, meta):
        # Verify if this is still the current item
        # If user clicked multiple times, path might differ from current_item_path
        # But for 'example' logic, self.current_item_path tracks the MAIN file (example list parent?).
        # Wait, load_examples sets self.current_item_path to the FOLDER or FILE?
        # self.example_images[self.current_example_idx] is the actual image being shown.
        
        current_img_path = None
        if self.example_images and 0 <= self.current_example_idx < len(self.example_images):
            current_img_path = self.example_images[self.current_example_idx]
            
        if not current_img_path or os.path.normpath(path) != os.path.normpath(current_img_path):
            return # Stale result
            
        try:
            # Update Status Icon based on standardized type
            # Update Status Icon based on standardized type (User Request: Only Show Comfy Workflow Status)
            if meta["type"] == "comfy":
                self.lbl_wf_status.setText("Workflow")
                self.lbl_wf_status.setToolTip("Contains ComfyUI Workflow (JSON)")
                self.lbl_wf_status.setObjectName("WorkflowStatus_Success")
            else:
                self.lbl_wf_status.setText("no workflow")
                self.lbl_wf_status.setToolTip("No ComfyUI workflow metadata found")
                self.lbl_wf_status.setObjectName("WorkflowStatus_Normal")
                
                # Force style reload since ObjectName changed
                self.lbl_wf_status.style().unpolish(self.lbl_wf_status)
                self.lbl_wf_status.style().polish(self.lbl_wf_status)
                
            # Populate UI based on standardized data
            
            # Special Case: NovelAI
            # NAI LSB data ("type": "novelai") is comprehensive and structured. 
            # We prefer this over any Exif text which might be generic.

            # Prioritize User-Edited/Hybrid Text Metadata
            # If we have raw_text (A1111 style) and it looks valid (contains "Steps:" or "Sampler:"), 
            # we prefer using that for display as it represents the most current/edited state.
            if meta.get("raw_text", "") and ("Steps:" in meta["raw_text"] or "Sampler:" in meta["raw_text"]):
                 try:
                    self._display_parameters(meta["raw_text"])
                 except Exception as e:
                    logging.debug(f"Hybrid parse error: {e}")

            # Special Case: NovelAI
            # NAI LSB data ("type": "novelai") is comprehensive and structured. 
            elif meta["type"] == "novelai":
                p = meta["main"]
                key_map = {
                    "steps": "Steps", "sampler": "Sampler", "cfg": "CFG", "seed": "Seed", "schedule": "Schedule"
                }
                for k_std, k_ui in key_map.items():
                    if p.get(k_std): self.param_widgets[k_ui].setText(str(p[k_std]))
                    
                self.txt_pos.setText(meta["prompts"]["positive"])
                self.txt_neg.setText(meta["prompts"]["negative"])
                
                # Etc / Tags
                etc_lines = []
                for k, v in meta["etc"].items():
                    etc_lines.append(f"{k}: {v}")
                self.txt_etc.setText("\n".join(etc_lines))
                    
            elif meta["type"] == "comfy":
                # Graph Only (No text block)
                p = meta["main"]
                key_map = {
                    "steps": "Steps", "sampler": "Sampler", "cfg": "CFG", "seed": "Seed", "schedule": "Schedule"
                }
                for k_std, k_ui in key_map.items():
                    if p.get(k_std): self.param_widgets[k_ui].setText(str(p[k_std]))
                    
                # Model/Resources
                m = meta["model"]
                lines = []
                if m.get("checkpoint"): lines.append(f"[checkpoint] {m['checkpoint']}")
                for lora in m.get("loras", []): lines.append(f"[lora] {lora}")
                self.txt_resources.setText("\n".join(lines))
                
                # Prompts
                self.txt_pos.setText(meta["prompts"]["positive"])
                self.txt_neg.setText(meta["prompts"]["negative"])
                
            elif meta["type"] == "simpai":
                 # Generic JSON from UserComment (SimpAI etc.)
                 p = meta["main"]
                 key_map = {
                    "steps": "Steps", "sampler": "Sampler", "cfg": "CFG", "seed": "Seed", "schedule": "Schedule"
                 }
                 for k_std, k_ui in key_map.items():
                    if p.get(k_std): self.param_widgets[k_ui].setText(str(p[k_std]))
                 
                 # SimpAI stores prompts?? Unknown from debug output.
                 # Assuming generic map if available, else empty.
                 self.txt_pos.setText(meta["prompts"]["positive"])
                 self.txt_neg.setText(meta["prompts"]["negative"])
                 
                 # Resources
                 if meta["model"]["checkpoint"]:
                     self.txt_resources.setText(f"[checkpoint] {meta['model']['checkpoint']}")
                 
                 # ETC
                 etc_lines = []
                 for k, v in meta["etc"].items():
                     etc_lines.append(f"{k}: {v}")
                 self.txt_etc.setText("\n".join(etc_lines))

            else:
                 # Fallback: Last Resort Text
                 if meta.get("raw_text", ""):
                     try: self._display_parameters(meta["raw_text"])
                     except: pass
                
        except Exception as e: 
            # Non-fatal
            logging.warning(f"Meta parse error: {e}")
            # Clear etc in case of partial failure
            self.txt_etc.clear()

    def _display_parameters(self, text):
        import re
        pos = ""; neg = ""; params = ""
        
        # Regex split for "Negative prompt:" (case-insensitive)
        parts = re.split(r"Negative prompt:", text, flags=re.IGNORECASE)
        
        if len(parts) > 1:
            pos = parts[0].strip()
            # The rest might contain Steps, so we look into the last part
            remainder = parts[1]
        else:
            # Check if "Steps:" exists directly without negative prompt
            steps_match = re.search(r"\bSteps:", text, flags=re.IGNORECASE)
            if steps_match:
                pos = text[:steps_match.start()].strip()
                remainder = text[steps_match.start():]
            else:
                pos = text; remainder = ""
        
        # Now split remainder for "Steps:"
        steps_parts = re.split(r"\bSteps:", remainder, flags=re.IGNORECASE, maxsplit=1)
        if len(steps_parts) > 1:
            neg = steps_parts[0].strip()
            params = "Steps:" + steps_parts[1]
        else:
            neg = remainder.strip()
            
        self.txt_pos.setText(pos)
        self.txt_neg.setText(neg) 
        
        # Robust Parsing
        self._raw_civitai_resources = None # Clear previous
        p_map = self._parse_parameters_robust(params)
        
        # UI Mapping
        key_map = {
            "steps": "Steps", 
            "sampler": "Sampler", 
            "cfg scale": "CFG", 
            "seed": "Seed", 
            "model": "Model", 
            "model hash": "Model", # Sometimes it's Model hash
            "schedule type": "Schedule"
        }
        
        # Special handling for Model/Resources
        model_val = ""
        
        if "model" in p_map: model_val = p_map["model"]
        elif "model hash" in p_map: model_val = p_map["model hash"]
        
        # Format Resources List
        formatted_lines = []
        checkpoint_converted = False

        # Handle Civitai Resources
        if "civitai resources" in p_map:
            raw_res = p_map["civitai resources"]
            self._raw_civitai_resources = raw_res # Keep raw for preservation
            try:
                res_list = json.loads(raw_res)
                if isinstance(res_list, list):
                    for item in res_list:
                        itype = item.get("type", "unknown")
                        iname = item.get("modelName", "Unknown")
                        iver = item.get("modelVersionName", "")
                        
                        line = f"[{itype}] {iname}"
                        if iver: line += f" ({iver})"
                        if itype != "checkpoint":
                             weight = item.get("weight", 1.0)
                             line += f" : {weight}"
                        
                        formatted_lines.append(line)
                        if itype == "checkpoint": checkpoint_converted = True
                        
            except json.JSONDecodeError:
                formatted_lines.append(raw_res) # Fallback
        
        # Handle generic Resources (from manual saves)
        elif "resources" in p_map:
             formatted_lines.append(p_map["resources"])
        
        # If no checkpoint found in Civitai resources, but we have Model param
        if not checkpoint_converted and model_val:
            formatted_lines.insert(0, f"[checkpoint] {model_val}")

        resources_text = "\n".join(formatted_lines)
        
        # Apply Logic to Widgets
        for k, v in self.param_widgets.items(): v.clear()
        
        # Set Model if found -- REMOVED WIDGET
        # if model_val: self.param_widgets["Model"].setText(model_val)
        
        for k_ui in self.param_widgets:
            # if k_ui == "Model": continue # Handled above
            
            # Reverse lookup for other keys
            for k_map_lower, k_map_ui in key_map.items():
                if k_map_ui == k_ui and k_map_lower in p_map:
                    self.param_widgets[k_ui].setText(p_map[k_map_lower])
                    break
                    
        self.txt_resources.setText(resources_text)
        
        # Populate Etc with unused keys
        used_keys = set([k.lower() for k in key_map.keys()]) | {"civitai resources", "resources"}
        # Note: key_map keys in source code are already lower case in my view (steps, sampler...)
        # But ensure robust checking
        used_keys = {
            "steps", "sampler", "cfg scale", "seed", "model", "model hash", "schedule type",
            "civitai resources", "resources"
        }
        
        etc_lines = []
        for k, v in p_map.items():
            if k not in used_keys:
                 etc_lines.append(f"{k}: {v}")
        
        self.txt_etc.setText("\n".join(etc_lines))

    def _parse_parameters_robust(self, params_str):
        """
        Parses the parameter string handling JSON arrays/objects correctly.
        Returns a dict of lowercased keys -> values.
        """
        if not params_str: return {}
        
        result = {}
        in_key = True
        
        # State machine
        buffer = []
        stack = [] # For [], {}
        in_quote = False
        
        def commit():
            full_str = "".join(buffer).strip()
            if not full_str: return
            
            # Try to find the first colon that is NOT inside quotes/brackets (simple approach)
            # Actually, standard format is "Key: Value"
            if ':' in full_str:
                k, v = full_str.split(':', 1)
                result[k.strip().lower()] = v.strip()
            buffer.clear()
            
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
                
            if char == ',' and not stack:
                # Comma at root level -> Splitter
                commit()
                continue
                
            buffer.append(char)
            
        commit() # Commit last part
        return result

    def _clear_meta(self):
        self.txt_pos.clear()
        self.txt_neg.clear()
        for w in self.param_widgets.values(): w.clear()
        self.txt_resources.clear()
        self.txt_etc.clear()
        self._raw_civitai_resources = None
        self.lbl_wf_status.setText("No Workflow")
        self.lbl_wf_status.setObjectName("WorkflowStatus_Neutral")
        self.lbl_wf_status.style().unpolish(self.lbl_wf_status)
        self.lbl_wf_status.style().polish(self.lbl_wf_status)

    def _copy_to_clipboard(self, text, name):
        if text:
            QApplication.clipboard().setText(text)
            self.status_message.emit(f"{name} copied to clipboard.")

    # [Memory Optimization]
    def stop_videos(self):
        """Stops and releases video resources in the example tab."""
        if hasattr(self, 'lbl_img'):
            if hasattr(self.lbl_img, 'release_resources'):
                self.lbl_img.release_resources()
            elif hasattr(self.lbl_img, '_stop_video_playback'):
                self.lbl_img._stop_video_playback()


