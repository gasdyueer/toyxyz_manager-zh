import os
import time
import logging
from typing import Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
    QLabel, QPushButton, QComboBox, QLineEdit, QMessageBox, QAbstractItemView,
    QFileDialog, QApplication, QFormLayout
)
from PySide6.QtCore import Qt, QThread, QSize

from ..workers import FileScannerWorker, ThumbnailWorker, FileSearchWorker, ImageLoader
from ..ui_components import ZoomWindow, MarkdownNoteWidget
from .example import ExampleTabWidget
from ..core import VIDEO_EXTENSIONS, PREVIEW_EXTENSIONS, calculate_structure_path

class WrappingLabel(QLabel):
    """QLabel that wraps text without pushing parent layout wider."""
    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        return QSize(0, sh.height())

    def setText(self, text):
        # Insert zero-width space after path separators to allow wrapping
        if text:
            text = text.replace("\\", "\\\u200b").replace("/", "/\u200b").replace("_", "_\u200b")
        super().setText(text)

class SortableTreeItem(QTreeWidgetItem):
    def __lt__(self, other):
        # 1. Always prioritize Folders over Files
        # 'folder' < 'file' ?
        # We want folders to appear FIRST. 
        # In Ascending order, we want Small < Large. So Folder < File.
        # In Descending order, QTreeWidget reverses the result. So File < Folder?
        # This means in Descending, Files would come first.
        # To strictly keep folders on top is tricky without custom proxy model.
        # For now, let's just make sure "Folder" < "File" so in standard Ascending sort (default), it works.
        
        my_type = self.data(0, Qt.UserRole + 1)
        other_type = other.data(0, Qt.UserRole + 1)
        
        if my_type != other_type:
            # If I am folder (0) and other is file (1)
            # We want me < other
            return my_type == "folder"
            
        # Same type: sort by text (case insensitive)
        t1 = self.text(0).lower()
        t2 = other.text(0).lower()
        return t1 < t2

