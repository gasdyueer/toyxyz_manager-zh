import os
import sys
import gc

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
from .managers.gallery import GalleryManagerWidget

class ModelManagerWindow(QMainWindow):
    def __init__(self, debug_mode=False):
        super().__init__()
        self.debug_mode = debug_mode
        self.setWindowTitle("toyxyz 管理器")
        self.resize(1500, 950)
        
        self.app_settings = {"civitai_api_key": "", "hf_api_key": "", "cache_path": ""}
        self.directories = {}
        
        # Load Config
        self.load_config_data()
        
        if not HAS_PILLOW:
            QTimer.singleShot(500, lambda: QMessageBox.warning(
                self, "缺少库", "缺少 Pillow 库。图像功能将无法工作。\n\n运行: pip install pillow"
            ))

        self._init_ui()

        if self.debug_mode:
            self.debug_timer = QTimer(self)
            self.debug_timer.timeout.connect(self._print_debug_stats)
            self.debug_timer.start(3000) # 3 seconds

    def _print_debug_stats(self):
        import threading, logging
        # [Win] Clear console
        os.system('cls' if os.name == 'nt' else 'clear')
        
        info = []
        info.append("=== TOYXYZ 管理器调试模式 ===")
        
        # 1. Global Stats
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            rss_mb = mem_info.rss / 1024 / 1024
            vms_mb = mem_info.vms / 1024 / 1024
            info.append(f"内存 (RSS): {rss_mb:.2f} MB")
            info.append(f"内存 (VMS): {vms_mb:.2f} MB")
        except ImportError:
            info.append(f"内存使用: (psutil not installed) GC Count: {gc.get_count()}")
            
        info.append(f"活动线程: {threading.active_count()}")
        objs = gc.get_objects()
        info.append(f"GC对象: {len(objs)}")

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
            
        info.append(f"详情: 位图={counts['QPixmap']} | 图像={counts['QImage']} | 播放器={counts['QMediaPlayer']} | 视频窗口={counts['QVideoWidget']} | 线程={counts['QThread']}")
        
        # 2. Managers
        if hasattr(self, 'model_manager'):
            m_stats = self.model_manager.get_debug_info()
            info.append(f"\n[模型 Manager]")
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
        
        # 3. Active Media 详情s
        info.append(f"\n[Active Media]")
        
        # Collect from 模型 Manager
        if hasattr(self, 'model_manager'):
            # Preview image
            if hasattr(self.model_manager, 'preview_lbl'):
                media_info = self.model_manager.preview_lbl.get_media_info()
                if media_info:
                    info.append(f"  [模型 Preview] {media_info['filename']}")
                    info.append(f"    类型: {media_info['type']} | Size: {media_info['size_mb']:.2f}MB | Res: {media_info.get('resolution', 'N/A')}")
                    if media_info['type'] == 'video':
                        info.append(f"    Playing: {media_info.get('playing', False)} | Duration: {media_info.get('duration_sec', 0):.1f}s")
            
            # Example tab images
            if hasattr(self.model_manager, 'tab_example'):
                example_media = self.model_manager.tab_example.lbl_img.get_media_info()
                if example_media:
                    info.append(f"  [Example] {example_media['filename']}")
                    info.append(f"    类型: {example_media['type']} | Size: {example_media['size_mb']:.2f}MB | Res: {example_media.get('resolution', 'N/A')}")
                    if example_media['type'] == 'video':
                        info.append(f"    Playing: {example_media.get('playing', False)} | Duration: {example_media.get('duration_sec', 0):.1f}s")

        print("\n".join(info))
        logging.info("\n" + "\n".join(info))

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Header
        header = QHBoxLayout()
        # [User Request] Remove redundant title/icon, place 设置 button here instead
        btn_settings = QPushButton("⚙️ 设置")
        btn_settings.setToolTip("打开应用程序设置")
        btn_settings.clicked.connect(self.open_settings)
        header.addWidget(btn_settings)
        header.addStretch() # Push everything else to right (if any)
        layout.addLayout(header)
        
        # Tab Widget (模式 Switcher)
        self.mode_tabs = QTabWidget()
        # self.mode_tabs.setStyleSheet(...) -> Moved to QSS
        
        # Initialize 任务 Monitor (Global)
        self.task_monitor = TaskMonitorWidget()

        # Initialize Managers
        self.model_manager = ModelManagerWidget(self.directories, self.app_settings, self.task_monitor, self)
        self.workflow_manager = WorkflowManagerWidget(self.directories, self.app_settings, self.task_monitor, self)
        self.prompt_manager = PromptManagerWidget(self.directories, self.app_settings, self)
        
        self.mode_tabs.addTab(self.model_manager, "模型")
        self.mode_tabs.addTab(self.workflow_manager, "工作流")
        self.mode_tabs.addTab(self.prompt_manager, "提示词")
        
        self.gallery_manager = GalleryManagerWidget(self.directories, self.app_settings, self)
        self.mode_tabs.addTab(self.gallery_manager, "画廊")
        
        self.mode_tabs.addTab(self.task_monitor, "任务")
        
        # [Video Memory Optimization] Handle tab switching
        self.mode_tabs.currentChanged.connect(self._on_tab_changed)
        
        layout.addWidget(self.mode_tabs)
        self.statusBar().showMessage("就绪")

    def _on_tab_changed(self, index):
        """Handle tab switching to release resources of hidden tabs."""
        # Get current widget
        current_widget = self.mode_tabs.widget(index)
        
        # Notify all managers about visibility change
        for i in range(self.mode_tabs.count()):
            widget = self.mode_tabs.widget(i)
            if widget == current_widget:
                if hasattr(widget, 'on_tab_shown'):
                    widget.on_tab_shown()
            else:
                if hasattr(widget, 'on_tab_hidden'):
                    widget.on_tab_hidden()

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
            if hasattr(self, 'gallery_manager'): self.gallery_manager.set_directories(self.directories)
            
    def closeEvent(self, event):
        # Propagate close to managers to stop threads
        managers = []
        if hasattr(self, 'model_manager'): managers.append(self.model_manager)
        if hasattr(self, 'workflow_manager'): managers.append(self.workflow_manager)
        if hasattr(self, 'prompt_manager'): managers.append(self.prompt_manager)
        if hasattr(self, 'gallery_manager'): managers.append(self.gallery_manager)
        
        # Phase 0: Collect Workers (Preserve state before stopping)
        collected_data = {}
        for mgr in managers:
             if hasattr(mgr, 'collect_active_workers'):
                 try:
                     collected_data[mgr] = mgr.collect_active_workers()
                 except Exception:
                     collected_data[mgr] = None
             else:
                 collected_data[mgr] = None

        # Phase 1: Signal Stop (Parallel)
        for mgr in managers:
            try:
                if collected_data[mgr]:
                    workers, _, heavy_workers = collected_data[mgr]
                    if hasattr(mgr, 'signal_workers_stop'):
                        mgr.signal_workers_stop(workers, heavy_workers)
                elif hasattr(mgr, 'stop_all_workers'):
                    # Fallback (Should be rare as all inherit BaseManager)
                    pass 
            except Exception: pass

        # Phase 2: Wait for Stop (Parallel-ish)
        for mgr in managers:
            try:
                if collected_data[mgr]:
                    workers, thumb_workers, heavy_workers = collected_data[mgr]
                    if hasattr(mgr, 'wait_workers_stop'):
                        mgr.wait_workers_stop(workers, thumb_workers, heavy_workers)
                elif hasattr(mgr, 'stop_all_workers'):
                    mgr.stop_all_workers()
            except Exception: pass
        
        event.accept()
