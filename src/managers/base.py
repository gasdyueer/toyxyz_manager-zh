import os
from typing import Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
    QLabel, QPushButton, QComboBox, QLineEdit, QMessageBox, QAbstractItemView
)
from PySide6.QtCore import Qt

from ..workers import FileScannerWorker

class BaseManagerWidget(QWidget):
    def __init__(self, directories: Dict[str, Any], extensions):
        super().__init__()
        self.directories = directories
        self.extensions = extensions
        self.current_path = None
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
        btn_refresh.clicked.connect(self.refresh_list)
        combo_box.addWidget(self.folder_combo, 1)
        combo_box.addWidget(btn_refresh)
        
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Filter...")
        self.filter_edit.textChanged.connect(self.filter_list)
        
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
        
        path = data.get("path") if isinstance(data, dict) else data
        
        if hasattr(self, 'scanner') and self.scanner.isRunning():
            self.scanner.stop()
            # Wait or just ignore, standard is to wait but we want responsiveness
            
        self.tree.clear()
        self.filter_edit.clear()
        self.scanner = FileScannerWorker(path, self.extensions)
        self.scanner.finished.connect(self._on_scan_finished)
        self.scanner.start()

    def _on_scan_finished(self, structure):
        if not structure and not hasattr(self, 'scanner'): return
        self.tree.setUpdatesEnabled(False)
        
        name = self.folder_combo.currentText()
        data = self.directories.get(name)
        base_path = data.get("path") if isinstance(data, dict) else data
        if not base_path: return
        base_path = os.path.normpath(base_path)
        
        item_map = {base_path: self.tree.invisibleRootItem()}
        sorted_paths = sorted(structure.keys(), key=lambda x: len(x.split(os.sep)))
        
        for root in sorted_paths:
            norm_root = os.path.normpath(root)
            if norm_root == base_path:
                item_map[norm_root] = self.tree.invisibleRootItem()
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

    def filter_list(self, text):
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