class BaseManagerWidget(QWidget):
    def __init__(self, directories: Dict[str, Any], extensions, app_settings: Dict[str, Any] = None):
        super().__init__()
        self.directories = directories
        self.extensions = extensions
        self.app_settings = app_settings or {}
        self.current_path = None
        self.active_scanners = []
        self.image_loader_thread = ImageLoader()
        self.image_loader_thread.start()
        self._init_base_ui()
        self.update_combo_list()
        
    # ... (rest of class)

    def get_debug_info(self) -> Dict[str, Any]:
        """Returns debug statistics for the manager."""
        info = {
            "scanners_active": len(self.active_scanners),
            "search_active": hasattr(self, 'search_worker') and self.search_worker and self.search_worker.isRunning(),
            "loader_queue": len(self.image_loader_thread.queue),
            "tree_items": self.tree.topLevelItemCount()
        }
        return info

    @staticmethod
    def format_size(size_bytes):
        if size_bytes >= 1073741824: return f"{size_bytes / 1073741824:.2f} GB"
        elif size_bytes >= 1048576: return f"{size_bytes / 1048576:.2f} MB"
        elif size_bytes >= 1024: return f"{size_bytes / 1024:.2f} KB"
        return f"{size_bytes} B"

    @staticmethod
    def format_date(mtime, seconds=False):
        if mtime <= 0: return "-"
        fmt = '%Y-%m-%d %H:%M:%S' if seconds else '%Y-%m-%d %H:%M'
        return time.strftime(fmt, time.localtime(mtime))

    def save_note_for_path(self, path, text, silent=False):
        if not path: return
        try:
            filename = os.path.basename(path)
            model_name = os.path.splitext(filename)[0]
            # [Fix] Added mode argument
            cache_dir = calculate_structure_path(path, self.get_cache_dir(), self.directories, mode=self.get_mode())
            md_path = os.path.join(cache_dir, model_name + ".md")
            
            # [FIX] Create directory if it doesn't exist
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
            
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(text)
                
            if not silent:
                self.show_status_message("Note saved (.md).")
        except Exception as e: 
            logging.error(f"Save 错误: {e}")
            self.show_status_message(f"Save 失败: {e}")

    def _init_base_ui(self):
        main_layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)
        # self.splitter.setStyleSheet(...) -> Moved to QSS
        
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
        self.filter_edit.setPlaceholderText("🔍 搜索")
        self.filter_edit.returnPressed.connect(self.search_files)
        
        self.btn_search = QPushButton("搜索")
        self.btn_search.setToolTip("在当前目录中递归搜索文件")
        self.btn_search.clicked.connect(self.search_files)
        
        self.btn_search_back = QPushButton("⬅️ 返回")
        self.btn_search_back.setToolTip("返回完整列表（清除搜索）")
        self.btn_search_back.setEnabled(False) # Default hidden/disabled
        self.btn_search_back.clicked.connect(self.cancel_search)
        
        search_layout.addWidget(self.filter_edit)
        search_layout.addWidget(self.btn_search)
        search_layout.addWidget(self.btn_search_back)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "大小", "日期", "格式"])
        self.tree.setColumnWidth(0, 200) 
        self.tree.setColumnWidth(1, 70)  
        self.tree.setColumnWidth(2, 110) 
        self.tree.setColumnWidth(3, 70)
        # self.tree.setStyleSheet(...) -> Moved to QSS
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True) # [Fix] Enable Sorting
        self.tree.sortByColumn(0, Qt.AscendingOrder) # Default sort by 名称
        self.tree.itemSelectionChanged.connect(self.on_tree_select)
        self.tree.itemExpanded.connect(self.on_tree_expand)
        
        left_layout.addLayout(combo_box)
        left_layout.addLayout(search_layout)
        left_layout.addWidget(self.tree)
        
        # Hook for additional left-side widgets (e.g. New File button)
        self.init_left_bottom(left_layout)
        
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
    def init_left_bottom(self, layout): pass
    def on_tree_select(self): pass
    
    def _setup_info_panel(self, extra_fields: list = None):
        """Helper to create standard info panel (名称, Size, 路径, Date + Extras)."""
        extra_fields = extra_fields or []
        # Standard fields: 名称 is always first. Size, 路径, Date are always last.
        # Extras inserted in between.
        target_fields = ["名称"] + extra_fields + ["大小", "路径", "日期"]
        
        self.info_labels = {}
        form_layout = QFormLayout()
        
        for k in target_fields:
            l = WrappingLabel("-")
            l.setWordWrap(True)
            self.info_labels[k] = l
            form_layout.addRow(f"{k}:", l)
            
        # Duplicate Warning
        self.lbl_duplicate_warning = QLabel("")
        self.lbl_duplicate_warning.setObjectName("DuplicateWarning")
        self.lbl_duplicate_warning.setWordWrap(True)
        self.lbl_duplicate_warning.hide()
        form_layout.addRow(self.lbl_duplicate_warning)
        
        self.center_layout.addLayout(form_layout)

    # Hook for getting current mode, defaulted to 'model' if not overridden
    def get_mode(self): return "model"

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
        
        if hasattr(self, 'indexing_scanner'):
             try:
                 if self.indexing_scanner.isRunning():
                     self.indexing_scanner.stop()
                     self.indexing_scanner.wait()
             except RuntimeError: pass

        # [Fix] Stop all active partial scanners to prevent zombie signals
        if hasattr(self, 'active_scanners'):
            for scanner in list(self.active_scanners):
                try:
                    if scanner.isRunning():
                        scanner.stop()
                except RuntimeError: pass
            self.active_scanners.clear()

        self.tree.clear()
        self.filter_edit.clear()
        
        # [Duplicate Check] Initialize File Map
        # Key: filename (lowercase), Value: list of full paths
        self.file_map = {} 
        
        # [Thread Safety] Track active thumbnail workers
        self.active_thumb_workers = set()
        
        # 1. UI Scanner (Fast, Non-Recursive)
        self.tree.setSortingEnabled(False) # [Optimization] Disable sorting for entire scan
        self.scanner = FileScannerWorker(path, self.extensions, recursive=False)
        self.scanner.batch_ready.connect(self._on_batch_ready)
        self.scanner.finished.connect(self._on_scan_finished) # [Optimization] New slot
        self.scanner.finished.connect(self.scanner.deleteLater) 
        self.scanner.start()
        
        # 2. Indexing Scanner (Background, Recursive for full duplicate check)
        self.indexing_scanner = FileScannerWorker(path, self.extensions, recursive=True)
        self.indexing_scanner.setObjectName("IndexingScannerThread")
        self.indexing_scanner.batch_ready.connect(self._on_indexing_batch_ready)
        self.indexing_scanner.finished.connect(self.indexing_scanner.deleteLater)
        self.indexing_scanner.start()
        # [Optimization] Low priority for background indexing to prevent UI jank
        self.indexing_scanner.setPriority(QThread.LowPriority)
        
        # Disable Back button when in normal list view
        if hasattr(self, 'btn_search_back'):
            self.btn_search_back.setEnabled(False)

    def _on_batch_ready(self, current_dir, dirs, files):
        self.tree.setUpdatesEnabled(False)
        
        # Find the parent item for 'current_dir'
        # Since this is the initial scan (non-recursive), current_dir SHOULD be the root path
        # But if we change it to recursive later, we need to find the item.
        
        # Check if current_dir matches the root
        name = self.folder_combo.currentText()
        data = self.directories.get(name)
        raw_path = data.get("path") if isinstance(data, dict) else data
        base_path = os.path.normpath(raw_path)
        
        parent_item = self.tree.invisibleRootItem()
        
        # If the batch is for a subdirectory (not currently supported in initial refresh but good for safety)
        if os.path.normpath(current_dir) != base_path:
             # Find item by path... (Optimization: Too slow for large trees?)
             # Since initial scan is recursive=False, we always populate root.
             pass
        
        # [Optimization] Sorting is disabled globally during scan
        # self.tree.setSortingEnabled(False) 
        
        # Construct data dict as expected by _populate_item
        root_data = {"dirs": dirs, "files": files}
        self._populate_item(parent_item, current_dir, root_data)

        self.tree.setUpdatesEnabled(True)
        # [Optimization] Sorting re-enabled only at end of scan
        # self.tree.setSortingEnabled(True)

    def _on_scan_finished(self):
        """Called when INITIAL UI scan is complete."""
        self.tree.setSortingEnabled(True)
        # self.show_status_message(f"Scan complete. {self.tree.topLevelItemCount()} items.")

    def _populate_item(self, parent_item, current_path, data):
        # ... (Unchanged logic, just ensure no sorting calls here)
        # 1. Add Folders
        dirs = data.get("dirs", [])
        # Sort folders by name
        dirs.sort(key=lambda s: s.lower())
        
        for d_name in dirs:
            d_path = os.path.join(current_path, d_name)
            d_item = SortableTreeItem(parent_item) # [Fix] Use SortableItem
            d_item.setText(0, f"📁 {d_name}")
            d_item.setData(0, Qt.UserRole, d_path)
            d_item.setData(0, Qt.UserRole + 1, "folder")
            
            # Add Dummy Item to enable expansion
            dummy = QTreeWidgetItem(d_item) # Dummy doesn't need to be sortable, or maybe yes?
            dummy.setText(0, "Loading...")
            dummy.setData(0, Qt.UserRole, "DUMMY")

        # 2. Add Files
        files = data.get("files", [])
        # Files are already sorted or we can sort here
        files.sort(key=lambda x: x['name'].lower())
        
        for f in files:
            f_item = SortableTreeItem(parent_item) # [Fix] Use SortableItem
            f_item.setText(0, f['name'])
            f_item.setText(1, f['size'])
            f_item.setText(2, f['date'])
            ext = os.path.splitext(f['name'])[1].lower()
            f_item.setText(3, ext)
            f_item.setData(0, Qt.UserRole, f['path'])
            f_item.setData(0, Qt.UserRole + 1, "file")
            
            # [Duplicate Check] Update Global File Map (Initial visible items)
            f_name_lower = f['name'].lower()
            if f_name_lower not in self.file_map:
                self.file_map[f_name_lower] = []
            if f['path'] not in self.file_map[f_name_lower]:
                self.file_map[f_name_lower].append(f['path'])

    def _on_indexing_batch_ready(self, root, dirs, files):
        """Background worker updates the file map for full duplicate detection."""
        for f in files:
            f_name_lower = f['name'].lower()
            f_path = f['path']
            
            if f_name_lower not in self.file_map:
                self.file_map[f_name_lower] = []
            
            if f_path not in self.file_map[f_name_lower]:
                self.file_map[f_name_lower].append(f_path)
        
        # If currently selected item has duplicates, update warning immediately
        if self.current_path:
            cur_name = os.path.basename(self.current_path).lower()
            if cur_name in self.file_map and len(self.file_map[cur_name]) > 1:
                # Trigger re-selection logic to refresh warning
                # We can call on_tree_select manually or just update warning if we refactor warning logic.
                # For now, let's just re-simulate selection if it's the current item
                # But on_tree_select expects an item.
                # Simpler: Update the warning label directly if method exists (it's in subclass)
                # Or verify if we can call something generic.
                # Let's check subclasses... or just rely on user re-clicking? 
                # Better: Emit a signal or call a refresh method.
                self._refresh_duplicate_warning()

    def _refresh_duplicate_warning(self):
        if self.get_mode() == "gallery": return

        # Subclasses can override or we implement generic if label is standard
        # ModelManagerWidget has lbl_duplicate_warning
        if hasattr(self, 'lbl_duplicate_warning') and self.current_path:
             f_name = os.path.basename(self.current_path).lower()
             duplicates = self.file_map.get(f_name, [])
             if len(duplicates) > 1:
                 # Exclude current path (More robust comparison)
                 curr_norm = os.path.normcase(os.path.abspath(self.current_path))
                 other_paths = [p for p in duplicates if os.path.normcase(os.path.abspath(p)) != curr_norm]
                 
                 msg = f"⚠️ Duplicate Found ({len(duplicates)})"
                 if other_paths:
                     msg += "\n" + "\n".join(other_paths)
                 
                 tooltip = "Same filename detected in:\n" + "\n".join(duplicates)
                 self.lbl_duplicate_warning.setText(msg)
                 self.lbl_duplicate_warning.setToolTip(tooltip)
                 self.lbl_duplicate_warning.show()
             else:
                 self.lbl_duplicate_warning.hide()

    def on_tree_expand(self, item):
        # Check if it has a dummy child
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) == "DUMMY":
            # Remove dummy
            item.takeChild(0)
            
            path = item.data(0, Qt.UserRole)
            if not path or not os.path.isdir(path): return
            
            self.tree.setSortingEnabled(False) # [Optimization] Disable sort for lazy load
            
            worker = FileScannerWorker(path, self.extensions, recursive=False)
            # Connect to batch signal, reusing the logic to populate THIS item
            worker.batch_ready.connect(lambda p, d, f: self._on_partial_batch_ready(item, p, d, f))
            worker.finished.connect(lambda: self.tree.setSortingEnabled(True)) # [Optimization] Re-enable
            worker.finished.connect(worker.deleteLater) # Cleanup thread
            
            # [Fix] Remove from active list when done to prevent accessing deleted objects
            worker.finished.connect(lambda: self.active_scanners.remove(worker) if worker in self.active_scanners else None)
            
            self.active_scanners.append(worker)
            worker.start()

    def _on_partial_batch_ready(self, parent_item, current_path, dirs, files):
        # [Fix] Critical Crash Prevention:
        # If the parent_item (QTreeWidgetItem) has been deleted by a refresh/clear operation
        # while this signal was in flight, accessing it will raise RuntimeError.
        try:
             # Just checking if 'parent_item' is valid.
             # Accessing any method on a deleted C++ object raises RuntimeError.
             if not parent_item or parent_item.childCount() < 0: 
                 return
                 
             self.tree.setUpdatesEnabled(False)
             # self.tree.setSortingEnabled(False) # [Optimization] Handled in on_tree_expand
            
             root_data = {"dirs": dirs, "files": files}
             self._populate_item(parent_item, current_path, root_data)
            
             self.tree.setUpdatesEnabled(True)
             # self.tree.setSortingEnabled(True) # [Optimization] Handled in on_tree_expand finished
        except RuntimeError:
             # "wrapped C/C++ object of type SortableTreeItem has been deleted"
             # This is expected during rapid refreshes. Ignore.
             pass


    # _on_partial_scan_finished REMOVED (Replaced by _on_partial_batch_ready)

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

        if hasattr(self, 'scanner'):
            try:
                if self.scanner.isRunning(): self.scanner.stop()
            except RuntimeError: pass

        if hasattr(self, 'search_worker'):
            try:
                if self.search_worker.isRunning(): self.search_worker.stop()
            except RuntimeError: pass

        self.tree.clear()
        
        # Loading Indicator
        loading = QTreeWidgetItem(self.tree)
        loading.setText(0, "搜索中...")
        
        self.filter_edit.setEnabled(False)
        self.btn_search.setEnabled(False)
        if hasattr(self, 'btn_search_back'): self.btn_search_back.setEnabled(False)
        
        self.search_worker = FileSearchWorker(root_path, query, self.extensions)
        self.search_worker.finished.connect(self._on_search_finished)
        self.search_worker.finished.connect(self.search_worker.deleteLater) # Cleanup thread
        self.search_worker.start()

    def _on_search_finished(self, results):
        self.filter_edit.setEnabled(True)
        self.btn_search.setEnabled(True)
        if hasattr(self, 'btn_search_back'):
            self.btn_search_back.setEnabled(True)
        self.tree.clear()
        
        if not results:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, "No results found.")
            return
            
        # [Safety] Cap results to prevent UI freeze
        total_found = len(results)
        if total_found > 2000:
            results = results[:2000]
            self.show_status_message(f"Search results capped to 2000 items (found {total_found})")

        # Sort by name
        results.sort(key=lambda x: os.path.basename(x[0]).lower())
        
        for item_data in results:
            # Handle both old (2 items) and new (4 items) formats for safety, though only new will be emitted
            path = item_data[0]
            
            # Unpack stats if available
            size_bytes = 0
            mtime = 0
            if len(item_data) >= 4:
                size_bytes = item_data[2]
                mtime = item_data[3]
            
            name = os.path.basename(path)
            item = SortableTreeItem(self.tree)
            item.setText(0, name)
            item.setToolTip(0, path) 
            
            # Format Size
            size_str = self.format_size(size_bytes)
            
            # Format Date
            date_str = self.format_date(mtime)

            item.setText(1, size_str) 
            item.setText(2, date_str)
            
            ext = os.path.splitext(name)[1].lower()
            item.setText(3, ext)
            
            item.setData(0, Qt.UserRole, path)
            item.setData(0, Qt.UserRole + 1, "file")

    def cancel_search(self):
        self.filter_edit.clear()
        self.refresh_list()

    def show_status_message(self, msg, duration=3000):
        if hasattr(self, 'parent_window') and self.parent_window:
            self.parent_window.statusBar().showMessage(msg, duration)
        else:
            logging.info(f"[状态] {msg}")

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
            logging.warning(f"Cleanup error: {e}")
        
        is_video = (ext in VIDEO_EXTENSIONS)
        
        # [Fix] Invalidate cache for the target path to ensure UI updates
        if hasattr(self, 'image_loader_thread'):
            self.image_loader_thread.remove_from_cache(target_path)
            
        self.thumb_worker = ThumbnailWorker(file_path, target_path, is_video)
        self.thumb_worker.finished.connect(self._on_thumb_worker_finished)
        
        # [Thread Safety] Track worker
        if not hasattr(self, 'active_thumb_workers'): self.active_thumb_workers = set()
        self.active_thumb_workers.add(self.thumb_worker)
        self.thumb_worker.finished.connect(lambda: self._cleanup_thumb_worker(self.thumb_worker))
        
        self.thumb_worker.start()

    def _cleanup_thumb_worker(self, worker):
        if hasattr(self, 'active_thumb_workers') and worker in self.active_thumb_workers:
            self.active_thumb_workers.discard(worker)
        worker.deleteLater()

    def _on_thumb_worker_finished(self, success, msg):
        if hasattr(self, 'btn_replace'): self.btn_replace.setEnabled(True)
        self.show_status_message(msg)
        if success:
             # Refresh details - assumes subclasses implement _load_details
             if hasattr(self, '_load_details'): self._load_details(self.current_path)
        else:
             QMessageBox.warning(self, "错误", f"失败: {msg}")

    def on_preview_click(self):
        if not hasattr(self, 'preview_lbl'): return
        path = self.preview_lbl.get_current_path()
        if path and os.path.exists(path) and os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
            ZoomWindow(path, self).show()

    # === Shared Content Logic (Note/Example) ===
    
    def setup_content_tabs(self):
        """Initializes the standard Note and Example tabs."""
        from PySide6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        
        # Tab 1: Note
        self.tab_note = MarkdownNoteWidget()
        self.tab_note.save_requested.connect(self.save_note)
        self.tab_note.set_media_handler(self.handle_media_insert)
        self.tabs.addTab(self.tab_note, "Note")
        
        # Tab 2: Example
        # [Refactor] Pass cache_root explicitely
        self.tab_example = ExampleTabWidget(self.directories, self.app_settings, self, self.image_loader_thread, cache_root=self.get_cache_dir(), mode=self.get_mode())
        self.tab_example.status_message.connect(self.show_status_message)
        self.tabs.addTab(self.tab_example, "Example")
        
        return self.tabs

    def load_content_data(self, path):
        """Loads note content from .md file and initializes examples."""
        if not path: return

        filename = os.path.basename(path)
        # [Fix] Added mode argument
        cache_dir = calculate_structure_path(path, self.get_cache_dir(), self.directories, mode=self.get_mode())
        model_name = os.path.splitext(filename)[0]
        md_path = os.path.join(cache_dir, model_name + ".md")
        
        note_content = ""
        if os.path.exists(md_path):
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    note_content = f.read()
            except OSError: pass
            
        if hasattr(self, 'tab_note'): self.tab_note.set_text(note_content)
        if hasattr(self, 'tab_example'): self.tab_example.load_examples(path)

    def save_note(self, text):
        if not self.current_path: return
        self.save_note_for_path(self.current_path, text)

    def handle_media_insert(self, mtype):
        if not self.current_path: 
            QMessageBox.warning(self, "错误", "No item selected.")
            return None
            
        if mtype not in ["image", "video"]: return None
        
        filters = "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.gif)"
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select {mtype.title()}", "", filters)
        if not file_path: return None
        
        return self.copy_media_to_cache(file_path, self.current_path)

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
        
        # [Fix] Added mode argument
        cache_dir = calculate_structure_path(target_relative_path, self.get_cache_dir(), self.directories, mode=self.get_mode())
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
            self.show_status_message(f"失败 to copy media: {e}")
            return None

    def closeEvent(self, event):
        self.stop_all_workers()
        super().closeEvent(event)

    def stop_all_workers(self):
        """
        [Optimization] Parallel shutdown sequence.
        Phase 1: Signal all threads to stop.
        Phase 2: Wait for threads with a global timeout.
        """
    def stop_all_workers(self):
        """
        [Optimization] Parallel shutdown sequence.
        Phase 1: Signal all threads to stop.
        Phase 2: Wait for threads with a global timeout.
        """
        workers, thumb_workers, heavy_workers = self.collect_active_workers()
        self.signal_workers_stop(workers, heavy_workers)
        self.wait_workers_stop(workers, thumb_workers, heavy_workers)

    def collect_active_workers(self):
        workers = [] # Fast workers (Scanners, Search)
        heavy_workers = [] # Slow IO workers (ImageLoader, Metadata)

        # Collect all active workers
        if hasattr(self, 'active_scanners'):
            workers.extend([w for w in self.active_scanners if w.isRunning()])
            self.active_scanners.clear()
            
        try:
            if hasattr(self, 'scanner') and self.scanner and self.scanner.isRunning():
                workers.append(self.scanner)
        except RuntimeError: pass

        try:
            if hasattr(self, 'indexing_scanner') and self.indexing_scanner and self.indexing_scanner.isRunning():
                workers.append(self.indexing_scanner)
        except RuntimeError: pass

        try:
            if hasattr(self, 'search_worker') and self.search_worker and self.search_worker.isRunning():
                workers.append(self.search_worker)
        except RuntimeError: pass

        try:
            if hasattr(self, 'image_loader_thread') and self.image_loader_thread and self.image_loader_thread.isRunning():
                 heavy_workers.append(self.image_loader_thread)
        except RuntimeError: pass

        # Collect thumbnail workers
        thumb_workers = []
        if hasattr(self, 'active_thumb_workers'):
            thumb_workers = list(self.active_thumb_workers)
            self.active_thumb_workers.clear()
        
        # [NEW] Collect LocalMetadataWorker from ExampleTabWidget
        if hasattr(self, 'tab_example') and hasattr(self.tab_example, 'metadata_worker'):
            try:
                if self.tab_example.metadata_worker and self.tab_example.metadata_worker.isRunning():
                    heavy_workers.append(self.tab_example.metadata_worker)
            except RuntimeError:
                pass
        
        return workers, thumb_workers, heavy_workers

    def signal_workers_stop(self, workers=None, heavy_workers=None):
        if workers is None:
             workers, _, heavy_workers = self.collect_active_workers() # Re-collect if needed
        
        if heavy_workers is None: heavy_workers = []

        all_stop_workers = workers + heavy_workers
        logging.debug(f"[StopAllWorkers] Stopping {len(all_stop_workers)} workers...")

        # Phase 1: Send Stop Signal (for those that support it)
        for w in all_stop_workers:
            try:
                if hasattr(w, 'stop'):
                    w.stop()
            except RuntimeError: pass
            # ThumbnailWorker doesn't have stop(), it just runs until completion (copy is blocking usually)

    def wait_workers_stop(self, workers=None, thumb_workers=None, heavy_workers=None):
        if workers is None:
             workers, thumb_workers, heavy_workers = self.collect_active_workers()
        
        if thumb_workers is None: thumb_workers = []
        if heavy_workers is None: heavy_workers = []

        # Phase 2: Wait for workers
        
        # 1. Wait for Scanners & Searchers (Fast)
        for w in workers:
            try:
                if w.isRunning():
                    logging.debug(f"[StopAllWorkers] Waiting for {w.object名称() if w.object名称() else 'Worker'}...")
                    w.wait(1000) # 1 sec each
                    logging.debug(f"[StopAllWorkers] {w.object名称() if w.object名称() else 'Worker'} finished.")
            except RuntimeError: pass

        # 2. Wait for Thumbnail workers
        for w in thumb_workers:
            try:
                if w.isRunning():
                    logging.debug(f"[StopAllWorkers] Waiting for ThumbnailWorker...")
                    w.wait(500)
            except RuntimeError: pass
            
        # 3. Wait for Heavy Workers (ImageLoader, Metadata)
        for w in heavy_workers:
            try:
                if w.isRunning():
                    name = w.object名称() if w.object名称() else str(w)
                    logging.debug(f"[StopAllWorkers] Waiting for {name} (3s timeout)...")
                    # Give it ample time (e.g. 3s)
                    if not w.wait(3000):
                        logging.warning(f"[StopAllWorkers] {name} stuck. Forcing termination.")
                        # Terminate is dangerous but prevents the "Destroyed while running" error on exit
                        w.terminate()
                        w.wait()
                        logging.warning(f"[StopAllWorkers] {name} terminated.")
                    else:
                        logging.debug(f"[StopAllWorkers] {name} exited gracefully.")
            except RuntimeError: pass
            
        logging.debug("[StopAllWorkers] Cleanup complete.")

    # [Memory Optimization] Tab Visibility Hooks
    def on_tab_hidden(self):
        """Called when this manager tab is hidden (user switched to another tab)."""
        import logging
        logger = logging.getLogger("managers.base")
        logger.debug(f"[BaseManager] Tab hidden: {self.__class__.__name__}")
        
        # Release preview player resources
        if hasattr(self, 'preview_lbl') and hasattr(self.preview_lbl, 'release_resources'):
            self.preview_lbl.release_resources()
            
        # Stop example videos
        if hasattr(self, 'tab_example') and hasattr(self.tab_example, 'stop_videos'):
            self.tab_example.stop_videos()

    def on_tab_shown(self):
        """Called when this manager tab is shown."""
        # Optional: Restore resources if needed, but lazy loading usually handles it
        pass

    def cleanup(self):
        """Called on app exit"""
        self.stop_all_workers()
        # Ensure we also release video resources on exit
        self.on_tab_hidden()



    def _load_common_file_details(self, path):
        """
        Refactored common logic for loading file details.
        Returns: (filename, size_str, date_str, preview_path)
        """
        filename = os.path.basename(path)
        
        # [Log] Debug
        logging.debug(f"[_load_common_file_details] Loading details for: {path}")

        try:
            st = os.stat(path)
            size_str = self.format_size(st.st_size)
            date_str = self.format_date(st.st_mtime, seconds=True)
        except (OSError, ValueError) as e:
            logging.error(f"失败 to stat file {path}: {e}")
            size_str = "错误"
            date_str = "错误"
            
        # Duplicate Check
        if self.get_mode() != "gallery" and hasattr(self, 'file_map') and self.lbl_duplicate_warning:
            f_name_lower = filename.lower()
            duplicates = self.file_map.get(f_name_lower, [])
            if len(duplicates) > 1:
                 logging.debug(f"[Duplicate] Found {len(duplicates)} duplicates for {filename}")
                 # Exclude current path from display
                 curr_norm = os.path.normcase(os.path.abspath(path))
                 other_paths = [p for p in duplicates if os.path.normcase(os.path.abspath(p)) != curr_norm]
                 
                 msg = f"⚠️ Duplicate Files Found ({len(duplicates)})"
                 if other_paths:
                     msg += "\n" + "\n".join(other_paths)

                 tooltip = "Same filename detected in:\n" + "\n".join(duplicates)
                 self.lbl_duplicate_warning.setText(msg)
                 self.lbl_duplicate_warning.setToolTip(tooltip)
                 self.lbl_duplicate_warning.show()
            else:
                 self.lbl_duplicate_warning.hide()

        # Find Thumbnail Common Logic
        base = os.path.splitext(path)[0]
        preview_path = None
        for ext in PREVIEW_EXTENSIONS:
            if os.path.exists(base + ext):
                preview_path = base + ext
                break
        
        return filename, size_str, date_str, preview_path
