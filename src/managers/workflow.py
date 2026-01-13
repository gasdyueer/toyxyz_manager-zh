import os
import shutil
import json
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QTextEdit, 
    QFormLayout, QGridLayout, QTabWidget, QStackedWidget, QMessageBox, QFileDialog,
    QSplitter, QApplication
)
from PySide6.QtCore import Qt, QUrl, QMimeData, QTimer
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor

from .base import BaseManagerWidget
from ..core import (
    SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, 
    HAS_MARKDOWN, calculate_structure_path, PREVIEW_EXTENSIONS
)
from ..ui_components import SmartMediaWidget, ZoomWindow, TaskMonitorWidget
from .example import ExampleTabWidget
from ..workers import ImageLoader, ThumbnailWorker

try:
    import markdown
except ImportError:
    pass

class WorkflowManagerWidget(BaseManagerWidget):
    def __init__(self, directories, app_settings, task_monitor, parent_window=None):
        self.task_monitor = task_monitor
        self.task_monitor = task_monitor
        self.parent_window = parent_window
        # self.image_loader_thread = ImageLoader() # Moved to Base
        # self.image_loader_thread.start()
        
        # Filter directories for 'workflow' mode
        wf_dirs = {k: v for k, v in directories.items() if v.get("mode") == "workflow"}
        super().__init__(wf_dirs, SUPPORTED_EXTENSIONS["workflow"], app_settings)

    def set_directories(self, directories):
        # Filter directories for 'workflow' mode
        wf_dirs = {k: v for k, v in directories.items() if v.get("mode") == "workflow"}
        super().set_directories(wf_dirs)
        if hasattr(self, 'tab_example'):
            self.tab_example.directories = directories

    def init_center_panel(self):
        self.info_labels = {}
        form_layout = QFormLayout()
        for k in ["Name", "Size", "Path", "Date"]:
            l = QLabel("-")
            l.setWordWrap(True)
            self.info_labels[k] = l
            form_layout.addRow(f"{k}:", l)
        self.center_layout.addLayout(form_layout)
        
        # Extended SmartMediaWidget for JSON Drag & Drop
        self.preview_lbl = WorkflowDraggableMediaWidget(loader=self.image_loader_thread)
        self.preview_lbl.setMinimumSize(100, 100)
        self.preview_lbl.clicked.connect(self.on_preview_click)
        self.center_layout.addWidget(self.preview_lbl, 1)
        
        # Buttons
        center_btn_layout = QHBoxLayout()
        self.btn_replace = QPushButton("🖼️ Change Thumb")
        self.btn_replace.setToolTip("Change the thumbnail image for the selected workflow")
        self.btn_replace.clicked.connect(self.replace_thumbnail)
        center_btn_layout.addWidget(self.btn_replace)
        
        btn_open = QPushButton("📂 Open Folder")
        btn_open.setToolTip("Open the containing folder in File Explorer")
        btn_open.clicked.connect(self.open_current_folder)
        center_btn_layout.addWidget(btn_open)
        self.center_layout.addLayout(center_btn_layout)





    def init_right_panel(self):
        # Tabs (from Base)
        self.tabs = self.setup_content_tabs()
        
        # Tab 3: Raw JSON
        self.tab_raw = QWidget()
        raw_layout = QVBoxLayout(self.tab_raw)
        self.txt_raw = QTextBrowser()
        raw_layout.addWidget(self.txt_raw)
        self.tabs.addTab(self.tab_raw, "Raw JSON")
        
        self.right_layout.addWidget(self.tabs)

    def on_tree_select(self):
        item = self.tree.currentItem()
        if not item: return
        
        path = item.data(0, Qt.UserRole)
        type_ = item.data(0, Qt.UserRole + 1)
        
        if type_ == "file" and path:
            self.current_path = path
            self._load_details(path)
            # Pass the JSON path to the draggable widget so it knows what to drag
            self.preview_lbl.set_json_path(path)

    def _load_details(self, path):
        filename = os.path.basename(path)
        try:
            st = os.stat(path)
            size_str = f"{st.st_size} B"
            if st.st_size > 1024: size_str = f"{st.st_size/1024:.2f} KB"
            date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
        except (OSError, ValueError): size_str="?"; date_str="?"
        
        self.info_labels["Name"].setText(filename)
        self.info_labels["Size"].setText(size_str)
        self.info_labels["Date"].setText(date_str)
        self.info_labels["Path"].setText(path)
        
        # Find thumbnail: same name as json but with image extension
        base = os.path.splitext(path)[0]
        preview_path = None
        for ext in PREVIEW_EXTENSIONS:
            if os.path.exists(base + ext):
                preview_path = base + ext
                break
        self.preview_lbl.set_media(preview_path)
        
        # Load Raw JSON
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw_text = f.read()
                self.txt_raw.setText(raw_text)
        except Exception as e:
            self.txt_raw.setText(f"Error reading file: {e}")

        # Load Note (Standardized)
        self.load_content_data(path)



    # save_note and handle_media_insert removed (using Base)


            
    def closeEvent(self, event):
        super().closeEvent(event)


class WorkflowDraggableMediaWidget(SmartMediaWidget):
    """
    Subclass of SmartMediaWidget that drags the JSON file path instead of the image.
    """
    def set_json_path(self, path):
        self.json_path = path

    def mouseMoveEvent(self, event):
        if not self._drag_start_pos: return
        if not (event.buttons() & Qt.LeftButton): return
        current_pos = event.position().toPoint()
        if (current_pos - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        
        # Ensure we have a JSON path to drag
        if hasattr(self, 'json_path') and self.json_path and os.path.exists(self.json_path):
            drag = QDrag(self)
            mime_data = QMimeData()
            # This is the standard way to drag files in OS
            mime_data.setUrls([QUrl.fromLocalFile(self.json_path)])
            drag.setMimeData(mime_data)
            
            # Create default drag pixmap for JSON
            pix = QPixmap(100, 100)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            painter.setBrush(QColor(60, 60, 60))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(0, 0, 100, 100, 10, 10)
            painter.setPen(QColor(255, 255, 255))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pix.rect(), Qt.AlignCenter, "JSON\nWorkflow")
            painter.end()
            drag.setPixmap(pix)
            drag.setHotSpot(pix.rect().center())
            
            drag.exec(Qt.CopyAction)
            self._drag_start_pos = None
        else:
            # Fallback to default behavior if no JSON path (though usually we want JSON for workflow mode)
            super().mouseMoveEvent(event)
