import os
import sys

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTabWidget, QApplication, QMessageBox
)
from PySide6.QtCore import Qt, QTimer

from .core import load_config, save_config, HAS_PILLOW
from .ui_components import SettingsDialog
from .managers.model import ModelManagerWidget
from .managers.workflow import WorkflowManagerWidget
# from .managers.prompt import PromptManagerWidget # Future

class ModelManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("toyxyz manager")
        self.resize(1500, 950)
        
        self.app_settings = {"civitai_api_key": "", "hf_api_key": "", "font_scale": 100, "cache_path": ""}
        self.directories = {}
        
        # Load Config
        self.load_config_data()
        
        # Apply Font Scale
        self._apply_font_scale()

        if not HAS_PILLOW:
            QTimer.singleShot(500, lambda: QMessageBox.warning(
                self, "Missing Library", "Pillow is missing. Image features will not work.\n\nRun: pip install pillow"
            ))

        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("🤖 toyxyz manager")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        btn_settings = QPushButton("⚙️ Settings")
        btn_settings.clicked.connect(self.open_settings)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(btn_settings)
        layout.addLayout(header)
        
        # Tab Widget (Mode Switcher)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { height: 30px; width: 100px; font-size: 12px; }
        """)
        
        # Initialize Managers
        self.model_manager = ModelManagerWidget(self.directories, self.app_settings, self)
        self.workflow_manager = WorkflowManagerWidget(self.directories, self.app_settings, self)
        # self.prompt_manager = PromptManagerWidget(self.directories, self.app_settings, self)
        self.prompt_manager = QWidget() # Placeholder
        
        self.mode_tabs.addTab(self.model_manager, "Model")
        self.mode_tabs.addTab(self.workflow_manager, "Workflow")
        self.mode_tabs.addTab(self.prompt_manager, "Prompt")
        
        layout.addWidget(self.mode_tabs)
        self.statusBar().showMessage("Ready")

    def load_config_data(self):
        data = load_config()
        self.app_settings = data.get("__settings__", {})
        self.directories = self.app_settings.get("directories", {})

    def save_config_data(self):
        self.app_settings["directories"] = self.directories
        data = {"__settings__": self.app_settings}
        save_config(data)

    def _apply_font_scale(self):
        scale = int(self.app_settings.get("font_scale", 100))
        default_font = QApplication.font()
        default_size = default_font.pointSize()
        if default_size <= 0: default_size = 10
        
        new_size = max(6, int(default_size * (scale / 100.0)))
        font = QApplication.font()
        font.setPointSize(new_size)
        QApplication.setFont(font)

    def open_settings(self):
        dlg = SettingsDialog(self, self.app_settings, self.directories)
        if dlg.exec():
            new_data = dlg.get_data()
            self.app_settings.update(new_data)
            self.directories = new_data["directories"]
            self.save_config_data()
            self._apply_font_scale()
            
            # Refresh all managers
            # We need to re-filter directories for each manager because they might have changed modes or been added/removed
            # For simplicity, we can just re-initialize the combo list in them
            self.model_manager.directories = {k: v for k, v in self.directories.items() if v.get("mode", "model") == "model"}
            self.model_manager.update_combo_list()
            
            self.workflow_manager.directories = {k: v for k, v in self.directories.items() if v.get("mode") == "workflow"}
            self.workflow_manager.update_combo_list()
            
    def closeEvent(self, event):
        # Propagate close to managers to stop threads
        self.model_manager.closeEvent(event)
        self.workflow_manager.closeEvent(event)
        # event.accept() is called inside them, but since we called it manually we might need to verify
        # Actually QMainWindow closeEvent accepts automatically if not ignored.
        event.accept()
