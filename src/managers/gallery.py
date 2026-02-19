import os
import json
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser, 
    QTabWidget, QLabel
)
from PySide6.QtCore import Qt
from .base import BaseManagerWidget
from ..core import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from ..ui_components import SmartMediaWidget
from ..ui.metadata_widget import MetadataViewerWidget
from ..workers import LocalMetadataWorker

class GalleryManagerWidget(BaseManagerWidget):
    def __init__(self, directories, app_settings, parent=None):
        # [CRITICAL] STRICT FILTERING: Only allow directories with mode="gallery"
        gallery_dirs = {k: v for k, v in directories.items() if v.get("mode") == "gallery"}
        
        # Extensions: Images and Videos
        extensions = list(IMAGE_EXTENSIONS) + list(VIDEO_EXTENSIONS)
        
        super().__init__(gallery_dirs, extensions, app_settings)
        
        # Metadata Worker
        self.meta_worker = LocalMetadataWorker()
        self.meta_worker.finished.connect(self._on_meta_ready)
        self.meta_worker.start()

    def get_mode(self):
        return "gallery"

    # === UI Implementation ===

    def init_center_panel(self):
        """
        Center Panel: Preview + Actions
        """
        # [Refactor] Use shared setup for Info Panel
        self._setup_info_panel(["Ext"])

        # Preview Widget
        # We reuse the ImageLoader from base (self.image_loader_thread)
        # Renamed to preview_lbl to match BaseManagerWidget conventions for on_preview_click
        self.preview_lbl = SmartMediaWidget(loader=self.image_loader_thread, player_type="preview")
        self.preview_lbl.setMinimumSize(100, 100)
        self.preview_lbl.clicked.connect(self.on_preview_click) # [Feature] Fullscreen Hook
        
        # Actions
        btn_layout = QHBoxLayout()
        
        btn_open_file = QPushButton("📂 Open File")
        btn_open_file.setToolTip("Open in default system viewer")
        btn_open_file.clicked.connect(self._open_current_file)
        
        btn_open_folder = QPushButton("📁 Open Folder")
        btn_open_folder.setToolTip("Open containing folder")
        btn_open_folder.clicked.connect(self.open_current_folder)
        
        btn_layout.addWidget(btn_open_file)
        btn_layout.addWidget(btn_open_folder)
        btn_layout.addStretch()
        
        self.center_layout.addWidget(self.preview_lbl, 1)
        self.center_layout.addLayout(btn_layout)

    def init_right_panel(self):
        """
        Right Panel: Metadata Tabs
        """
        self.right_tabs = QTabWidget()
        
        # Tab 1: Example (Metadata Visualizer)
        self.meta_viewer = MetadataViewerWidget()
        self.right_tabs.addTab(self.meta_viewer, "Example")
        
        # Tab 2: Raw (JSON)
        self.txt_raw = QTextBrowser()
        self.right_tabs.addTab(self.txt_raw, "Raw")
        
        self.right_layout.addWidget(self.right_tabs)

    # === Logic Implementation ===

    def on_tree_select(self):
        """
        Called when a tree item is selected.
        Updates preview and metadata.
        """
        item = self.tree.currentItem()
        if not item: return
        
        path = item.data(0, Qt.UserRole)
        type_ = item.data(0, Qt.UserRole + 1)
        
        if type_ == "file" and path and os.path.exists(path):
            self.current_path = path

            # 0. Load Common 详情s (Info Panel)
            filename, size_str, date_str, preview_path = self._load_common_file_details(path)
            
            ext = os.path.splitext(filename)[1]
            self.info_labels["名称"].setText(filename)
            self.info_labels["Ext"].setText(ext)
            self.info_labels["大小"].setText(size_str)
            self.info_labels["日期"].setText(date_str)
            self.info_labels["路径"].setText(path)
            
            # 1. Update Preview
            # [Fix] In Gallery mode, we must show exactly what is selected.
            # _load_common_file_details might return a 'better' preview (e.g. video for a model),
            # but here we are selecting specific files.
            self.preview_lbl.set_media(path)
            
            # 2. Extract Metadata
            self.meta_viewer.clear()
            self.txt_raw.clear()
            self.meta_worker.extract(path)
            
        else:
            self.preview_lbl.set_media(None)
            self.meta_viewer.clear()
            self.txt_raw.clear()
            self.current_path = None
            
            # Clear Info Panel
            self.info_labels["名称"].setText("-")
            self.info_labels["Ext"].setText("-")
            self.info_labels["大小"].setText("-")
            self.info_labels["路径"].setText("-")
            self.info_labels["日期"].setText("-")

    def _on_meta_ready(self, path, meta):
        """
        Called when metadata worker finishes extraction.
        """
        # Verify strict equality of path to avoid race conditions
        if not self.current_path or os.path.normpath(path) != os.path.normpath(self.current_path):
            return
            
        # Update Viewer
        self.meta_viewer.set_metadata(meta)
        
        # Update Raw
        try:
            raw_json = json.dumps(meta, indent=4, ensure_ascii=False)
            self.txt_raw.setText(raw_json)
        except:
            self.txt_raw.setText(str(meta))

    def _open_current_file(self):
        if self.current_path and os.path.exists(self.current_path):
            try:
                os.startfile(self.current_path)
            except OSError as e:
                logging.error(f"失败 to open file: {e}")

    def collect_active_workers(self):
        """Override to include the gallery-specific metadata worker."""
        # Get base workers (image loader, scanners, etc.)
        workers, thumb_workers, heavy_workers = super().collect_active_workers()
        
        # Add our specific worker
        try:
            if hasattr(self, 'meta_worker') and self.meta_worker and self.meta_worker.isRunning():
                heavy_workers.append(self.meta_worker)
        except RuntimeError: pass
        
        return workers, thumb_workers, heavy_workers

    def set_directories(self, directories):
        """Updates the directories and refreshes the combo box, enforcing strict filtering."""
        gallery_dirs = {k: v for k, v in directories.items() if v.get("mode") == "gallery"}
        super().set_directories(gallery_dirs)
