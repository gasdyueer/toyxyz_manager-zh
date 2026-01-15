import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextBrowser
from PySide6.QtCore import Qt

from .base import BaseManagerWidget
from ..core import SUPPORTED_EXTENSIONS

class PromptManagerWidget(BaseManagerWidget):
    def __init__(self, directories, app_settings, parent_window=None):
        self.parent_window = parent_window
        
        # Filter directories for 'prompt' mode
        prompt_dirs = {k: v for k, v in directories.items() if v.get("mode") == "prompt"}
        super().__init__(prompt_dirs, SUPPORTED_EXTENSIONS["prompt"], app_settings)

    def set_directories(self, directories):
        # Filter directories for 'prompt' mode
        prompt_dirs = {k: v for k, v in directories.items() if v.get("mode") == "prompt"}
        super().set_directories(prompt_dirs)

    # [Fix] Override mode
    def get_mode(self): return "prompt"

    def init_center_panel(self):
        # Initial simple viewer for text prompts
        self.txt_preview = QTextBrowser()
        self.txt_preview.setPlaceholderText("Select a prompt text file to view content...")
        self.center_layout.addWidget(self.txt_preview)

    def init_right_panel(self):
        # Placeholder for right panel (e.g. metadata editor later)
        lbl = QLabel("Prompt Metadata (Coming Soon)")
        lbl.setAlignment(Qt.AlignCenter)
        self.right_layout.addWidget(lbl)
    
    def on_tree_select(self):
        item = self.tree.currentItem()
        if not item: return
        
        path = item.data(0, Qt.UserRole)
        type_ = item.data(0, Qt.UserRole + 1)
        
        if type_ == "file" and path:
            self.current_path = path
            self._load_prompt_content(path)
            
    def _load_prompt_content(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.txt_preview.setText(content)
            
            # Update info in status bar if available
            size = os.path.getsize(path)
            self.show_status_message(f"Loaded: {os.path.basename(path)} ({self.format_size(size)})")
            
        except Exception as e:
            self.txt_preview.setText(f"Error reading file:\n{e}")
            self.show_status_message(f"Error loading file: {e}")
