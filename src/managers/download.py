import os
import re
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from ..workers import 模型DownloadWorker
from ..ui_components import FileCollisionDialog

class DownloadController(QObject):
    """
    Manages the download queue and 模型DownloadWorker.
    Emits signals for progress, completion, and queue status.
    """
    download_finished = Signal(str, str) # msg, file_path
    download_error = Signal(str)         # err_msg
    progress_updated = Signal(str, str, int) # key, status, percent
    queue_updated = Signal(int)          # count

    def __init__(self, parent_widget, task_monitor, app_settings):
        super().__init__()
        self.parent_widget = parent_widget # For Dialogs
        self.task_monitor = task_monitor
        self.app_settings = app_settings
        self.download_queue = []
        self.current_worker = None
        self._is_paused = False

    def add_download(self, url, target_dir):
        display_name = "Unknown 模型"
        match_slug = re.search(r'models/\d+/([^/?#]+)', url)
        match_id = re.search(r'models/(\d+)', url)
        if match_slug:
            display_name = match_slug.group(1)
        elif match_id:
            display_name = f"模型 {match_id.group(1)}"
        
        detail_info = f"{display_name} / {os.path.basename(target_dir)}"

        task = {
            'url': url,
            'target_dir': target_dir,
            'display_name': detail_info
        }
        self.download_queue.append(task)
        self.task_monitor.add_row(url, "Download", detail_info, "排队中")
        self.queue_updated.emit(len(self.download_queue))
        
        # Determine if we should start immediately
        # We process if not paused and no worker running
        if not self._is_paused and not self.is_running():
            self.process_next()

    def process_next(self):
        if self._is_paused: return
        if self.is_running(): return
        if not self.download_queue: return

        task = self.download_queue.pop(0)
        self.queue_updated.emit(len(self.download_queue))

        self.current_worker = 模型DownloadWorker(
            task['url'], task['target_dir'], 
            api_key=self.app_settings.get("civitai_api_key"),
            task_key=task['url'] 
        )
        
        self.current_worker.progress.connect(self._on_worker_progress)
        self.current_worker.finished.connect(self._on_worker_finished)
        self.current_worker.error.connect(self._on_worker_error)
        self.current_worker.name_found.connect(self.task_monitor.update_task_name)
        self.current_worker.ask_collision.connect(self.handle_collision)
        self.current_worker.finished.connect(self.current_worker.deleteLater)
        self.current_worker.finished.connect(self._cleanup_worker)
        
        self.current_worker.start()

    def is_running(self):
        if self.current_worker is not None:
            try:
                return self.current_worker.isRunning()
            except RuntimeError:
                self.current_worker = None
        return False

    def stop(self):
        self._is_paused = True
        if self.is_running():
             self.current_worker.stop()
             self.current_worker.wait(1000)
        self.current_worker = None

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False
        self.process_next()

    def handle_collision(self, filename):
        dlg = FileCollisionDialog(filename, self.parent_widget)
        dlg.exec()
        if self.current_worker:
            self.current_worker.set_collision_decision(dlg.result_value)

    def _on_worker_progress(self, key, status, percent):
        self.progress_updated.emit(key, status, percent)
        self.task_monitor.update_task(key, status, percent)

    def _on_worker_finished(self, msg, file_path):
        # Update 任务 Monitor to 完成
        if self.current_worker:
             self.task_monitor.update_task(self.current_worker.task_key, "完成", 100)
        
        self.download_finished.emit(msg, file_path)
        # Note: We do NOT auto-call process_next here to allow owner to inject logic (e.g. metadata chain)
        # The owner must call resume() or process_next() when ready.

    def _on_worker_error(self, err_msg):
        if self.current_worker:
             self.task_monitor.update_task(self.current_worker.task_key, "错误", 0)
             
        self.download_error.emit(err_msg)
        # Similarly, pause or continue? Usually continue on error, but let owner decide?
        # For robustness, we might want to continue.
        # But let's stick to explicit control for now.
        pass

    def _cleanup_worker(self):
        self.current_worker = None
