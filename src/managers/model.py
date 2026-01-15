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
from .example import ExampleTabWidget
from ..workers import ImageLoader, ThumbnailWorker # MetadataWorker removed
from .download import DownloadController
from ..controllers.metadata_controller import MetadataController

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
        
        self.last_download_dir = None

        # Filter directories for 'model' mode
        model_dirs = {k: v for k, v in directories.items() if v.get("mode", "model") == "model"}
        super().__init__(model_dirs, SUPPORTED_EXTENSIONS["model"], app_settings)
        
        self.metadata_queue = []
        self.selected_model_paths = []
        self._gc_counter = 0 # [Memory] Counter for periodic GC
        
        # Download Controller
        self.downl_controller = DownloadController(self, task_monitor, app_settings)
        self.downl_controller.download_finished.connect(self._on_download_finished_controller)
        self.downl_controller.download_error.connect(self._on_download_error_controller)
        self.downl_controller.progress_updated.connect(lambda k, s, p: self.show_status_message(f"{s}: {p}%", 0))
        
        # Metadata Controller
        self.metadata_controller = MetadataController(app_settings, directories, self)
        self.metadata_controller.status_message.connect(lambda msg, dur: self.show_status_message(msg, dur))
        self.metadata_controller.task_progress.connect(self.task_monitor.update_task)
        self.metadata_controller.batch_started.connect(lambda paths: self.task_monitor.add_tasks(paths, task_type="Auto Match"))
        self.metadata_controller.model_processed.connect(self._on_model_processed)
        self.metadata_controller.batch_processed.connect(self._on_batch_processed)
        
    def set_directories(self, directories):
        # Filter directories for 'model' mode
        model_dirs = {k: v for k, v in directories.items() if v.get("mode", "model") == "model"}
        super().set_directories(model_dirs)
        if self.directories:
            self.metadata_controller.directories = directories
        if hasattr(self, 'tab_example'):
            self.tab_example.directories = directories

    def get_mode(self): return "model"

    def get_debug_info(self):
        info = super().get_debug_info()
        
        # Player Stats
        player_state = "Stopped"
        if self.preview_lbl and self.preview_lbl.media_player:
            state = self.preview_lbl.media_player.playbackState()
            if state == 1: player_state = "Playing" 
            elif state == 2: player_state = "Paused"
            
        info.update({
            "download_queue_size": len(self.downl_controller.download_queue),
            "metadata_queue_size": len(self.metadata_controller.queue),
            "video_player_active": (self.preview_lbl.media_player is not None),
            "video_player_state": player_state,
            "gc_counter": self._gc_counter,
            "example_tab_stats": self.tab_example.get_debug_info() if hasattr(self, 'tab_example') else {}
        })
        return info

    def init_center_panel(self):
        self.info_labels = {}
        form_layout = QFormLayout()
        for k in ["Name", "Ext", "Size", "Path", "Date"]:
            l = QLabel("-")
            l.setWordWrap(True)
            self.info_labels[k] = l
            form_layout.addRow(f"{k}:", l)
            
        # [Duplicate Warning]
        self.lbl_duplicate_warning = QLabel("")
        self.lbl_duplicate_warning.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_duplicate_warning.setWordWrap(True)
        self.lbl_duplicate_warning.hide()
        form_layout.addRow(self.lbl_duplicate_warning)
        
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
        
        
        
        # Tabs (from Base)
        self.tabs = self.setup_content_tabs()
        
        # Download Tab Removed (User Request: Redundant with Task Monitor)
        
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
                 self.current_path = path # [Fix] Update current path tracker
                 self._load_details(path)
                 
                 # [Duplicate Check]
                 f_name = os.path.basename(path).lower()
                 if hasattr(self, 'file_map'):
                     duplicates = self.file_map.get(f_name, [])
                     if len(duplicates) > 1:
                         # Exclude current path from display
                         curr_norm = os.path.normcase(os.path.abspath(self.current_path))
                         other_paths = [p for p in duplicates if os.path.normcase(os.path.abspath(p)) != curr_norm]
                         
                         msg = f"⚠️ Duplicate Models Found ({len(duplicates)})"
                         if other_paths:
                             msg += "\n" + "\n".join(other_paths)
                             
                         tooltip = "Same filename detected in:\n" + "\n".join(duplicates)
                         self.lbl_duplicate_warning.setText(msg)
                         self.lbl_duplicate_warning.setToolTip(tooltip)
                         self.lbl_duplicate_warning.show()
                     else:
                         self.lbl_duplicate_warning.hide()
                 
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
            size_str = self.format_size(st.st_size)
            date_str = self.format_date(st.st_mtime, seconds=True)
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
        
        # Note Loading (Standardized)
        self.load_content_data(path)



    
    # save_note and handle_media_insert removed (using Base)

    # _check_metadata_conflicts removed (Moved to Controller)

    def _save_json_direct(self, model_path, content):
        # [Fix] Added mode argument
        cache_dir = calculate_structure_path(model_path, self.get_cache_dir(), self.directories, mode=self.get_mode())
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
    def run_civitai(self, mode, targets=None, manual_url_override=None, overwrite_behavior_override=None):
        if targets is None:
            targets = self.selected_model_paths
        
        # Delegate to Controller
        self.metadata_controller.run_civitai(mode, targets, manual_url_override, overwrite_behavior_override)

    def _on_model_processed(self, success, msg, data, model_path):
        if success:
            desc = data.get("description", "")
            self.save_note_for_path(model_path, desc, silent=True)
            if self.current_path == model_path:
                self.tab_note.set_text(desc)
                self.tab_example.load_examples(model_path)
                QTimer.singleShot(200, lambda: self._load_details(model_path))

    def _on_batch_processed(self):
        self.show_status_message("Batch Processed.")
        # Resume download queue if we were in a chain
        self.downl_controller.resume()

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
            self.downl_controller.add_download(url, target_dir)
            self.show_status_message(f"Added to queue: {os.path.basename(target_dir)}")

    def _on_download_finished_controller(self, msg, file_path):
        self.show_status_message(msg)
        self.refresh_list()
        
        # Auto-match Logic
        chain_started = False
        if file_path and os.path.exists(file_path):
             self.show_status_message(f"Auto-matching for: {os.path.basename(file_path)}...")
             self.run_civitai("auto", targets=[file_path])
             # Check if controller accepted the task (worker running or queue not empty)
             if self.metadata_controller.worker is not None or self.metadata_controller.queue:
                 chain_started = True
                 
        if not chain_started:
             self.downl_controller.resume() # Process next immediately

    def _on_download_error_controller(self, err_msg):
        self.show_status_message(f"Download Error: {err_msg}")
        QMessageBox.critical(self, "Download Failed", err_msg)
        self.downl_controller.resume()









    # _save_note_direct removed (Inherited save_note_for_path used)

    def closeEvent(self, event):
        self.metadata_controller.stop()
        self.downl_controller.stop()
        
        # [Memory] Explicit cleanup of media widgets
        if hasattr(self, 'preview_lbl'):
            self.preview_lbl.clear_memory()
            
        if hasattr(self, 'tab_example'):
            self.tab_example.unload_current_examples()
            
        super().closeEvent(event)
