
import os
import time
import json
import platform
import subprocess
import shutil
import re
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
    QLabel, QPushButton, QComboBox, QTextBrowser, QTextEdit, QFileDialog, QMessageBox, 
    QProgressBar, QTabWidget, QLineEdit, QFormLayout, QStackedWidget, QGroupBox, 
    QGridLayout, QAbstractItemView, QApplication, QTreeWidgetItemIterator
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont

try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    pass

try:
    import markdown
except ImportError:
    pass

from .core import (
    CONFIG_FILE, CACHE_DIR_NAME, SUPPORTED_EXTENSIONS, PREVIEW_EXTENSIONS, 
    IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, HAS_PILLOW, HAS_MARKDOWN,
    calculate_structure_path, load_config, save_config, sanitize_filename
)
from .workers import (
    ImageLoader, ThumbnailWorker, FileScannerWorker, MetadataWorker, ModelDownloadWorker
)
from .ui_components import (
    SmartMediaWidget, TaskMonitorWidget, SettingsDialog, DownloadDialog, 
    FileCollisionDialog, OverwriteConfirmDialog, ZoomWindow
)

class ModelManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComfyUI Model Manager (Multimedia Support)")
        self.resize(1500, 950)
        self.app_settings = {"civitai_api_key": "", "hf_api_key": "", "font_scale": 100, "cache_path": ""}
        self.directories = {}
        self.current_model_path = None
        self.selected_model_paths = []
        self.example_images = []
        self.current_example_idx = 0
        self.default_font = QApplication.font()
        self.default_font_size = self.default_font.pointSize()
        
        self.download_queue = [] 
        self.is_chain_processing = False
        
        self.last_download_dir = None
        self.path_to_restore = None

        if self.default_font_size <= 0: self.default_font_size = 10 
        if not HAS_PILLOW:
            QTimer.singleShot(500, lambda: QMessageBox.warning(
                self, "Missing Library", "Pillow is missing. Image features will not work.\n\nRun: pip install pillow"
            ))
        self.image_loader_thread = ImageLoader()
        self.image_loader_thread.start()

        self.load_config_data()
        self.apply_font_scale()
        self._init_ui()
        self.update_combo_list()

    def get_cache_dir(self):
        custom_path = self.app_settings.get("cache_path", "").strip()
        if custom_path and os.path.isdir(custom_path):
            return custom_path
        if not os.path.exists(CACHE_DIR_NAME):
            try: os.makedirs(CACHE_DIR_NAME)
            except: pass
        return CACHE_DIR_NAME

    def _calculate_cache_path(self, model_path):
        return calculate_structure_path(model_path, self.get_cache_dir(), self.directories)


    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # 헤더
        header = QHBoxLayout()
        title = QLabel("📁 Model Manager")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        btn_settings = QPushButton("⚙️ Settings")
        btn_settings.clicked.connect(self.open_settings)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(btn_settings)
        layout.addLayout(header)
        
        # 메인 Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        
        # [Left Panel] 파일 탐색 트리
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0,0,0,0)
        combo_box = QHBoxLayout()
        self.folder_combo = QComboBox()
        self.folder_combo.currentIndexChanged.connect(self.refresh_list)
        btn_refresh = QPushButton("🔄")
        btn_refresh.clicked.connect(self.refresh_list)
        combo_box.addWidget(self.folder_combo, 1)
        combo_box.addWidget(btn_refresh)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Filter models...")
        self.filter_edit.textChanged.connect(self.filter_model_list)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Date", "Format"])
        self.tree.setColumnWidth(0, 200) 
        self.tree.setColumnWidth(1, 70)  
        self.tree.setColumnWidth(2, 110) 
        self.tree.setColumnWidth(3, 70)  
        self.tree.setStyleSheet("""
            QTreeWidget::item:selected:!focus {
                background-color: #505050;
                color: #e0e0e0;
            }
            QTreeWidget::item:selected:focus {
                background-color: #2196F3;
                color: white;
            }
        """)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self.on_tree_select)
        left_layout.addLayout(combo_box)
        left_layout.addWidget(self.filter_edit) 
        left_layout.addWidget(self.tree)
        self.splitter.addWidget(left_panel)
        
        # [Center Panel] 이미지 미리보기
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        self.info_labels = {}
        form_layout = QFormLayout()
        for k in ["Name", "Ext", "Size", "Path", "Date"]:
            l = QLabel("-")
            l.setWordWrap(True)
            self.info_labels[k] = l
            form_layout.addRow(f"{k}:", l)
        center_layout.addLayout(form_layout)
        
        self.preview_lbl = SmartMediaWidget(loader=self.image_loader_thread)
        self.preview_lbl.setMinimumSize(100, 100) 
        self.preview_lbl.clicked.connect(self.on_preview_click)
        center_layout.addWidget(self.preview_lbl, 1)
        
        center_btn_layout = QHBoxLayout()
        self.btn_replace = QPushButton("🖼️ Change Thumb")
        self.btn_replace.clicked.connect(self.replace_thumbnail)
        btn_open = QPushButton("📂 Open Folder")
        btn_open.clicked.connect(self.open_current_folder)
        center_btn_layout.addWidget(self.btn_replace)
        center_btn_layout.addWidget(btn_open)
        center_layout.addLayout(center_btn_layout)
        self.splitter.addWidget(center_panel)
        
        # [Right Panel] 기능 버튼 + 탭
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        
        meta_btns = QGridLayout()
        btn_auto = QPushButton("⚡ Auto Match")
        btn_manual = QPushButton("🔗 Manual URL")
        btn_download = QPushButton("⬇️ Download Model")
        
        btn_auto.clicked.connect(lambda: self.run_civitai("auto"))
        btn_manual.clicked.connect(lambda: self.run_civitai("manual"))
        btn_download.clicked.connect(self.download_model_dialog)

        meta_btns.addWidget(btn_auto, 0, 0)
        meta_btns.addWidget(btn_manual, 0, 1)
        meta_btns.addWidget(btn_download, 1, 0)
        right_layout.addLayout(meta_btns)
        
        self.tabs = QTabWidget()
        
        # Tab 1: Note
        self.tab_note = QWidget()
        note_layout = QVBoxLayout(self.tab_note)
        note_layout.setContentsMargins(5,5,5,5)
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
        
        # Tab 2: Example
        self._init_example_tab()
        self.tabs.addTab(self.tab_example, "Example")
        
        # Tab 3: Tasks
        self.task_monitor = TaskMonitorWidget()
        self.tabs.addTab(self.task_monitor, "Tasks")
        
        right_layout.addWidget(self.tabs)
        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([450, 500, 400])
        
        layout.addWidget(self.splitter)
        
        self.status_bar = self.statusBar()

    def _init_example_tab(self):
        self.tab_example = QWidget()
        ex_main_layout = QVBoxLayout(self.tab_example)
        ex_main_layout.setContentsMargins(5,5,5,5)
        self.ex_splitter = QSplitter(Qt.Vertical)
        ex_img_widget = QWidget()
        ex_img_layout = QVBoxLayout(ex_img_widget)
        ex_img_layout.setContentsMargins(0,0,0,0)
        
        self.lbl_ex_img = SmartMediaWidget(loader=self.image_loader_thread)
        self.lbl_ex_img.setMinimumSize(100, 100)
        self.lbl_ex_img.clicked.connect(self.on_example_click)
        
        ex_img_layout.addWidget(self.lbl_ex_img)
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.lbl_ex_count = QLabel("0/0")
        self.lbl_ex_wf = QLabel("No Workflow")
        self.btn_prev.clicked.connect(lambda: self.change_example(-1))
        self.btn_next.clicked.connect(lambda: self.change_example(1))
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.lbl_ex_count)
        nav_layout.addWidget(self.lbl_ex_wf)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_next)
        ex_img_layout.addLayout(nav_layout)
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
        btn_json = QPushButton("📄")
        btn_json.setToolTip("Inject Workflow (JSON)")
        btn_json.clicked.connect(self.inject_workflow)
        btn_save_meta = QPushButton("💾")
        btn_save_meta.setToolTip("Save Metadata")
        btn_save_meta.clicked.connect(self.save_example_metadata)
        for b in [btn_add, btn_del, btn_open, btn_json, btn_save_meta]:
            b.setFixedWidth(40)
            tools_layout.addWidget(b)
        tools_layout.addStretch()
        ex_img_layout.addLayout(tools_layout)
        self.ex_splitter.addWidget(ex_img_widget)
        ex_meta_widget = QWidget()
        ex_meta_layout = QVBoxLayout(ex_meta_widget)
        ex_meta_layout.setContentsMargins(0,0,0,0)
        pos_header = QHBoxLayout()
        pos_header.addWidget(QLabel("Positive:"))
        btn_copy_pos = QPushButton("📋")
        btn_copy_pos.setFixedWidth(30)
        btn_copy_pos.setToolTip("Copy Positive Prompt")
        btn_copy_pos.clicked.connect(lambda: self._copy_to_clipboard(self.txt_ex_pos.toPlainText(), "Positive Prompt"))
        pos_header.addWidget(btn_copy_pos)
        pos_header.addStretch()
        ex_meta_layout.addLayout(pos_header)
        self.txt_ex_pos = QTextEdit()
        self.txt_ex_pos.setPlaceholderText("Positive Prompt")
        ex_meta_layout.addWidget(self.txt_ex_pos, 1)
        neg_header = QHBoxLayout()
        neg_header.addWidget(QLabel("Negative:"))
        btn_copy_neg = QPushButton("📋")
        btn_copy_neg.setFixedWidth(30)
        btn_copy_neg.setToolTip("Copy Negative Prompt")
        btn_copy_neg.clicked.connect(lambda: self._copy_to_clipboard(self.txt_ex_neg.toPlainText(), "Negative Prompt"))
        neg_header.addWidget(btn_copy_neg)
        neg_header.addStretch()
        ex_meta_layout.addLayout(neg_header)
        self.txt_ex_neg = QTextEdit()
        self.txt_ex_neg.setPlaceholderText("Negative Prompt")
        self.txt_ex_neg.setStyleSheet("background-color: #fff0f0;")
        ex_meta_layout.addWidget(self.txt_ex_neg, 1)
        self.param_widgets = {}
        grid_group = QGroupBox("Generation Settings")
        grid_layout = QGridLayout(grid_group)
        params = ["Steps", "Sampler", "CFG", "Seed", "Schedule"]
        for i, p in enumerate(params):
            grid_layout.addWidget(QLabel(p), 0, i)
            le = QLineEdit()
            self.param_widgets[p] = le
            grid_layout.addWidget(le, 1, i)
        ex_meta_layout.addWidget(grid_group)
        self.ex_splitter.addWidget(ex_meta_widget)
        ex_main_layout.addWidget(self.ex_splitter)
        self.ex_splitter.setSizes([500, 300])

    def _copy_to_clipboard(self, text, name):
        if text:
            QApplication.clipboard().setText(text)
            self.status_bar.showMessage(f"{name} copied to clipboard.", 2000)

    def load_config_data(self):
        data = load_config()
        self.app_settings = data.get("__settings__", {})
        # Load directories ONLY from __settings__ to avoid duplication
        # Fallback to root level only for backward compatibility migration
        self.directories = self.app_settings.get("directories", {})
        if not self.directories:
            # Migration: If __settings__['directories'] is empty, check root keys
            root_dirs = {k: v for k, v in data.items() if k != "__settings__"}
            if root_dirs:
                self.directories = root_dirs
                # Auto-migrate: save immediately to fix structure
                self.save_config_data()

    def save_config_data(self):
        # We only save __settings__ at the root, and directories inside it
        self.app_settings["directories"] = self.directories
        data = {"__settings__": self.app_settings}
        save_config(data)

    def apply_font_scale(self):
        scale = int(self.app_settings.get("font_scale", 100))
        new_size = max(6, int(self.default_font_size * (scale / 100.0)))
        font = QApplication.font()
        font.setPointSize(new_size)
        QApplication.setFont(font)
        self.update()
        if self.current_model_path:
             self._load_details(self.current_model_path)

    def update_combo_list(self):
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItems(list(self.directories.keys()))
        self.folder_combo.blockSignals(False)
        if self.directories: self.refresh_list()

    def refresh_list(self):
        if self.folder_combo.count() == 0: return
        name = self.folder_combo.currentText()
        path = self.directories.get(name)
        if not path: return
        
        if hasattr(self, 'scanner') and self.scanner.isRunning():
            self.scanner.stop()
            self.status_bar.showMessage("Stopping previous scan... Click Refresh again shortly.")
            return

        self.path_to_restore = self.current_model_path 

        self.tree.clear()
        self.filter_edit.clear()
        self.scanner = FileScannerWorker(path)
        self.scanner.finished.connect(self._on_scan_finished)
        self.scanner.start()

    def _on_scan_finished(self, structure):
        if not structure and not hasattr(self, 'scanner'): return
        self.tree.setUpdatesEnabled(False)
        if not structure:
             self.status_bar.showMessage("No files found or Scan Cancelled.")
             self.tree.setUpdatesEnabled(True)
             return
        base_path = self.directories.get(self.folder_combo.currentText())
        if not base_path: return
        base_path = os.path.normpath(base_path)
        item_map = {base_path: self.tree.invisibleRootItem()}
        sorted_paths = sorted(structure.keys(), key=lambda x: len(x.split(os.sep)))
        for root in sorted_paths:
            norm_root = os.path.normpath(root)
            if norm_root == base_path:
                current_item = self.tree.invisibleRootItem()
                item_map[norm_root] = current_item
            else:
                parent_dir = os.path.dirname(norm_root)
                parent_item = item_map.get(parent_dir)
                if not parent_item: parent_item = self.tree.invisibleRootItem()
                folder_name = os.path.basename(norm_root)
                current_item = QTreeWidgetItem(parent_item)
                current_item.setText(0, f"📁 {folder_name}")
                current_item.setData(0, Qt.UserRole, norm_root)
                current_item.setData(0, Qt.UserRole + 1, "folder")
                item_map[norm_root] = current_item
        for root in sorted_paths:
            norm_root = os.path.normpath(root)
            current_item = item_map.get(norm_root)
            if not current_item: continue
            files = structure[root].get("files", [])
            for f in files:
                f_item = QTreeWidgetItem(current_item)
                f_item.setText(0, f['name'])
                f_item.setText(1, f['size'])
                f_item.setText(2, f['date'])
                ext = os.path.splitext(f['name'])[1].lower()
                f_item.setText(3, ext)
                f_item.setData(0, Qt.UserRole, f['path'])
                f_item.setData(0, Qt.UserRole + 1, "file")
        
        self.tree.setUpdatesEnabled(True)
        self.status_bar.showMessage("Scan Completed.")

        if self.path_to_restore:
            found = False
            iterator = QTreeWidgetItemIterator(self.tree)
            while iterator.value():
                item = iterator.value()
                data = item.data(0, Qt.UserRole)
                if data == self.path_to_restore:
                    self.tree.setCurrentItem(item)
                    found = True
                    break
                iterator += 1
            
            if found:
                self._load_details(self.path_to_restore)
            else:
                self.current_model_path = None
                self.preview_lbl.set_media(None)
                self.info_labels["Name"].setText("-")
                self.info_labels["Size"].setText("-")
            
            self.path_to_restore = None 

    def filter_model_list(self, text):
        text = text.lower()
        root = self.tree.invisibleRootItem()
        child_count = root.childCount()
        for i in range(child_count):
            folder_item = root.child(i)
            folder_has_visible_child = False
            for j in range(folder_item.childCount()):
                file_item = folder_item.child(j)
                file_name = file_item.text(0).lower()
                if text in file_name:
                    file_item.setHidden(False)
                    folder_has_visible_child = True
                else:
                    file_item.setHidden(True)
            if not text:
                folder_item.setHidden(False)
                folder_item.setExpanded(False)
                for j in range(folder_item.childCount()): folder_item.child(j).setHidden(False)
            else:
                if folder_has_visible_child:
                    folder_item.setHidden(False)
                    folder_item.setExpanded(True)
                else:
                    folder_item.setHidden(True)

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
            if type_ == "file" and path:
                self.current_model_path = path
                self._load_details(path)

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
        except: size_str = "Unknown"; date_str = "Unknown"
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
        cache_dir = self._calculate_cache_path(path)
        model_name = os.path.splitext(filename)[0]
        self.current_json_path = os.path.join(cache_dir, model_name + ".json")
        note_content = ""
        if os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    note_content = json.load(f).get("user_note", "")
            except: pass
        self.txt_edit.setText(note_content)
        self._update_note_display(note_content)
        self._load_examples(path)

    def _update_note_display(self, text):
        scale = int(self.app_settings.get("font_scale", 100))
        font_size_pt = max(8, int(self.default_font_size * (scale / 100.0)))
        css = f"""<style>img {{ max-width: 100%; height: auto; }}
                body {{ color: black; background-color: white; font-size: {font_size_pt}pt; font-family: sans-serif; }}</style>"""
        font = self.txt_edit.font()
        font.setPointSize(font_size_pt)
        self.txt_edit.setFont(font)
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
        if not self.current_model_path: return
        text = self.txt_edit.toPlainText()
        self._save_json_direct(self.current_model_path, text)
        self._update_note_display(text)
        self.btn_edit_note.setChecked(False)
        self.toggle_edit_note()
        self.status_bar.showMessage("Note saved.")

    def _save_json_direct(self, model_path, content):
        cache_dir = self._calculate_cache_path(model_path)
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
        self.worker.status_update.connect(self.status_bar.showMessage)
        self.worker.batch_started.connect(lambda paths: self.task_monitor.add_tasks(paths, task_type="Auto Match"))
        self.worker.task_progress.connect(self.task_monitor.update_task)
        self.worker.model_processed.connect(self._on_model_processed)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.ask_overwrite.connect(self.handle_overwrite_request)
        

        self.worker.start()

    def _on_model_processed(self, success, msg, data, model_path):
        if success:
            desc = data.get("description", "")
            self._save_json_direct(model_path, desc)
            if self.current_model_path == model_path:
                self.txt_edit.setText(desc)
                self._update_note_display(desc)
                self._load_examples(model_path)
                QTimer.singleShot(200, lambda: self._load_details(model_path))

    def _on_worker_finished(self):
        self.status_bar.showMessage("Batch Processed.")
        
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
            default_dir = self.directories.get(root_name)
        if not default_dir:
            default_dir = os.getcwd() 

        dlg = DownloadDialog(default_dir, self)
        if dlg.exec():
            url, target_dir = dlg.get_data()
            if not url:
                QMessageBox.warning(self, "Warning", "URL is required.")
                return
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
            self.status_bar.showMessage(f"Added to queue: {os.path.basename(target_dir)}")
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
        
        # [신규] 중복 확인 시그널 연결
        self.dl_worker.ask_collision.connect(self.handle_download_collision)
        
        self.status_bar.showMessage(f"Starting download...")

        self.dl_worker.start()

    # [신규] 중복 처리 다이얼로그 호출
    def handle_download_collision(self, filename):
        dlg = FileCollisionDialog(filename, self)
        dlg.exec()
        self.dl_worker.set_collision_decision(dlg.result_value)

    def _on_download_progress(self, key, status, percent):
        self.task_monitor.update_task(key, status, percent)

        self.status_bar.showMessage(f"Downloading... {percent}%")

    def _on_download_finished(self, msg, file_path):
        self.status_bar.showMessage(msg)

        self.refresh_list() 
        
        chain_started = False
        # 파일이 성공적으로 생성되었을 때만 오토 매칭 시도
        if file_path and os.path.exists(file_path):
            self.status_bar.showMessage(f"Auto-matching for: {os.path.basename(file_path)}...")
            # 메타데이터 워커가 이미 돌고 있다면 충돌 방지
            if hasattr(self, 'worker') and self.worker.isRunning():
                 pass
            else:
                 self.run_civitai("auto", targets=[file_path])
                 chain_started = True

        # 만약 매칭이 시작되지 않았다면(파일없음/취소/워커Busy 등) 즉시 다음 큐 실행
        if not chain_started:
            self.is_chain_processing = False
            self._process_download_queue()

    def _on_download_error(self, err_msg):
        self.status_bar.showMessage(f"Download Error: {err_msg}")

        QMessageBox.critical(self, "Download Failed", err_msg)
        
        self.is_chain_processing = False
        self._process_download_queue()

    def handle_overwrite_request(self, filename):
        dlg = OverwriteConfirmDialog(filename, self)
        dlg.exec()
        self.worker.set_overwrite_response(dlg.result_value)



    def open_settings(self):
        dlg = SettingsDialog(self, self.app_settings, self.directories)
        if dlg.exec():
            new_data = dlg.get_data()
            self.app_settings.update(new_data)
            self.directories = new_data["directories"]
            self.save_config_data()
            self.apply_font_scale()
            self.update_combo_list()

    def replace_thumbnail(self):
        if not self.current_model_path: return
        
        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select New Thumbnail/Preview", "", filters)
        if not file_path: return
        
        base = os.path.splitext(self.current_model_path)[0]
        ext = os.path.splitext(file_path)[1].lower()
        target_path = base + ext

        # [UI 프리징 방지] 백그라운드 워커로 위임
        self.btn_replace.setEnabled(False)
        self.status_bar.showMessage("Processing thumbnail...")
        
        is_video = (ext in VIDEO_EXTENSIONS)
        self.thumb_worker = ThumbnailWorker(file_path, target_path, is_video)
        self.thumb_worker.finished.connect(self._on_thumb_worker_finished)
        self.thumb_worker.start()

    def _on_thumb_worker_finished(self, success, msg):
        self.btn_replace.setEnabled(True)
        self.status_bar.showMessage(msg)
        if success:
             self._load_details(self.current_model_path)
        else:
             QMessageBox.warning(self, "Error", f"Failed: {msg}")

    def on_preview_click(self):
        path = self.preview_lbl.get_current_path()
        if not path: return
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
            return
        if os.path.exists(path): ZoomWindow(path, self).show()

    def on_example_click(self):
        path = self.lbl_ex_img.get_current_path()
        if not path: return
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
            return
        if os.path.exists(path): ZoomWindow(path, self).show()

    def open_current_folder(self):
        if self.current_model_path:
            f = os.path.dirname(self.current_model_path)
            try:
                os.startfile(f) if platform.system() == "Windows" else subprocess.Popen(["xdg-open", f])
            except Exception as e:
                self.status_bar.showMessage(f"Failed to open folder: {e}")

    def _load_examples(self, model_path):
        self.example_images = []
        self.current_example_idx = 0
        self._clear_example_meta()
        cache_dir = self._calculate_cache_path(model_path)
        preview_dir = os.path.join(cache_dir, "preview")
        if os.path.exists(preview_dir):
            valid_exts = tuple(list(IMAGE_EXTENSIONS) + list(VIDEO_EXTENSIONS))
            self.example_images = [os.path.join(preview_dir, f) for f in os.listdir(preview_dir) if f.lower().endswith(valid_exts)]
            self.example_images.sort()
        self._update_example_ui()

    def _update_example_ui(self):
        total = len(self.example_images)
        if total == 0:
            self.lbl_ex_img.set_media(None)
            self.lbl_ex_count.setText("0/0")
            self.lbl_ex_wf.setText("")
            self._clear_example_meta()
        else:
            self.current_example_idx = max(0, min(self.current_example_idx, total - 1))
            self.lbl_ex_count.setText(f"{self.current_example_idx + 1}/{total}")
            path = self.example_images[self.current_example_idx]
            self.lbl_ex_img.set_media(path)
            
            if os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
                self._parse_and_display_meta(path)
            else:
                self._clear_example_meta()
                self.lbl_ex_wf.setText("Video")

    def change_example(self, delta):
        if not self.example_images: return
        self.current_example_idx = (self.current_example_idx + delta) % len(self.example_images)
        self._update_example_ui()
    
    def add_example_image(self):
        if not self.current_model_path: return
        filters = "Media (*.png *.jpg *.webp *.mp4 *.webm *.gif)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", filters)
        if not files: return
        cache_dir = self._calculate_cache_path(self.current_model_path)
        preview_dir = os.path.join(cache_dir, "preview")
        if not os.path.exists(preview_dir): os.makedirs(preview_dir)
        for f in files:
            try: shutil.copy2(f, preview_dir)
            except: pass
        self._load_examples(self.current_model_path)

    def delete_example_image(self):
        if not self.example_images: return
        path = self.example_images[self.current_example_idx]
        if QMessageBox.question(self, "Delete", "Delete this file?") == QMessageBox.Yes:
            try: os.remove(path)
            except: pass
            self._load_examples(self.current_model_path)

    def open_example_folder(self):
        if not self.example_images: return
        f = os.path.dirname(self.example_images[0])
        try:
            os.startfile(f) if platform.system() == "Windows" else subprocess.Popen(["xdg-open", f])
        except Exception as e:
            self.status_bar.showMessage(f"Failed to open folder: {e}")

    def inject_workflow(self):
        if not self.example_images: return
        path = self.example_images[self.current_example_idx]
        
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
            QMessageBox.warning(self, "Error", "Cannot inject workflow into video files.")
            return

        json_file, _ = QFileDialog.getOpenFileName(self, "Select Workflow", "", "JSON (*.json)")
        if not json_file: return
        try:
            with open(json_file, 'r', encoding='utf-8') as f: wf_data = f.read()
            json.loads(wf_data) 
            img = Image.open(path)
            img.load() 
            metadata = PngInfo()
            if img.info:
                for k, v in img.info.items():
                    if k == "workflow" or k == "prompt": continue
                    if isinstance(v, str): metadata.add_text(k, v)
            metadata.add_text("workflow", wf_data)
            save_kwargs = {"pnginfo": metadata}
            if "exif" in img.info: save_kwargs["exif"] = img.info["exif"]
            if "icc_profile" in img.info: save_kwargs["icc_profile"] = img.info["icc_profile"]
            if not path.lower().endswith(".png"):
                if QMessageBox.question(self, "Convert", "Image must be PNG to store workflow. Convert?") == QMessageBox.Yes:
                    new_path = os.path.splitext(path)[0] + ".png"
                    img.save(new_path, **save_kwargs)
                    img.close()
                    try: os.remove(path)
                    except: pass
                    self.example_images[self.current_example_idx] = new_path
                    path = new_path
                else: return
            else:
                tmp = path + ".tmp.png"
                img.save(tmp, **save_kwargs)
                img.close()
                shutil.move(tmp, path)
            QMessageBox.information(self, "Success", "Workflow replaced successfully.")
            self._parse_and_display_meta(path)
        except Exception as e: QMessageBox.warning(self, "Error", f"Failed to inject workflow: {e}")

    def save_example_metadata(self):
        if not self.example_images: return
        path = self.example_images[self.current_example_idx]
        
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
            QMessageBox.warning(
                self, 
                "Not Supported", 
                "Cannot save metadata to video files.\n\nVideo containers (mp4, webm, etc.) do not support embedding ComfyUI metadata like PNG images do."
            )
            return
        pos = self.txt_ex_pos.toPlainText()
        neg = self.txt_ex_neg.toPlainText()
        params = []
        for k, w in self.param_widgets.items():
            val = w.text()
            if val: params.append(f"{k}: {val}")
        param_str = ", ".join(params)
        full_text = pos
        if neg: full_text += "\nNegative prompt: " + neg
        if param_str: full_text += "\n" + param_str
        try:
            img = Image.open(path)
            meta = PngInfo()
            exclude_keys = {"parameters"} 
            if "workflow" in img.info and isinstance(img.info["workflow"], str):
                meta.add_text("workflow", img.info["workflow"])
                exclude_keys.add("workflow")
            for k, v in img.info.items():
                if k in exclude_keys: continue
                if not isinstance(k, str) or not isinstance(v, str): continue
                try: v.encode('latin-1'); meta.add_text(k, v)
                except UnicodeEncodeError: meta.add_itxt(k, v)
            try: full_text.encode('latin-1'); meta.add_text("parameters", full_text)
            except UnicodeEncodeError: meta.add_itxt("parameters", full_text)
            save_kwargs = {"pnginfo": meta}
            if "exif" in img.info: save_kwargs["exif"] = img.info["exif"]
            if "icc_profile" in img.info: save_kwargs["icc_profile"] = img.info["icc_profile"]
            tmp = path + ".tmp.png"
            img.save(tmp, **save_kwargs)
            shutil.move(tmp, path)
            QMessageBox.information(self, "Success", "Metadata saved.")
        except Exception as e: QMessageBox.warning(self, "Error", str(e))

    def _clear_example_meta(self):
        self.txt_ex_pos.clear()
        self.txt_ex_neg.clear()
        for w in self.param_widgets.values(): w.clear()
        self.lbl_ex_wf.setText("No Workflow")
        self.lbl_ex_wf.setStyleSheet("color: grey")

    def _parse_and_display_meta(self, path):
        self._clear_example_meta()
        try:
            img = Image.open(path)
            info = img.info
            if "workflow" in info or "prompt" in info:
                self.lbl_ex_wf.setText("✅ Workflow")
                self.lbl_ex_wf.setStyleSheet("color: green; font-weight: bold")
            text = info.get("parameters", "")
            if not text and img.format in ["JPEG", "WEBP"]:
                try: 
                    exif = img._getexif()
                    if exif: text = str(exif.get(0x9286, ""))
                except: pass
            if text:
                pos = ""; neg = ""; params = ""
                parts = text.split("Negative prompt:")
                if len(parts) > 1:
                    pos = parts[0].strip()
                    remainder = parts[1]
                else:
                    if "Steps:" in text:
                        pos = text.split("Steps:")[0].strip()
                        remainder = "Steps:" + text.split("Steps:")[1]
                    else:
                        pos = text; remainder = ""
                parts2 = remainder.split("Steps:")
                if len(parts2) > 1:
                    neg = parts2[0].strip()
                    params = "Steps:" + parts2[1]
                else:
                    neg = remainder.strip()
                self.txt_ex_pos.setText(pos)
                self.txt_ex_neg.setText(neg)
                p_map = {}
                for p in params.split(','):
                    if ':' in p: k, v = p.split(':', 1); p_map[k.strip()] = v.strip()
                key_map = {"Steps": "Steps", "Sampler": "Sampler", "CFG scale": "CFG", "Seed": "Seed", "Model": "Model"}
                for k, widget_key in key_map.items():
                    if k in p_map and widget_key in self.param_widgets:
                        self.param_widgets[widget_key].setText(p_map[k])
        except Exception as e: print(f"Meta parse error: {e}")

    def closeEvent(self, event):
        if hasattr(self, 'scanner'): 
            self.scanner.stop()
            self.scanner.wait(1000)
        if hasattr(self, 'worker'): 
            self.worker.stop()
            self.worker.wait(1000)
        if hasattr(self, 'dl_worker'): 
            self.dl_worker.stop()
            self.dl_worker.wait(1000)
        if hasattr(self, 'image_loader_thread'): 
            self.image_loader_thread.stop()
            self.image_loader_thread.wait(1000)
        if hasattr(self, 'thumb_worker'): 
            self.thumb_worker.wait(1000)
        event.accept()
