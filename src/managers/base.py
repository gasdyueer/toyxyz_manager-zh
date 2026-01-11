import os
from typing import Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
    QLabel, QPushButton, QComboBox, QLineEdit, QMessageBox, QAbstractItemView,
    QFileDialog, QApplication
)
from PySide6.QtCore import Qt

from ..workers import FileScannerWorker, ThumbnailWorker, FileSearchWorker
from ..ui_components import ZoomWindow
from ..core import VIDEO_EXTENSIONS

class BaseManagerWidget(QWidget):
    def __init__(self, directories: Dict[str, Any], extensions, app_settings: Dict[str, Any] = None):
        super().__init__()
        self.directories = directories
        self.extensions = extensions
        self.app_settings = app_settings or {}
        self.current_path = None
        self.active_scanners = []
        self._init_base_ui()
        self.update_combo_list()

    def _init_base_ui(self):
        main_layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle:horizontal {
                width: 15px;
            }
            QSplitter::handle:vertical {
                height: 15px;
            }
        """)
        
        # [Left Panel] 
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0,0,0,0)
        
        combo_box = QHBoxLayout()
        self.folder_combo = QComboBox()
        self.folder_combo.currentIndexChanged.connect(self.refresh_list)
        btn_refresh = QPushButton("🔄")
        btn_refresh.setToolTip("Refresh file list")
        btn_refresh.clicked.connect(self.refresh_list)
        combo_box.addWidget(self.folder_combo, 1)
        combo_box.addWidget(btn_refresh)
        
        # [Search UI]
        search_layout = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Search... (Enter)")
        self.filter_edit.returnPressed.connect(self.search_files)
        
        self.btn_search = QPushButton("Search")
        self.btn_search.setToolTip("Search files in the current directory (Recursive)")
        self.btn_search.clicked.connect(self.search_files)
        
        search_layout.addWidget(self.filter_edit)
        search_layout.addWidget(self.btn_search)
        
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
        self.tree.itemExpanded.connect(self.on_tree_expand)
        
        left_layout.addLayout(combo_box)
        left_layout.addLayout(search_layout)
        left_layout.addWidget(self.tree)
        self.splitter.addWidget(left_panel)
        
        # [Center Panel] - To be filled by subclasses
        self.center_panel = QWidget()
        self.center_layout = QVBoxLayout(self.center_panel)
        self.init_center_panel()
        self.splitter.addWidget(self.center_panel)
        
        # [Right Panel] - To be filled by subclasses
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0,0,0,0)
        self.init_right_panel()
        self.splitter.addWidget(self.right_panel)
        
        self.splitter.setSizes([450, 500, 400])
        main_layout.addWidget(self.splitter)

    # Hooks for subclasses
    def init_center_panel(self): pass
    def init_right_panel(self): pass
    def on_tree_select(self): pass

    def set_directories(self, directories):
        """Updates the directories and refreshes the combo box."""
        self.directories = directories
        self.update_combo_list()

    def update_combo_list(self):
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        # Subclasses should filter directories by mode if needed, 
        # but here we might just show all or let subclass handle it.
        # Actually, let's make it data-driven. The passed `directories` 
        # should only contain the relevant ones for this mode.
        self.folder_combo.addItems(list(self.directories.keys()))
        self.folder_combo.blockSignals(False)
        if self.directories: self.refresh_list()

    def refresh_list(self):
        if self.folder_combo.count() == 0: return
        name = self.folder_combo.currentText()
        data = self.directories.get(name)
        if not data: return
        
        raw_path = data.get("path") if isinstance(data, dict) else data
        # [Fix] Normalize path here to ensure consistency with worker and popup logic
        path = os.path.normpath(raw_path)
        
        if hasattr(self, 'scanner') and self.scanner.isRunning():
            self.scanner.stop()
            
        self.tree.clear()
        self.filter_edit.clear()
        # Initial scan is non-recursive (Lazy Load)
        self.scanner = FileScannerWorker(path, self.extensions, recursive=False)
        self.scanner.finished.connect(self._on_scan_finished)
        self.scanner.start()

    def _on_scan_finished(self, structure):
        if not structure and not hasattr(self, 'scanner'): return
        self.tree.setUpdatesEnabled(False)
        
        # Re-resolve path to ensure we use the same key
        name = self.folder_combo.currentText()
        data = self.directories.get(name)
        raw_path = data.get("path") if isinstance(data, dict) else data
        if not raw_path: return
        base_path = os.path.normpath(raw_path)

        # Retrieve root data - structure keys usually match the path passed to worker
        # but to be safe against trailing slashes differences, we can check directly or normalized
        root_data = structure.get(base_path)
        
        # Fallback: if not found by strict key, try to find a key that is equivalent
        if not root_data:
            for k, v in structure.items():
                if os.path.normpath(k) == base_path:
                    root_data = v
                    break
        
        if root_data:
            self._populate_item(self.tree.invisibleRootItem(), base_path, root_data)

        self.tree.setUpdatesEnabled(True)

    def _populate_item(self, parent_item, current_path, data):
        # 1. Add Folders
        dirs = data.get("dirs", [])
        # Sort folders by name
        dirs.sort(key=lambda s: s.lower())
        
        for d_name in dirs:
            d_path = os.path.join(current_path, d_name)
            d_item = QTreeWidgetItem(parent_item)
            d_item.setText(0, f"📁 {d_name}")
            d_item.setData(0, Qt.UserRole, d_path)
            d_item.setData(0, Qt.UserRole + 1, "folder")
            
            # Add Dummy Item to enable expansion
            dummy = QTreeWidgetItem(d_item)
            dummy.setText(0, "Loading...")
            dummy.setData(0, Qt.UserRole, "DUMMY")

        # 2. Add Files
        files = data.get("files", [])
        # Files are already sorted or we can sort here
        files.sort(key=lambda x: x['name'].lower())
        
        for f in files:
            f_item = QTreeWidgetItem(parent_item)
            f_item.setText(0, f['name'])
            f_item.setText(1, f['size'])
            f_item.setText(2, f['date'])
            ext = os.path.splitext(f['name'])[1].lower()
            f_item.setText(3, ext)
            f_item.setData(0, Qt.UserRole, f['path'])
            f_item.setData(0, Qt.UserRole + 1, "file")

    def on_tree_expand(self, item):
        # Check if it has a dummy child
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) == "DUMMY":
            # Remove dummy
            item.takeChild(0)
            
            path = item.data(0, Qt.UserRole)
            if not path or not os.path.isdir(path): return
            
            worker = FileScannerWorker(path, self.extensions, recursive=False)
            worker.finished.connect(lambda s: self._on_partial_scan_finished(s, item, worker))
            self.active_scanners.append(worker)
            worker.start()

    def _on_partial_scan_finished(self, structure, parent_item, worker):
        if worker in self.active_scanners:
             self.active_scanners.remove(worker)
        
        path = parent_item.data(0, Qt.UserRole)
        # Normalize just in case
        path = os.path.normpath(path)
        
        # structure keys might be subtly different (os.scandir path sep), so check carefully
        # But usually key is exactly what we passed
        root_data = structure.get(path)
        
        self.tree.setUpdatesEnabled(False)
        if root_data:
            self._populate_item(parent_item, path, root_data)
        else:
            # Empty folder or error, maybe add (Empty) label?
            # For now just leave empty
            pass
        self.tree.setUpdatesEnabled(True)

    def search_files(self):
        query = self.filter_edit.text().strip()
        if not query:
            self.refresh_list()
            return

        name = self.folder_combo.currentText()
        if not name: return
        data = self.directories.get(name)
        
        raw_path = data.get("path") if isinstance(data, dict) else data
        root_path = os.path.normpath(raw_path)

        if hasattr(self, 'scanner') and self.scanner.isRunning(): self.scanner.stop()
        if hasattr(self, 'search_worker') and self.search_worker.isRunning(): self.search_worker.stop()

        self.tree.clear()
        
        # Loading Indicator
        loading = QTreeWidgetItem(self.tree)
        loading.setText(0, "Searching...")
        
        self.filter_edit.setEnabled(False)
        self.btn_search.setEnabled(False)
        
        self.search_worker = FileSearchWorker(root_path, query, self.extensions)
        self.search_worker.finished.connect(self._on_search_finished)
        self.search_worker.start()

    def _on_search_finished(self, results):
        self.filter_edit.setEnabled(True)
        self.btn_search.setEnabled(True)
        self.tree.clear()
        
        if not results:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, "No results found.")
            return
            
        # Sort by name
        results.sort(key=lambda x: os.path.basename(x[0]).lower())
        
        for path, type_ in results:
            name = os.path.basename(path)
            item = QTreeWidgetItem(self.tree)
            item.setText(0, name)
            item.setToolTip(0, path) # Show full path in tooltip
            
            # Simple metadata (can't afford full stat for all results easily, maybe later)
            item.setText(1, "-") 
            item.setText(2, "-")
            
            ext = os.path.splitext(name)[1].lower()
            item.setText(3, ext)
            
            item.setData(0, Qt.UserRole, path)
            item.setData(0, Qt.UserRole + 1, "file")

    def show_status_message(self, msg, duration=3000):
        if hasattr(self, 'parent_window') and self.parent_window:
            self.parent_window.statusBar().showMessage(msg, duration)
        else:
            print(f"[Status] {msg}")

    def get_cache_dir(self):
        # Allow app_settings to define cache path, or fallback to default
        custom_path = ""
        if hasattr(self, 'app_settings'):
            custom_path = self.app_settings.get("cache_path", "").strip()
        
        if custom_path and os.path.isdir(custom_path):
            return custom_path
            
        from ..core import CACHE_DIR_NAME
        if not os.path.exists(CACHE_DIR_NAME):
            try: os.makedirs(CACHE_DIR_NAME)
            except OSError: pass
        return CACHE_DIR_NAME

    def replace_thumbnail(self):
        if not self.current_path: return
        
        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select New Thumbnail/Preview", "", filters)
        if not file_path: return
        
        base = os.path.splitext(self.current_path)[0]
        ext = os.path.splitext(file_path)[1].lower()
        target_path = base + ext
        
        if hasattr(self, 'btn_replace'): self.btn_replace.setEnabled(False)
        
        # Unload image to be safe against file locks
        if hasattr(self, 'preview_lbl'): self.preview_lbl.set_media(None)
        QApplication.processEvents()

        self.show_status_message("Processing thumbnail...")

        # [Fix] Remove existing preview files to ensure the new one takes precedence
        # (e.g., .mp4 takes priority over .jpg, so we must remove .mp4 if replacing with .jpg)
        from ..core import PREVIEW_EXTENSIONS
        try:
            for p_ext in PREVIEW_EXTENSIONS:
                p_path = base + p_ext
                if os.path.exists(p_path) and os.path.abspath(p_path) != os.path.abspath(target_path):
                    try: os.remove(p_path)
                    except OSError: pass
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        is_video = (ext in VIDEO_EXTENSIONS)
        self.thumb_worker = ThumbnailWorker(file_path, target_path, is_video)
        self.thumb_worker.finished.connect(self._on_thumb_worker_finished)
        self.thumb_worker.start()

    def _on_thumb_worker_finished(self, success, msg):
        if hasattr(self, 'btn_replace'): self.btn_replace.setEnabled(True)
        self.show_status_message(msg)
        if success:
             # Refresh details - assumes subclasses implement _load_details
             if hasattr(self, '_load_details'): self._load_details(self.current_path)
        else:
             QMessageBox.warning(self, "Error", f"Failed: {msg}")

    def on_preview_click(self):
        if not hasattr(self, 'preview_lbl'): return
        path = self.preview_lbl.get_current_path()
        if path and os.path.exists(path) and os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
            ZoomWindow(path, self).show()

    def open_current_folder(self):
        if self.current_path:
            f = os.path.dirname(self.current_path)
            try: os.startfile(f)
            except OSError: pass

    # Re-implementing helper methods to be used by subclasses
    
    def copy_media_to_cache(self, file_path, target_relative_path):
        import shutil
        from ..core import calculate_structure_path
        
        if not target_relative_path: return None
        
        cache_dir = calculate_structure_path(target_relative_path, self.get_cache_dir(), self.directories)
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        
        name = os.path.basename(file_path)
        dest_path = os.path.join(cache_dir, name)
        
        try:
            shutil.copy2(file_path, dest_path)
            # Return Markdown/HTML snippet
            dest_path_fwd = dest_path.replace("\\", "/")
            ext = os.path.splitext(name)[1].lower()
            if ext in ['.mp4', '.webm', '.mkv']:
                return f'<video src="{dest_path_fwd}" controls width="100%"></video>'
            else:
                return f"![{name}]({dest_path_fwd})"
        except Exception as e:
            self.show_status_message(f"Failed to copy media: {e}")
            return None

