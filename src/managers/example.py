import os
import shutil
import json
import time
import gc
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, 
    QGridLayout, QGroupBox, QLineEdit, QSplitter, QFileDialog, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Signal
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from ..core import calculate_structure_path, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from ..ui_components import SmartMediaWidget, ZoomWindow

class ExampleTabWidget(QWidget):
    status_message = Signal(str)

    def __init__(self, directories, app_settings, parent=None, image_loader=None):
        super().__init__(parent)
        self.directories = directories
        self.app_settings = app_settings
        self.image_loader = image_loader
        self.current_item_path = None
        self.example_images = []
        self.current_example_idx = 0
        
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5,5,5,5)
        
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setStyleSheet("""
            QSplitter::handle:horizontal {
                width: 15px;
            }
            QSplitter::handle:vertical {
                height: 15px;
            }
        """)
        
        # [Top] Image Area
        img_widget = QWidget()
        img_layout = QVBoxLayout(img_widget)
        img_layout.setContentsMargins(0,0,0,0)
        
        self.lbl_img = SmartMediaWidget(loader=self.image_loader)
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
        self.txt_neg.setStyleSheet("background-color: #fff0f0;")
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
        self.splitter.addWidget(meta_widget)
        
        main_layout.addWidget(self.splitter)
        self.splitter.setSizes([500, 300])

    def load_examples(self, path):
        self.current_item_path = path
        self.example_images = []
        self.current_example_idx = 0
        self._clear_meta()
        
        if not path:
            self._update_ui()
            return

        cache_dir = calculate_structure_path(path, self.get_cache_dir(), self.directories)
        preview_dir = os.path.join(cache_dir, "preview")
        
        if os.path.exists(preview_dir):
            valid_exts = tuple(list(IMAGE_EXTENSIONS) + list(VIDEO_EXTENSIONS))
            self.example_images = [os.path.join(preview_dir, f) for f in os.listdir(preview_dir) if f.lower().endswith(valid_exts)]
            self.example_images.sort()
            
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

    def change_example(self, delta):
        if not self.example_images: return
        self.current_example_idx = (self.current_example_idx + delta) % len(self.example_images)
        self._update_ui()

    def add_example_image(self):
        if not self.current_item_path: return
        
        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", filters)
        if not files: return
        
        cache_dir = calculate_structure_path(self.current_item_path, self.get_cache_dir(), self.directories)
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
            # 1. Unload image from UI
            self.lbl_img.set_media(None)
            self.lbl_img.repaint()
            QApplication.processEvents()
            
            # 2. Force GC to release any lingering PIL/Qt handles
            gc.collect()
            
            # 3. Retry loop for deletion
            retries = 5
            for i in range(retries):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                    break # Success
                except OSError as e:
                    # WinError 32: Process cannot access the file
                    if e.winerror == 32 and i < retries - 1:
                        time.sleep(0.1 * (i + 1)) # Backoff
                        QApplication.processEvents()
                        continue
                    else:
                        raise e

            self.load_examples(self.current_item_path)
            self.status_message.emit("File permanently deleted.")
            
        except Exception as e:
             # Restore image if failed (try to reload what we can)
             print(f"Delete failed: {e}")
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
            rev_map = {"CFG": "CFG scale", "Steps": "Steps", "Sampler": "Sampler", "Seed": "Seed", "Schedule": "Schedule", "Model": "Model hash"}
            for k, w in self.param_widgets.items():
                v = w.text().strip()
                if v:
                    pk = rev_map.get(k, k)
                    param_parts.append(f"{pk}: {v}")
            
            full_text = pos
            if neg: full_text += f"\nNegative prompt: {neg}"
            if param_parts: full_text += "\n" + ", ".join(param_parts)
            
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
                    print(f"Failed to remove original file: {e}")
                
                self.status_message.emit("Converted to PNG and saved metadata.")
                # Reload list because filename changed
                self.load_examples(self.current_item_path)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save metadata: {e}")

    def _parse_and_display_meta(self, path):
        self._clear_meta()
        try:
            with Image.open(path) as img:
                info = img.info.copy() # Copy info dict so it persists after close
                fmt = img.format # Save format
            
            if "workflow" in info or "prompt" in info:
                self.lbl_wf_status.setText("✅ Workflow")
                self.lbl_wf_status.setStyleSheet("color: green; font-weight: bold")
            
            text = info.get("parameters", "")
            if not text and fmt in ["JPEG", "WEBP"]:
                # Try to read Exif UserComment
                # Try to read Exif UserComment
                try:
                    exif_data = img._getexif()
                    if exif_data:
                        # UserComment tag is 37510 (0x9286)
                        user_comment = exif_data.get(37510)
                        if user_comment:
                            # 1. Strip Header
                            payload = user_comment
                            if isinstance(user_comment, bytes):
                                if user_comment.startswith(b'UNICODE\0'):
                                    payload = user_comment[8:]
                                elif user_comment.startswith(b'ASCII\0\0\0'):
                                    payload = user_comment[8:]
                                
                                # 2. Heuristic Decoding
                                # Try common encodings and check for "Mojibake" or valid text
                                candidates = []
                                for enc in ['utf-8', 'utf-16le', 'utf-16be']:
                                    try:
                                        decoded = payload.decode(enc)
                                        # Filter empty
                                        if not decoded.strip(): continue
                                        
                                        # Heuristic: Valid generation info is mostly printable ASCII + some punctuation
                                        # Count printable vs total
                                        printable = sum(1 for c in decoded if c.isprintable() or c in '\n\r\t')
                                        ratio = printable / len(decoded)
                                        candidates.append((ratio, decoded))
                                    except: pass
                                
                                # Pick the best result (highest printable ratio)
                                if candidates:
                                    candidates.sort(key=lambda x: x[0], reverse=True)
                                    best_ratio, best_text = candidates[0]
                                    if best_ratio > 0.8: # Threshold: at least 80% printable
                                        text = best_text
                            
                            elif isinstance(user_comment, str):
                                text = user_comment
                except Exception: pass
                
            if text:
                self._display_parameters(text)
                
        except Exception as e: 
            # Non-fatal, just can't read meta
            print(f"Meta parse error: {e}")

    def _display_parameters(self, text):
        import re
        pos = ""; neg = ""; params = ""
        
        # Regex split for "Negative prompt:" (case-insensitive)
        # Using capturing group () to keep the delimiter if needed, but here we just split
        # \s* handles optional spaces
        parts = re.split(r"Negative prompt:", text, flags=re.IGNORECASE)
        
        if len(parts) > 1:
            pos = parts[0].strip()
            # The rest might contain Steps, so we look into the last part
            remainder = parts[1]
        else:
            # Check if "Steps:" exists directly without negative prompt
            # Look for "Steps:" with optional preceding newline or space
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
        
        # Parse Key-Value pairs in params
        # This is tricky because values can contain commas.
        # But A1111 format is usually Key: Value, Key: Value
        # We'll use a simple comma split for now as it covers 90% cases
        p_map = {}
        if params:
            # Simple parser: split by comma, assume k:v structure
            for p in params.split(','):
                if ':' in p: 
                    k, v = p.split(':', 1)
                    p_map[k.strip().lower()] = v.strip() # Lowercase keys for mapping
        
        # Map to UI widgets (keys lowercased for comparison)
        key_map = {
            "steps": "Steps", 
            "sampler": "Sampler", 
            "cfg scale": "CFG", 
            "seed": "Seed", 
            "model": "Model"
        }
        
        for k_lower, widget_key in key_map.items():
            if k_lower in p_map and widget_key in self.param_widgets:
                self.param_widgets[widget_key].setText(p_map[k_lower])

    def _clear_meta(self):
        self.txt_pos.clear()
        self.txt_neg.clear()
        for w in self.param_widgets.values(): w.clear()
        self.lbl_wf_status.setText("No Workflow")
        self.lbl_wf_status.setStyleSheet("color: grey")

    def _copy_to_clipboard(self, text, name):
        if text:
            QApplication.clipboard().setText(text)
            self.status_message.emit(f"{name} copied to clipboard.")

    def get_cache_dir(self):
        custom_path = self.app_settings.get("cache_path", "").strip()
        if custom_path and os.path.isdir(custom_path):
            return custom_path
        from ..core import CACHE_DIR_NAME
        if not os.path.exists(CACHE_DIR_NAME):
            try: os.makedirs(CACHE_DIR_NAME)
            except OSError: pass
        return CACHE_DIR_NAME
