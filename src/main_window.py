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
from .managers.prompt import PromptManagerWidget

class ModelManagerWindow(QMainWindow):
    def __init__(self, debug_mode=False):
        super().__init__()
        self.debug_mode = debug_mode
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

        if self.debug_mode:
            self.debug_timer = QTimer(self)
            self.debug_timer.timeout.connect(self._print_debug_stats)
            self.debug_timer.start(3000) # 3 seconds

    def _print_debug_stats(self):
        import os, gc, threading, logging
        # [Win] Clear console
        os.system('cls' if os.name == 'nt' else 'clear')
        
        info = []
        info.append("=== TOYXYZ MANAGER DEBUG MODE ===")
        
        # 1. Global Stats
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            rss_mb = mem_info.rss / 1024 / 1024
            vms_mb = mem_info.vms / 1024 / 1024
            info.append(f"Memory (RSS): {rss_mb:.2f} MB")
            info.append(f"Memory (VMS): {vms_mb:.2f} MB")
        except ImportError:
            info.append(f"Memory Usage: (psutil not installed) GC Count: {gc.get_count()}")
            
        info.append(f"Active Threads: {threading.active_count()}")
        objs = gc.get_objects()
        info.append(f"GC Objects: {len(objs)}")

        # [Debug] Granular Object Counting
        from PySide6.QtGui import QPixmap, QImage
        from PySide6.QtCore import QThread, QByteArray
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        
        counts = {"QPixmap": 0, "QImage": 0, "QMediaPlayer": 0, "QVideoWidget": 0, "QThread": 0}
        for o in objs:
            try:
                if isinstance(o, QPixmap): counts["QPixmap"] += 1
                elif isinstance(o, QImage): counts["QImage"] += 1
                elif isinstance(o, QMediaPlayer): counts["QMediaPlayer"] += 1
                elif isinstance(o, QVideoWidget): counts["QVideoWidget"] += 1
                elif isinstance(o, QThread): counts["QThread"] += 1
            except: pass
            
        info.append(f"Details: Pixmap={counts['QPixmap']} | Image={counts['QImage']} | Player={counts['QMediaPlayer']} | VideoW={counts['QVideoWidget']} | Thread={counts['QThread']}")
        
        # 2. Managers
        if hasattr(self, 'model_manager'):
            m_stats = self.model_manager.get_debug_info()
            info.append(f"\n[Model Manager]")
            info.append(f"  - Scanners: {m_stats['scanners_active']}")
            info.append(f"  - Loader Queue: {m_stats['loader_queue']}")
            info.append(f"  - Tree Items: {m_stats['tree_items']}")
            info.append(f"  - DL Queue: {m_stats['download_queue_size']}")
            info.append(f"  - Meta Queue: {m_stats['metadata_queue_size']}")
            info.append(f"  - Video Active: {m_stats['video_player_active']} ({m_stats['video_player_state']})")
            
            ex_stats = m_stats.get('example_tab_stats', {})
            info.append(f"  - [Examples] Files: {ex_stats.get('file_list_count')} | Active Mem: {ex_stats.get('est_memory_mb', 0):.2f} MB | GC Cnt: {ex_stats.get('gc_counter')}")

        if hasattr(self, 'workflow_manager'):
            w_stats = self.workflow_manager.get_debug_info()
            info.append(f"\n[Workflow Manager]")
            info.append(f"  - Scanners: {w_stats['scanners_active']}")
            info.append(f"  - Loader Queue: {w_stats['loader_queue']}")

        print("\n".join(info))
        logging.info("\n" + "\n".join(info))

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
        # Tab Widget (Mode Switcher)
        self.mode_tabs = QTabWidget()
        # self.mode_tabs.setStyleSheet(...) -> Moved to QSS
        
        # Initialize Task Monitor (Global)
        self.task_monitor = TaskMonitorWidget()

        # Initialize Managers
        self.model_manager = ModelManagerWidget(self.directories, self.app_settings, self.task_monitor, self)
        self.workflow_manager = WorkflowManagerWidget(self.directories, self.app_settings, self.task_monitor, self)
        self.prompt_manager = PromptManagerWidget(self.directories, self.app_settings, self)
        
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
            self.prompt_manager.set_directories(self.directories)
            
    def closeEvent(self, event):
        # Propagate close to managers to stop threads
        if hasattr(self, 'model_manager'): self.model_manager.stop_all_workers()
        if hasattr(self, 'workflow_manager'): self.workflow_manager.stop_all_workers()
        if hasattr(self, 'prompt_manager'): self.prompt_manager.stop_all_workers()
        
        event.accept()
