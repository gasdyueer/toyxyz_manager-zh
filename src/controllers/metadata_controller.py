import os
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox, QInputDialog

# Import Worker and Dialogs
from ..workers import MetadataWorker
from ..ui_components import OverwriteConfirmDialog
from ..core import calculate_structure_path

class MetadataController(QObject):
    # Signals to update UI
    status_message = Signal(str, int)  # msg, duration
    task_progress = Signal(str, str, int) # key, status, percent
    batch_started = Signal(list) # paths
    batch_processed = Signal()
    model_processed = Signal(bool, str, dict, str) # success, msg, data, path

    def __init__(self, app_settings, directories, parent=None):
        super().__init__(parent)
        self.app_settings = app_settings
        self.directories = directories
        self.parent_widget = parent # For dialogs
        self.worker = None
        self.queue = [] # Queue of (mode, targets, manual_url, overwrite_behavior)

    def run_civitai(self, mode, targets, manual_url_override=None, overwrite_behavior_override=None):
        if not targets: return

        # Validate Manual 模式
        manual_url = None
        if mode == "manual":
            if manual_url_override:
                manual_url = manual_url_override
            else:
                if len(targets) > 1:
                    QMessageBox.warning(self.parent_widget, "Warning", "Manual mode supports only single file selection.")
                    return
                # Ask UI for input (Blocking)
                url, ok = QInputDialog.getText(self.parent_widget, "Manual URL", "Enter Civitai or HuggingFace 模型 URL:")
                if not ok or not url: return
                manual_url = url

        # Overwrite Check Logic (Pre-check)
        final_targets = list(targets)
        worker_overwrite = 'ask'

        if overwrite_behavior_override:
            worker_overwrite = overwrite_behavior_override
        else:
            # Check for conflicts
            conflicts = self._check_conflicts(targets)
            if conflicts and not manual_url_override:
                # Ask user
                msg = f"Found existing metadata for {len(conflicts)} files.\nOverwrite them?"
                reply = QMessageBox.question(
                    self.parent_widget, "Metadata Exists", msg,
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                if reply == QMessageBox.Cancel:
                    return
                elif reply == QMessageBox.No:
                    final_targets = [t for t in targets if t not in conflicts]
                    if not final_targets:
                        self.status_message.emit("All tasks skipped (Metadata exists).", 3000)
                        return
                elif reply == QMessageBox.Yes:
                    worker_overwrite = 'yes_all'

        if not final_targets: return

        # Enqueue or Run
        if self.worker and self.worker.isRunning():
            self.queue.append((mode, final_targets, manual_url, worker_overwrite))
            self.status_message.emit(f"任务 queued. (Queue size: {len(self.queue)})", 3000)
        else:
            self._start_worker(mode, final_targets, manual_url, worker_overwrite)

    def _start_worker(self, mode, targets, manual_url, overwrite_behavior):
        cache_path = self.app_settings.get("cache_path", "")
        # Fallback logic for cache path is in core, but worker takes root.
        # It's better to ensure we pass a valid one or None to let worker decide
        if not cache_path: cache_path = None 

        self.worker = MetadataWorker(
            mode, targets, manual_url,
            civitai_key=self.app_settings.get("civitai_api_key", ""),
            hf_key=self.app_settings.get("hf_api_key", ""),
            cache_root=cache_path,
            directories=self.directories,
            overwrite_behavior=overwrite_behavior
        )

        # Connect Worker Signals
        self.worker.status_update.connect(lambda msg: self.status_message.emit(msg, 0))
        self.worker.batch_started.connect(self.batch_started.emit)
        self.worker.task_progress.connect(self.task_progress.emit)
        self.worker.model_processed.connect(self.model_processed.emit)
        
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.ask_overwrite.connect(self._handle_overwrite_request)
        
        self.worker.start()

    def _on_worker_finished(self):
        self.batch_processed.emit()
        self.worker = None
        self._process_next_in_queue()

    def _process_next_in_queue(self):
        if self.queue:
            item = self.queue.pop(0)
            mode, targets, manual_url, overwrite_beh = item
            self.status_message.emit(f"Processing queued task... ({len(self.queue)} remaining)", 3000)
            self._start_worker(mode, targets, manual_url, overwrite_beh)
        else:
            self.status_message.emit("All tasks completed.", 3000)

    def _handle_overwrite_request(self, filename):
        # Must be run on UI thread (Controller lives in UI thread usually)
        dlg = OverwriteConfirmDialog(filename, self.parent_widget)
        dlg.exec()
        if self.worker:
            self.worker.set_overwrite_response(dlg.result_value)

    def _check_conflicts(self, targets):
        """Checks if metadata exists."""
        conflicts = []
        # Need cache root logic that matches BaseManager...
        # We can duplicate the simple logic or ask App设置
        cache_root = self.app_settings.get("cache_path", "")
        if not cache_root:
             from ..core import CACHE_DIR_NAME
             cache_root = CACHE_DIR_NAME

        for path in targets:
            cache_dir = calculate_structure_path(path, cache_root, self.directories)
            if not os.path.exists(cache_dir): continue
            
            name = os.path.splitext(os.path.basename(path))[0]
            if os.path.exists(os.path.join(cache_dir, name + ".json")):
                conflicts.append(path)
            elif os.path.exists(os.path.join(cache_dir, name + ".md")):
                 conflicts.append(path)
                 
        return conflicts

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(500)
        self.queue.clear()
