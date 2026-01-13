import os
import sys

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTabWidget, QApplication, QMessageBox
)
from PySide6.QtCore import Qt, QTimer

from .core import load_config, save_config, HAS_PILLOW
from .ui_components import SettingsDialog, TaskMonitorWidget
from .managers.model import ModelManagerWidget
from .managers.workflow import WorkflowManagerWidget
# from .managers.prompt import PromptManagerWidget # Future

class ModelManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("toyxyz manager")
        self.resize(1500, 950)
        
        self.app_settings = {"civitai_api_key": "", "hf_api_key": "", "cache_path": ""}
        self.directories = {}
        
        # Load Config
        self.load_config_data()
        
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
        # [User Request] Remove redundant title/icon, place Settings button here instead
        btn_settings = QPushButton("⚙️ Settings")
        btn_settings.setToolTip("Open Application Settings")
        btn_settings.clicked.connect(self.open_settings)
        header.addWidget(btn_settings)
        header.addStretch() # Push everything else to right (if any)
        layout.addLayout(header)
        
        # Tab Widget (Mode Switcher)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { height: 30px; width: 100px; font-size: 12px; }
        """)
        
        # Initialize Task Monitor (Global)
        self.task_monitor = TaskMonitorWidget()

        # Initialize Managers
        self.model_manager = ModelManagerWidget(self.directories, self.app_settings, self.task_monitor, self)
        self.workflow_manager = WorkflowManagerWidget(self.directories, self.app_settings, self.task_monitor, self)
        # self.prompt_manager = PromptManagerWidget(self.directories, self.app_settings, self)
        self.prompt_manager = QWidget() # Placeholder
        
        self.mode_tabs.addTab(self.model_manager, "Model")
        self.mode_tabs.addTab(self.workflow_manager, "Workflow")
        self.mode_tabs.addTab(self.prompt_manager, "Prompt")
        self.mode_tabs.addTab(self.task_monitor, "Tasks")
        
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

    def open_settings(self):
        dlg = SettingsDialog(self, self.app_settings, self.directories)
        if dlg.exec():
            new_data = dlg.get_data()
            # new_data contains '__settings__' which is self.app_settings itself
            self.directories = new_data["directories"]
            self.save_config_data()
            
            # Refresh all managers using the new method
            self.model_manager.set_directories(self.directories)
            self.workflow_manager.set_directories(self.directories)
            
    def closeEvent(self, event):
        # Propagate close to managers to stop threads
        self.model_manager.closeEvent(event)
        self.workflow_manager.closeEvent(event)
        # event.accept() is called inside them, but since we called it manually we might need to verify
        # Actually QMainWindow closeEvent accepts automatically if not ignored.
        event.accept()
