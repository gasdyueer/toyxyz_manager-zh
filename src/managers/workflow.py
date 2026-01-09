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
from PySide6.QtGui import QDrag, QPixmap

from .base import BaseManagerWidget
from ..core import (
    SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, 
    HAS_MARKDOWN, calculate_structure_path
)
from ..ui_components import SmartMediaWidget, ZoomWindow, TaskMonitorWidget
from ..workers import ImageLoader

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
        btn_open = QPushButton("📂 Open Folder")
        btn_open.clicked.connect(self.open_current_folder)
        center_btn_layout.addWidget(btn_open)
        self.center_layout.addLayout(center_btn_layout)

    def init_right_panel(self):
        self.tabs = QTabWidget()
        
        # Tab 1: Note (Markdown)
        self.tab_note = QWidget()
        note_layout = QVBoxLayout(self.tab_note)
        note_controls = QHBoxLayout()
        self.btn_edit_note = QPushButton("✏️ Edit")
        self.btn_edit_note.setCheckable(True)
        self.btn_edit_note.clicked.connect(self.toggle_edit_note)
        self.btn_save_note = QPushButton("💾 Save")
        self.btn_save_note.clicked.connect(self.save_note)
        self.btn_save_note.setVisible(False)
        note_controls.addStretch()
        note_controls.addWidget(self.btn_edit_note)
        note_controls.addWidget(self.btn_save_note)
        note_layout.addLayout(note_controls)
        
        self.note_stack = QStackedWidget()
        self.txt_browser = QTextBrowser()
        self.txt_browser.setOpenExternalLinks(True)
        self.txt_edit = QTextEdit()
        self.note_stack.addWidget(self.txt_browser)
        self.note_stack.addWidget(self.txt_edit)
        note_layout.addWidget(self.note_stack)
        self.tabs.addTab(self.tab_note, "Note")
        
        # Tab 2: Raw JSON
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
        for ext in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
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
        self.txt_edit.setText(note_content)
        self._update_note_display(note_content)

    def get_cache_dir(self):
        custom_path = self.app_settings.get("cache_path", "").strip()
        if custom_path and os.path.isdir(custom_path):
            return custom_path
        from ..core import CACHE_DIR_NAME
        if not os.path.exists(CACHE_DIR_NAME):
            try: os.makedirs(CACHE_DIR_NAME)
            except: pass
        return CACHE_DIR_NAME

    def _update_note_display(self, text):
        scale = int(self.app_settings.get("font_scale", 100))
        font_size_pt = max(8, int(10 * (scale / 100.0))) 
        css = f"<style>body {{ color: black; background-color: white; font-size: {font_size_pt}pt; font-family: sans-serif; }}</style>"
        if HAS_MARKDOWN:
            html = markdown.markdown(text)
            self.txt_browser.setHtml(css + html)
        else:
            self.txt_browser.setHtml(css + f"<pre>{text}</pre>")

    def toggle_edit_note(self):
        is_edit = self.btn_edit_note.isChecked()
        self.note_stack.setCurrentIndex(1 if is_edit else 0)
        self.btn_save_note.setVisible(is_edit)
        if not is_edit: self._update_note_display(self.txt_edit.toPlainText())

    def save_note(self):
        if not self.current_wf_path: return
        text = self.txt_edit.toPlainText()
        
        cache_dir = calculate_structure_path(self.current_wf_path, self.get_cache_dir(), self.directories)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        model_name = os.path.splitext(os.path.basename(self.current_wf_path))[0]
        json_desc_path = os.path.join(cache_dir, model_name + ".desc.json")
        
        try:
            data = {"user_note": text}
            with open(json_desc_path, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            self._update_note_display(text)
            self.btn_edit_note.setChecked(False)
            self.toggle_edit_note()
            if self.parent_window: self.parent_window.statusBar().showMessage("Note saved.", 2000)
        except Exception as e: 
            print(f"Save Error: {e}")

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
            
            # Set drag pixmap (thumbnail)
            if not self.is_video and self.lbl_image.pixmap():
                drag_pixmap = self.lbl_image.pixmap().scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                drag.setPixmap(drag_pixmap)
                drag.setHotSpot(drag_pixmap.rect().center())
            
            drag.exec(Qt.CopyAction)
            self._drag_start_pos = None
        else:
            # Fallback to default behavior if no JSON path (though usually we want JSON for workflow mode)
            super().mouseMoveEvent(event)
