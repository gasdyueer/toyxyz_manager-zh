import os
import shutil
import json
import re
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QTextEdit, 
    QFormLayout, QGridLayout, QTabWidget, QStackedWidget, QMessageBox, QGroupBox, QLineEdit, QFileDialog, QInputDialog,
    QSplitter, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from .base import BaseManagerWidget
from ..core import (
    calculate_structure_path, HAS_PILLOW, HAS_MARKDOWN,
    SUPPORTED_EXTENSIONS, PREVIEW_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS
)
from ..ui_components import (
    SmartMediaWidget, TaskMonitorWidget, DownloadDialog, 
    FileCollisionDialog, OverwriteConfirmDialog, ZoomWindow
)
from .example import ExampleTabWidget
from ..workers import ImageLoader, ThumbnailWorker, MetadataWorker, ModelDownloadWorker

try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    pass
try:
    import markdown
except ImportError:
    pass

class ModelManagerWidget(BaseManagerWidget):
    def __init__(self, directories, app_settings, task_monitor, parent_window=None):
        self.task_monitor = task_monitor
        self.parent_window = parent_window
        self.last_download_dir = None
        
        self.image_loader_thread = ImageLoader()
        self.image_loader_thread.start()

        # Filter directories for 'model' mode
        model_dirs = {k: v for k, v in directories.items() if v.get("mode", "model") == "model"}
        super().__init__(model_dirs, SUPPORTED_EXTENSIONS["model"], app_settings)
        
        self.download_queue = []
        self.download_queue = []
        self.is_chain_processing = False
        self._gc_counter = 0 # [Memory] Counter for periodic GC
        
    def set_directories(self, directories):
        # Filter directories for 'model' mode
        model_dirs = {k: v for k, v in directories.items() if v.get("mode", "model") == "model"}
        super().set_directories(model_dirs)
        if hasattr(self, 'tab_example'):
            self.tab_example.directories = directories
        if hasattr(self, 'worker'):
            self.worker.directories = directories

    def init_center_panel(self):
        self.info_labels = {}
        form_layout = QFormLayout()
        for k in ["Name", "Ext", "Size", "Path", "Date"]:
            l = QLabel("-")
            l.setWordWrap(True)
            self.info_labels[k] = l
            form_layout.addRow(f"{k}:", l)
        self.center_layout.addLayout(form_layout)
        
        self.preview_lbl = SmartMediaWidget(loader=self.image_loader_thread)
        self.preview_lbl.setMinimumSize(100, 100) 
        self.preview_lbl.clicked.connect(self.on_preview_click)
        self.center_layout.addWidget(self.preview_lbl, 1)
        
        center_btn_layout = QHBoxLayout()
        self.btn_replace = QPushButton("🖼️ Change Thumb")
        self.btn_replace.setToolTip("Change the thumbnail image for the selected model")
        self.btn_replace.clicked.connect(self.replace_thumbnail)
        btn_open = QPushButton("📂 Open Folder")
        btn_open.setToolTip("Open the containing folder in File Explorer")
        btn_open.clicked.connect(self.open_current_folder)
        center_btn_layout.addWidget(self.btn_replace)
        center_btn_layout.addWidget(btn_open)
        self.center_layout.addLayout(center_btn_layout)

    def init_right_panel(self):
        meta_btns = QGridLayout()
        btn_auto = QPushButton("⚡ Auto Match")
        btn_auto.setToolTip("Automatically search Civitai for metadata by file hash")
        btn_manual = QPushButton("🔗 Manual URL")
        btn_manual.setToolTip("Manually enter a Civitai/HuggingFace URL to fetch metadata")
        btn_download = QPushButton("⬇️ Download Model")
        btn_download.setToolTip("Download a new model from a URL")
        
        btn_auto.clicked.connect(lambda: self.run_civitai("auto"))
        btn_manual.clicked.connect(lambda: self.run_civitai("manual"))
        btn_download.clicked.connect(self.download_model_dialog)

        meta_btns.addWidget(btn_auto, 0, 0)
        meta_btns.addWidget(btn_manual, 0, 1)
        meta_btns.addWidget(btn_download, 1, 0)
        self.right_layout.addLayout(meta_btns)
        
        self.tabs = QTabWidget()
        
        # Tab 1: Note
        from ..ui_components import MarkdownNoteWidget
        self.tab_note = MarkdownNoteWidget()
        self.tab_note.save_requested.connect(self.save_note)
        self.tab_note.set_media_handler(self.handle_media_insert)
        self.tabs.addTab(self.tab_note, "Note")
        
        # Tab 2: Example
        self.tab_example = ExampleTabWidget(self.directories, self.app_settings, self, self.image_loader_thread)
        self.tab_example.status_message.connect(self.show_status_message)
        self.tabs.addTab(self.tab_example, "Example")
        
        
        self.right_layout.addWidget(self.tabs)



    # === Interaction Logic ===
    
    def on_tree_select(self):
        items = self.tree.selectedItems()
        if not items: return
        selected_paths = []
        for item in items:
            path = item.data(0, Qt.UserRole)
            type_ = item.data(0, Qt.UserRole + 1)
            if type_ == "file" and path: 
                selected_paths.append(path)
        self.selected_model_paths = selected_paths
        current_item = self.tree.currentItem()
        if current_item:
            path = current_item.data(0, Qt.UserRole)
            type_ = current_item.data(0, Qt.UserRole + 1)
            
            # [Memory] Fast cleanup of previous view
            self.image_loader_thread.clear_queue() # Cancel pending loads
            self.preview_lbl.clear_memory()
            self.tab_example.unload_current_examples()
            
            import gc
            gc.collect() # Force immediate release (User request)
            
            if type_ == "file" and path:
                 self._load_details(path)
            elif type_ == "dict":
                 # Assuming self.lbl_info is a QLabel to display messages
                 # If not, this line might need adjustment based on actual UI
                 self.info_labels["Name"].setText("Select a model file to see details.")
                 self.info_labels["Ext"].setText("-")
                 self.info_labels["Size"].setText("-")
                 self.info_labels["Path"].setText("-")
                 self.info_labels["Date"].setText("-")
                 self.preview_lbl.set_media(None)
                 self.tab_note.set_text("")
            else:
                 self.info_labels["Name"].setText("Select a model file to see details.")
                 self.info_labels["Ext"].setText("-")
                 self.info_labels["Size"].setText("-")
                 self.info_labels["Path"].setText("-")
                 self.info_labels["Date"].setText("-")
                 self.preview_lbl.set_media(None)
                 self.tab_note.set_text("")

    def _load_details(self, path):
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1]
        try:
            st = os.stat(path)
            size_bytes = st.st_size
            if size_bytes >= 1073741824: size_str = f"{size_bytes / 1073741824:.2f} GB"
            elif size_bytes >= 1048576: size_str = f"{size_bytes / 1048576:.2f} MB"
            elif size_bytes >= 1024: size_str = f"{size_bytes / 1024:.2f} KB"
            else: size_str = f"{size_bytes} B"
            date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
        except (OSError, ValueError): size_str = "Unknown"; date_str = "Unknown"
        self.info_labels["Name"].setText(filename)
        self.info_labels["Ext"].setText(ext)
        self.info_labels["Size"].setText(size_str)
        self.info_labels["Date"].setText(date_str)
        self.info_labels["Path"].setText(path)
        base = os.path.splitext(path)[0]
        preview_path = None
        for ext in PREVIEW_EXTENSIONS:
            if os.path.exists(base + ext): preview_path = base + ext; break
        self.preview_lbl.set_media(preview_path)
        
        # [Memory] Periodic GC for model browsing
        self._gc_counter += 1
        if self._gc_counter >= 20: # Less frequent than examples as models are heavier to load structure? No, just heuristic.
            import gc
            gc.collect()
            self._gc_counter = 0
        
        # Note Loading
        cache_dir = calculate_structure_path(path, self.get_cache_dir(), self.directories)
        model_name = os.path.splitext(filename)[0]
        json_path = os.path.join(cache_dir, model_name + ".json")
        note_content = ""
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    note_content = json.load(f).get("user_note", "")
            except (OSError, json.JSONDecodeError): pass
        self.tab_note.set_text(note_content)
        self.tab_example.load_examples(path)



    def save_note(self, text):
        if not self.current_path: return
        try:
            base, ext = os.path.splitext(self.current_path)
            note_path = base + ".md"
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(text)
            
            # Also update JSON description if exists
            json_path = base + ".json"
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                    data["description"] = text
                    with open(json_path, "w", encoding="utf-8") as jf:
                        json.dump(data, jf, indent=4)
                except (OSError, json.JSONDecodeError): pass
                
            if self.parent_window: self.parent_window.statusBar().showMessage("Note saved.", 2000)
        except Exception as e: 
            print(f"Save Error: {e}")

    def handle_media_insert(self, mtype):
        if not self.current_path: 
            QMessageBox.warning(self, "Error", "No model selected.")
            return None
            
        if mtype not in ["image", "video"]: return None
        
        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select {mtype.title()}", "", filters)
        if not file_path: return None
        
        return self.copy_media_to_cache(file_path, self.current_path)

    def _save_json_direct(self, model_path, content):
        cache_dir = calculate_structure_path(model_path, self.get_cache_dir(), self.directories)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        json_path = os.path.join(cache_dir, model_name + ".json")
        try:
            data = {}
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f: data = json.load(f)
            data["user_note"] = content
            with open(json_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e: print(f"Save Error: {e}")



    # === Civitai / Download Logic ===
    def run_civitai(self, mode, targets=None):
        if targets is None:
            targets = self.selected_model_paths
        if not targets: return
        
        manual_url = None
        if mode == "manual":
            if len(targets) > 1:
                QMessageBox.warning(self, "Warning", "Manual mode supports only single file selection.")
                return
            url, ok = QInputDialog.getText(self, "Manual URL", "Enter Civitai or HuggingFace Model URL:")
            if not ok or not url: return
            manual_url = url
        
        if hasattr(self, 'worker') and self.worker.isRunning():
            QMessageBox.warning(self, "Busy", "A background task is already running. Please wait or stop it.")
            return

        self.tabs.setCurrentIndex(2)
            
        cache_dir = self.get_cache_dir()
        self.worker = MetadataWorker(
            mode, targets, manual_url, 
            civitai_key=self.app_settings.get("civitai_api_key"),
            hf_key=self.app_settings.get("hf_api_key"),
            cache_root=cache_dir,
            directories=self.directories
        )
        self.worker.status_update.connect(self.show_status_message)
        self.worker.batch_started.connect(lambda paths: self.task_monitor.add_tasks(paths, task_type="Auto Match"))
        self.worker.task_progress.connect(self.task_monitor.update_task)
        self.worker.model_processed.connect(self._on_model_processed)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.finished.connect(self.worker.deleteLater) # Cleanup thread
        self.worker.ask_overwrite.connect(self.handle_overwrite_request)
        
        self.worker.start()

    def _on_model_processed(self, success, msg, data, model_path):
        if success:
            desc = data.get("description", "")
            self._save_json_direct(model_path, desc)
            if self.current_path == model_path:
                self.tab_note.set_text(desc)
                self.tab_example.load_examples(model_path)
                QTimer.singleShot(200, lambda: self._load_details(model_path))

    def _on_worker_finished(self):
        self.show_status_message("Batch Processed.")
        if self.is_chain_processing:
            self.is_chain_processing = False
            self._process_download_queue()

    def download_model_dialog(self):
        default_dir = None
        if self.last_download_dir and os.path.exists(self.last_download_dir):
            default_dir = self.last_download_dir
        if not default_dir:
            current_item = self.tree.currentItem()
            if current_item:
                path = current_item.data(0, Qt.UserRole)
                type_ = current_item.data(0, Qt.UserRole + 1)
                if path:
                    default_dir = os.path.dirname(path) if type_ == "file" else path
        if not default_dir:
            root_name = self.folder_combo.currentText()
            default_dir = self.directories.get(root_name, {}).get("path") if isinstance(self.directories.get(root_name), dict) else self.directories.get(root_name)
        if not default_dir:
            default_dir = os.getcwd() 

        dlg = DownloadDialog(default_dir, self)
        if dlg.exec():
            url, target_dir = dlg.get_data()
            if not url: return
            if not os.path.exists(target_dir):
                QMessageBox.warning(self, "Error", "Selected directory does not exist.")
                return

            self.last_download_dir = target_dir
            
            display_name = "Unknown Model"
            match_slug = re.search(r'models/\d+/([^/?#]+)', url)
            match_id = re.search(r'models/(\d+)', url)
            if match_slug:
                display_name = match_slug.group(1)
            elif match_id:
                display_name = f"Model {match_id.group(1)}"
            
            detail_info = f"{display_name} / {os.path.basename(target_dir)}"

            task = {
                'url': url,
                'target_dir': target_dir,
                'display_name': detail_info
            }
            self.download_queue.append(task)
            self.task_monitor.add_row(url, "Download", detail_info, "Queued")
            self.tabs.setCurrentIndex(2) 
            self.show_status_message(f"Added to queue: {os.path.basename(target_dir)}")
            self._process_download_queue()

    def _process_download_queue(self):
        if (hasattr(self, 'dl_worker') and self.dl_worker.isRunning()) or \
           (hasattr(self, 'worker') and self.worker.isRunning()) or \
           self.is_chain_processing:
            return

        if not self.download_queue:
            return

        self.is_chain_processing = True
        task = self.download_queue.pop(0)
        
        self.dl_worker = ModelDownloadWorker(
            task['url'], task['target_dir'], 
            api_key=self.app_settings.get("civitai_api_key"),
            task_key=task['url'] 
        )
        
        self.dl_worker.progress.connect(self._on_download_progress)
        self.dl_worker.finished.connect(self._on_download_finished)
        self.dl_worker.error.connect(self._on_download_error)
        self.dl_worker.name_found.connect(self.task_monitor.update_task_name)
        self.dl_worker.ask_collision.connect(self.handle_download_collision)
        self.dl_worker.finished.connect(self.dl_worker.deleteLater) # Cleanup thread
        
        self.show_status_message(f"Starting download...")
        self.dl_worker.start()

    def handle_download_collision(self, filename):
        dlg = FileCollisionDialog(filename, self)
        dlg.exec()
        self.dl_worker.set_collision_decision(dlg.result_value)

    def _on_download_progress(self, key, status, percent):
        self.task_monitor.update_task(key, status, percent)
        self.show_status_message(f"Downloading... {percent}%")

    def _on_download_finished(self, msg, file_path):
        self.show_status_message(msg)
        self.refresh_list() 
        chain_started = False
        if file_path and os.path.exists(file_path):
            self.show_status_message(f"Auto-matching for: {os.path.basename(file_path)}...")
            if hasattr(self, 'worker') and self.worker.isRunning():
                 pass
            else:
                 self.run_civitai("auto", targets=[file_path])
                 chain_started = True

        if not chain_started:
            self.is_chain_processing = False
            self._process_download_queue()

    def _on_download_error(self, err_msg):
        self.show_status_message(f"Download Error: {err_msg}")
        QMessageBox.critical(self, "Download Failed", err_msg)
        self.is_chain_processing = False
        self._process_download_queue()

    def handle_overwrite_request(self, filename):
        dlg = OverwriteConfirmDialog(filename, self)
        dlg.exec()
        self.worker.set_overwrite_response(dlg.result_value)

    def open_settings(self):
        # NOT USED HERE - handled by MainWindow
        pass





    def closeEvent(self, event):
        if hasattr(self, 'image_loader_thread'):
            self.image_loader_thread.stop()
            self.image_loader_thread.wait(1000)
        
        # Stop Metadata Worker
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1000)
            
        # Stop Download Worker
        if hasattr(self, 'dl_worker') and self.dl_worker.isRunning():
            self.dl_worker.stop()
            self.dl_worker.wait(1000)
        super().closeEvent(event)
