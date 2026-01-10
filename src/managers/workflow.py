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
    def __init__(self, directories, app_settings, parent_window=None):
        self.app_settings = app_settings
        self.parent_window = parent_window
        self.current_wf_path = None
        
        self.image_loader_thread = ImageLoader()
        self.image_loader_thread.start()
        
        # Filter directories for 'workflow' mode
        wf_dirs = {k: v for k, v in directories.items() if v.get("mode") == "workflow"}
        super().__init__(wf_dirs, SUPPORTED_EXTENSIONS["workflow"])

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
        self.btn_replace.clicked.connect(self.replace_thumbnail)
        center_btn_layout.addWidget(self.btn_replace)
        
        btn_open = QPushButton("📂 Open Folder")
        btn_open.clicked.connect(self.open_current_folder)
        center_btn_layout.addWidget(btn_open)
        self.center_layout.addLayout(center_btn_layout)

    def replace_thumbnail(self):
        if not self.current_wf_path: return
        
        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select New Thumbnail/Preview", "", filters)
        if not file_path: return
        
        base = os.path.splitext(self.current_wf_path)[0]
        ext = os.path.splitext(file_path)[1].lower()
        target_path = base + ext

        self.btn_replace.setEnabled(False)
        self.show_status("Processing thumbnail...")
        
        # [Fix] Unload image to be safe against file locks
        self.preview_lbl.set_media(None)
        QApplication.processEvents()

        is_video = (ext in VIDEO_EXTENSIONS)
        self.thumb_worker = ThumbnailWorker(file_path, target_path, is_video)
        self.thumb_worker.finished.connect(self._on_thumb_worker_finished)
        self.thumb_worker.start()

    def _on_thumb_worker_finished(self, success, msg):
        self.btn_replace.setEnabled(True)
        self.show_status(msg)
        if success:
             self._load_details(self.current_wf_path)
        else:
             QMessageBox.warning(self, "Error", f"Failed: {msg}")

    def show_status(self, msg):
        if self.parent_window:
            self.parent_window.statusBar().showMessage(msg, 3000)
        else:
            print(msg)

    def init_right_panel(self):
        self.tabs = QTabWidget()
        
        # Tab 1: Note (Markdown)
        from ..ui_components import MarkdownNoteWidget
        self.tab_note = MarkdownNoteWidget()
        self.tab_note.save_requested.connect(self.save_note)
        self.tab_note.set_media_handler(self.handle_media_insert)
        self.tabs.addTab(self.tab_note, "Note")
        
        # Tab 2: Example
        self.tab_example = ExampleTabWidget(self.directories, self.app_settings, self, self.image_loader_thread)
        self.tab_example.status_message.connect(self.show_status)
        self.tabs.addTab(self.tab_example, "Example")
        
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
            self.current_wf_path = path
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
        except: size_str="?"; date_str="?"
        
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

        # Load Note
        cache_dir = calculate_structure_path(path, self.get_cache_dir(), self.directories)
        model_name = os.path.splitext(filename)[0]
        json_desc_path = os.path.join(cache_dir, model_name + ".desc.json") # Different file to avoid collision involving .json
        # User note logic
        # Actually workflow itself IS a json file, so we can't store note INSIDE it easily without breaking structure if it's stricly comfy format.
        # So we use a separate sidecar file in cache for notes about workflows.
        
        note_content = ""
        if os.path.exists(json_desc_path):
            try:
                with open(json_desc_path, 'r', encoding='utf-8') as f:
                    note_content = json.load(f).get("user_note", "")
            except: pass
        self.tab_note.set_text(note_content)
        self.tab_example.load_examples(path)

    def get_cache_dir(self):
        custom_path = self.app_settings.get("cache_path", "").strip()
        if custom_path and os.path.isdir(custom_path):
            return custom_path
        from ..core import CACHE_DIR_NAME
        if not os.path.exists(CACHE_DIR_NAME):
            try: os.makedirs(CACHE_DIR_NAME)
            except: pass
        return CACHE_DIR_NAME

    def save_note(self, text):
        if not self.current_wf_path: return
        
        cache_dir = calculate_structure_path(self.current_wf_path, self.get_cache_dir(), self.directories)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        model_name = os.path.splitext(os.path.basename(self.current_wf_path))[0]
        json_desc_path = os.path.join(cache_dir, model_name + ".desc.json")
        
        try:
            data = {"user_note": text}
            with open(json_desc_path, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            if self.parent_window: self.parent_window.statusBar().showMessage("Note saved.", 2000)
        except Exception as e: 
            print(f"Save Error: {e}")

    def handle_media_insert(self, mtype):
        if not self.current_wf_path: 
            QMessageBox.warning(self, "Error", "No workflow selected.")
            return None
            
        if mtype not in ["image", "video"]: return None
        
        filters = "Images (*.png *.jpg *.jpeg *.webp *.gif)" if mtype == "image" else "Videos (*.mp4 *.webm)"
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select {mtype.title()}", "", filters)
        if not file_path: return None
        
        cache_dir = calculate_structure_path(self.current_wf_path, self.get_cache_dir(), self.directories)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        
        name = os.path.basename(file_path)
        dest_path = os.path.join(cache_dir, name)
        
        try:
            shutil.copy2(file_path, dest_path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to copy file to cache: {e}")
            return None
            
        # Use absolute path for reliability
        dest_path = dest_path.replace("\\", "/")
        if mtype == "image":
            return f"![{name}]({dest_path})"
        else:
            return f'<video src="{dest_path}" controls width="100%"></video>'

    def on_preview_click(self):
        path = self.preview_lbl.get_current_path()
        if path and os.path.exists(path) and os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
            ZoomWindow(path, self).show()

    def open_current_folder(self):
        if self.current_wf_path:
            f = os.path.dirname(self.current_wf_path)
            try: os.startfile(f)
            except: pass
            
    def closeEvent(self, event):
        if hasattr(self, 'image_loader_thread'): 
            self.image_loader_thread.stop()
            self.image_loader_thread.wait(1000)
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
