import os
import gc
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, 
    QSizePolicy, QDialog, QLineEdit, QFileDialog, QDialogButtonBox, 
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, 
    QFormLayout, QSpinBox, QListWidget, QInputDialog, QGridLayout, QGroupBox, 
    QApplication, QMessageBox, QComboBox, QTextBrowser, QTextEdit
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QMimeData, QSize, QBuffer, QByteArray
from PySide6.QtGui import QPixmap, QDrag, QBrush, QColor, QImageReader
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from .core import VIDEO_EXTENSIONS

# ==========================================
# Smart Media Widget
# ==========================================
class SmartMediaWidget(QWidget):
    clicked = Signal()

    def __init__(self, parent=None, loader=None):
        super().__init__(parent)
        self.loader = loader
        self.current_path = None
        self.is_video = False
        self._drag_start_pos = None

        self.play_timer = QTimer()
        self.play_timer.setSingleShot(True)
        self.play_timer.setInterval(50) 
        self.play_timer.timeout.connect(self._start_video_playback)

        self.stack = QStackedWidget(self)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.stack)
        self.setLayout(main_layout)

        self.lbl_image = QLabel("No Media")
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image = QLabel("No Media")
        self.lbl_image.setObjectName("media_label")
        self.lbl_image.setAlignment(Qt.AlignCenter)
        # self.lbl_image.setStyleSheet(...) -> Moved to QSS
        self._original_pixmap = None
        
        self.stack.addWidget(self.lbl_image)
        # Video components will be initialized lazily
        self.video_widget = None
        self.media_player = None
        self.audio_output = None

        if self.loader:
            self.loader.image_loaded.connect(self._on_image_loaded)

    def _init_video_components(self):
        if self.media_player: return
        
        self.video_widget = QVideoWidget()
        self.video_widget = QVideoWidget()
        # self.video_widget.setStyleSheet(...) -> Moved to QSS
        self.stack.addWidget(self.video_widget)
        
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.audio_output.setVolume(0)
        self.media_player.setLoops(QMediaPlayer.Infinite)
        self.media_player.errorOccurred.connect(self._on_media_error)

    def _destroy_video_components(self):
        if self.media_player:
            self.media_player.stop()
            self.media_player.setSource(QUrl())
            self.media_player.setVideoOutput(None)
            self.media_player.deleteLater()
            self.media_player = None
            
        if self.audio_output:
            self.audio_output.deleteLater()
            self.audio_output = None
            
        if self.video_widget:
            self.stack.removeWidget(self.video_widget)
            self.video_widget.close() # Explicitly close native window
            self.video_widget.deleteLater()
            self.video_widget = None

    def _stop_video_playback(self):
        """Stops playback and releases file lock without destroying components."""
        if self.media_player:
            self.media_player.stop()
            self.media_player.setSource(QUrl())
            # Do NOT detach video output here, to allow instant reuse.

    def set_media(self, path, target_width=1024):
        self.play_timer.stop()
        
        # [Memory] Force memory release check
        if not path:
             # Reuse: Just stop playback and show default image
             self._stop_video_playback()
             self.lbl_image.clear()
             self._original_pixmap = None
             self.current_path = None
             self.is_video = False
             self.stack.setCurrentWidget(self.lbl_image)
             self.lbl_image.setText("No Media")
             return
             
        self.current_path = path # Update current_path here

        if not os.path.exists(path):
            self._destroy_video_components()
            self.is_video = False
            self.stack.setCurrentWidget(self.lbl_image)
            self.lbl_image.setText("No Media")
            return

        ext = os.path.splitext(path)[1].lower()
        
        if ext in VIDEO_EXTENSIONS:
            # Reuse or Init
            if not self.media_player:
                self._init_video_components()
            
            # Stop previous if any
            if self.media_player.playbackState() == QMediaPlayer.PlayingState:
                self.media_player.stop()
            
            self.is_video = True
            self.stack.setCurrentWidget(self.video_widget)
            
            self.media_player.setSource(QUrl.fromLocalFile(path))
            self.media_player.play()
            # The play_timer is no longer strictly needed for initial playback
            # as setSource and play are called directly.
            # However, if there's a specific reason for a delayed start, it can remain.
            # For now, we'll keep it as per the instruction, but its effect might be minimal.
            self.play_timer.start() 
        else:
            # Not a video -> Stop video but keep components for future reuse
            if self.is_video: 
                self._stop_video_playback()
            
            self.is_video = False
            self.stack.setCurrentWidget(self.lbl_image)
            self.lbl_image.setText("Loading...")
            if self.loader:
                self.loader.load_image(path, target_width)
            else:
                self._load_image_sync(path, target_width)

    def clear_memory(self):
        """Explicitly release heavy resources."""
        self._original_pixmap = None
        self.lbl_image.clear()
        self.play_timer.stop()
        self._destroy_video_components() 
        gc.collect() # Optional but helpful for large media 

    def _start_video_playback(self):
        if self.current_path and self.is_video and os.path.exists(self.current_path):
            if self.media_player:
                self.media_player.setSource(QUrl.fromLocalFile(self.current_path))
                self.media_player.play()

    def _on_media_error(self):
        self.lbl_image.setText("Video Error")
        self.stack.setCurrentWidget(self.lbl_image)

    def _load_image_sync(self, path, target_width=1024):
        # Synchrnous loading using QImageReader
        try:
            # [Fix] Read file to memory first to release file handle immediately
            # This is important for delete/rename operations
            with open(path, "rb") as f:
                raw_data = f.read()
            
            byte_array = QByteArray(raw_data)
            buffer = QBuffer(byte_array)
            buffer.open(QBuffer.ReadOnly)

            reader = QImageReader(buffer)
            reader.setAutoTransform(True)
            tw = target_width if target_width else 1024
            if reader.size().width() > tw:
                reader.setScaledSize(reader.size().scaled(tw, tw, Qt.KeepAspectRatio))
            img = reader.read()
            
            if not img.isNull():
                self._original_pixmap = QPixmap.fromImage(img)
                self._perform_resize()
            else:
                self.lbl_image.setText("Load Failed")
                
            buffer.close()
        except Exception as e:
            print(f"Sync load error: {e}")
            self.lbl_image.setText("Load Error")

    def _on_image_loaded(self, path, image):
        if path == self.current_path and not self.is_video:
            if not image.isNull():
                self._original_pixmap = QPixmap.fromImage(image)
                self.lbl_image.setText("")
                self._perform_resize()
            else:
                self.lbl_image.setText("Load Failed")

    def resizeEvent(self, event):
        if not self.is_video and self._original_pixmap:
            self._perform_resize()
        super().resizeEvent(event)

    def _perform_resize(self):
        if self._original_pixmap and not self._original_pixmap.isNull():
            # Use self.size() (the widget's size) as the authoritative source
            # because lbl_image size might be stale during resize events or stack switches.
            target_size = self.size()
            if target_size.width() > 0 and target_size.height() > 0:
                scaled = self._original_pixmap.scaled(
                    target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.lbl_image.setPixmap(scaled)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._drag_start_pos: return
        if not (event.buttons() & Qt.LeftButton): return
        current_pos = event.position().toPoint()
        if (current_pos - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        
        if self.current_path and os.path.exists(self.current_path):
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(self.current_path)])
            drag.setMimeData(mime_data)
            
            if not self.is_video and self.lbl_image.pixmap():
                drag_pixmap = self.lbl_image.pixmap().scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                drag.setPixmap(drag_pixmap)
                drag.setHotSpot(drag_pixmap.rect().center())
            
            drag.exec(Qt.CopyAction)
            self._drag_start_pos = None

    def mouseReleaseEvent(self, event):
        if self._drag_start_pos:
            if not self.is_video:
                self.clicked.emit()
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)
        
    def get_current_path(self):
        return self.current_path

    def get_memory_usage(self):
        """Returns approximate memory usage in bytes."""
        size = 0
        if self._original_pixmap and not self._original_pixmap.isNull():
            # QPixmap depth is usually 32bpp (4 bytes)
            size += self._original_pixmap.width() * self._original_pixmap.height() * 4
        return size

# ==========================================
# Dialogs
# ==========================================
class FileCollisionDialog(QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Exists")
        self.setWindowTitle("File Exists")
        # [Memory] Auto-delete off for safety
        self.resize(400, 150)
        self.result_value = "cancel"
        
        layout = QVBoxLayout(self)
        
        msg_container = QWidget()
        msg_layout = QHBoxLayout(msg_container)
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 30px;")
        text_label = QLabel(f"The file <b>'{filename}'</b> already exists.\nWhat would you like to do?")
        text_label.setWordWrap(True)
        msg_layout.addWidget(icon_label)
        msg_layout.addWidget(text_label, 1)
        layout.addWidget(msg_container)
        
        btn_layout = QHBoxLayout()
        
        btn_overwrite = QPushButton("Overwrite")
        btn_overwrite.setToolTip("Replace the existing file.")
        btn_overwrite.clicked.connect(lambda: self.done_val("overwrite"))
        
        btn_rename = QPushButton("Rename (Keep Both)")
        btn_rename.setToolTip("Save as a new file with timestamp.")
        btn_rename.clicked.connect(lambda: self.done_val("rename"))
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(lambda: self.done_val("cancel"))
        
        btn_layout.addWidget(btn_overwrite)
        btn_layout.addWidget(btn_rename)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)

    def done_val(self, val):
        self.result_value = val
        self.accept()

class OverwriteConfirmDialog(QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Overwrite Confirmation")
        # [Memory] Auto-delete on close
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.result_value = "cancel"
        layout = QVBoxLayout(self)
        msg = QLabel(f"Data for <b>'{filename}'</b> already exists.<br>Do you want to overwrite it?")
        msg.setWordWrap(True)
        layout.addWidget(msg)
        btn_layout = QGridLayout()
        btn_yes = QPushButton("Yes")
        btn_no = QPushButton("No")
        btn_yes_all = QPushButton("Yes to All")
        btn_no_all = QPushButton("No to All")
        btn_yes.clicked.connect(lambda: self.done_val("yes"))
        btn_no.clicked.connect(lambda: self.done_val("no"))
        btn_yes_all.clicked.connect(lambda: self.done_val("yes_all"))
        btn_no_all.clicked.connect(lambda: self.done_val("no_all"))
        btn_layout.addWidget(btn_yes, 0, 0)
        btn_layout.addWidget(btn_no, 0, 1)
        btn_layout.addWidget(btn_yes_all, 1, 0)
        btn_layout.addWidget(btn_no_all, 1, 1)
        layout.addLayout(btn_layout)
    def done_val(self, val):
        self.result_value = val
        self.accept()

class DownloadDialog(QDialog):
    def __init__(self, default_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Model")
        self.setWindowTitle("Download Model")
        # [Memory] Auto-delete off for safety
        self.resize(550, 180)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Civitai / HuggingFace URL:"))
        self.entry_url = QLineEdit()
        self.entry_url.setPlaceholderText("Paste URL here (Ctrl+V)...")
        layout.addWidget(self.entry_url)
        layout.addWidget(QLabel("Save Location:"))
        path_layout = QHBoxLayout()
        self.entry_path = QLineEdit(default_path)
        self.entry_path.setPlaceholderText("Type path or select folder...")
        btn_browse = QPushButton("📂 Change")
        btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(self.entry_path)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        btn_box.button(QDialogButtonBox.Ok).setText("Download")
        layout.addWidget(btn_box)
        
        self.result_data = None

    def browse_folder(self):
        current = self.entry_path.text()
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", current)
        if folder:
            self.entry_path.setText(folder)

    def accept(self):
        self.result_data = (self.entry_url.text().strip(), self.entry_path.text().strip())
        super().accept()

    def get_data(self):
        return self.result_data if self.result_data else ("", "")

class LinkInsertDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Link")
        self.resize(400, 150)
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        self.entry_url = QLineEdit()
        self.entry_url.setPlaceholderText("https://...")
        self.entry_text = QLineEdit()
        self.entry_text.setPlaceholderText("Display Text (Optional)")
        
        form.addRow("URL:", self.entry_url)
        form.addRow("Text:", self.entry_text)
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        self.result_data = None

    def accept(self):
        url = self.entry_url.text().strip()
        text = self.entry_text.text().strip()
        self.result_data = (text, url)
        super().accept()
        
    def get_data(self):
        return self.result_data

class TaskMonitorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        header_widget = QWidget()
        header_widget.setFixedHeight(30)
        header_widget = QWidget()
        header_widget.setObjectName("task_header")
        header_widget.setFixedHeight(30)
        # header_widget.setStyleSheet(...) -> Moved to QSS 
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 0, 5, 0)
        self.lbl_title = QLabel("Queue & History")
        self.lbl_title = QLabel("Queue & History")
        self.lbl_title.setObjectName("task_title")
        # self.lbl_title.setStyleSheet(...) -> Moved to QSS
        
        # [수정] 버튼 스타일 개선 (글자색 흰색)
        self.btn_clear = QPushButton("Clear Done")
        self.btn_clear.setToolTip("Remove completed tasks from the list")
        self.btn_clear.clicked.connect(self.clear_finished_tasks) 
        self.btn_clear.setFixedWidth(80)
        self.btn_clear.setFixedHeight(22)
        self.btn_clear = QPushButton("Clear Done")
        self.btn_clear.setObjectName("task_clear_btn")
        self.btn_clear.setToolTip("Remove completed tasks from the list")
        self.btn_clear.clicked.connect(self.clear_finished_tasks) 
        self.btn_clear.setFixedWidth(80)
        self.btn_clear.setFixedHeight(22)
        # self.btn_clear.setStyleSheet(...) -> Moved to QSS
        
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_clear)
        self.layout.addWidget(header_widget)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Task", "File / Info", "Status", "%"])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 80) 
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 150)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 80)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 40)
        
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        
        self.table.setShowGrid(False)
        self.table.setObjectName("task_table")
        # self.table.setStyleSheet(...) -> Moved to QSS
        self.layout.addWidget(self.table)
        self.row_map = {} 
        self.table.setVisible(True)

    def add_row(self, key, task_type, detail_text, status="Pending"):
        if key in self.row_map:
            row = self.row_map[key]
            self.table.item(row, 0).setText(task_type)
            self.table.item(row, 1).setText(detail_text)
            self.table.item(row, 2).setText(status)
            self.update_status_color(row, status)
            return
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.row_map[key] = row
        
        item_task = QTableWidgetItem(task_type)
        item_task.setTextAlignment(Qt.AlignCenter)
        item_task.setData(Qt.UserRole, key) 
        
        item_detail = QTableWidgetItem(detail_text)
        item_detail.setToolTip(detail_text)
        item_status = QTableWidgetItem(status)
        item_status.setTextAlignment(Qt.AlignCenter)
        item_prog = QTableWidgetItem("0")
        item_prog.setTextAlignment(Qt.AlignCenter)
        
        self.table.setItem(row, 0, item_task)
        self.table.setItem(row, 1, item_detail)
        self.table.setItem(row, 2, item_status)
        self.table.setItem(row, 3, item_prog)
        
        self.update_status_color(row, status)
        self.table.scrollToBottom()

    def add_tasks(self, file_paths, task_type="Auto Match"):
        start_row = self.table.rowCount()
        self.table.setRowCount(start_row + len(file_paths))
        for i, path in enumerate(file_paths):
            row = start_row + i
            filename = os.path.basename(path)
            self.row_map[path] = row
            
            item_task = QTableWidgetItem(task_type)
            item_task.setTextAlignment(Qt.AlignCenter)
            item_task.setData(Qt.UserRole, path)
            
            item_file = QTableWidgetItem(filename if filename else path)
            item_file.setToolTip(path)
            item_status = QTableWidgetItem("Pending")
            item_status.setTextAlignment(Qt.AlignCenter)
            item_prog = QTableWidgetItem("0")
            item_prog.setTextAlignment(Qt.AlignCenter)
            
            self.table.setItem(row, 0, item_task)
            self.table.setItem(row, 1, item_file)
            self.table.setItem(row, 2, item_status)
            self.table.setItem(row, 3, item_prog)

    def update_task(self, key, status, percent=None):
        row = self.row_map.get(key)
        if row is None: return 
        self.table.item(row, 2).setText(status)
        self.update_status_color(row, status)
        if percent is not None:
            self.table.item(row, 3).setText(f"{percent}")

    def update_task_name(self, key, new_name):
        row = self.row_map.get(key)
        if row is None: return
        self.table.item(row, 1).setText(new_name)
        self.table.item(row, 1).setToolTip(new_name)

    def update_status_color(self, row, status):
        status_lower = status.lower()
        color = QColor("#eee")
        if any(x in status_lower for x in ["done", "processed", "cached", "complete"]):
            color = QColor("#4CAF50") 
        elif "skipped" in status_lower:
            color = QColor("#FFC107") 
        elif "error" in status_lower or "fail" in status_lower:
            color = QColor("#F44336") 
        elif "downloading" in status_lower:
            color = QColor("#03A9F4") 
        elif any(x in status_lower for x in ["hash", "searching", "fetching", "analyzing"]):
            color = QColor("#E040FB") 
        elif "queued" in status_lower or "pending" in status_lower:
            color = QColor("#2196F3") 
        self.table.item(row, 2).setForeground(QBrush(color))

    # [수정] Smart Clear 구현 (완료된 것만 삭제)
    def clear_finished_tasks(self):
        row_count = self.table.rowCount()
        for r in range(row_count - 1, -1, -1):
            item = self.table.item(r, 2)
            if not item: continue
            
            status = item.text().lower()
            if any(s in status for s in ["done", "processed", "skipped", "error", "cached", "complete"]):
                self.table.removeRow(r)
        
        self.row_map = {}
        for r in range(self.table.rowCount()):
            item_task = self.table.item(r, 0)
            if item_task:
                key = item_task.data(Qt.UserRole)
                if key:
                    self.row_map[key] = r

class FolderDialog(QDialog):
    def __init__(self, parent=None, path="", mode="model"):
        super().__init__(parent)
        self.setWindowTitle("Folder Settings")
        # [Memory] Auto-delete on close
        self.resize(400, 150)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.edit_path = QLineEdit(path)
        path_box = QHBoxLayout()
        path_box.addWidget(self.edit_path)
        btn_browse = QPushButton("📂")
        btn_browse.setToolTip("Browse Folder")
        btn_browse.clicked.connect(self.browse)
        path_box.addWidget(btn_browse)
        form.addRow("Path:", path_box)
        
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["model", "workflow", "prompt"])
        self.combo_mode.setCurrentText(mode)
        form.addRow("Mode:", self.combo_mode)
        
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        self.result_data = None

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder", self.edit_path.text())
        if d: self.edit_path.setText(d)

    def accept(self):
        path = self.edit_path.text().strip()
        alias = os.path.basename(path) if path else ""
        self.result_data = (alias, path, self.combo_mode.currentText())
        super().accept()

    def get_data(self):
        return self.result_data if self.result_data else ("", "", "model")

class SettingsDialog(QDialog):
    def __init__(self, parent=None, settings=None, directories=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        # [Memory] Auto-delete on close
        self.resize(700, 600)
        self.settings = settings or {}
        self.directories = directories or {}
        layout = QVBoxLayout(self)
        
        # General Settings Group
        grp_gen = QGroupBox("General")
        form_layout = QFormLayout(grp_gen)
        self.entry_civitai_key = QLineEdit(self.settings.get("civitai_api_key", ""))
        self.entry_civitai_key.setPlaceholderText("Paste your Civitai API Key here")
        form_layout.addRow("Civitai API Key:", self.entry_civitai_key)
        self.entry_hf_key = QLineEdit(self.settings.get("hf_api_key", ""))
        self.entry_hf_key.setPlaceholderText("Paste your Hugging Face Token here (Optional)")
        form_layout.addRow("Hugging Face Token:", self.entry_hf_key)
        self.entry_cache = QLineEdit(self.settings.get("cache_path", ""))
        self.entry_cache.setPlaceholderText("Default: ./cache (Leave empty for default)")
        btn_browse_cache = QPushButton("📂")
        btn_browse_cache.setToolTip("Browse Cache Folder")
        btn_browse_cache.setFixedWidth(40)
        btn_browse_cache.clicked.connect(self.browse_cache_folder)
        cache_layout = QHBoxLayout()
        cache_layout.addWidget(self.entry_cache)
        cache_layout.addWidget(btn_browse_cache)
        form_layout.addRow("Cache Folder:", cache_layout)
        layout.addWidget(grp_gen)
        
        # Directory Settings Group
        grp_dir = QGroupBox("Registered Folders")
        dir_layout = QVBoxLayout(grp_dir)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Name", "Mode", "Path"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        dir_layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ Add Folder")
        self.btn_add.setToolTip("Register a new folder to manage")
        self.btn_edit = QPushButton("✏️ Edit Selected")
        self.btn_edit.setToolTip("Edit the path or mode of the selected folder")
        self.btn_del = QPushButton("➖ Remove Selected")
        self.btn_del.setToolTip("Unregister the selected folder")
        self.btn_add.clicked.connect(self.add_folder)
        self.btn_edit.clicked.connect(self.edit_folder)
        self.btn_del.clicked.connect(self.remove_folder)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_edit)
        btn_layout.addWidget(self.btn_del)
        dir_layout.addLayout(btn_layout)
        
        layout.addWidget(grp_dir)
        
        # Bottom Buttons
        action_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 Save & Close")
        self.btn_save.setToolTip("Save changes and close settings")
        self.btn_save.clicked.connect(self.accept)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_save)
        layout.addLayout(action_layout)
        
        self.refresh_table()

    def refresh_table(self):
        self.table.setRowCount(0)
        for alias, data in self.directories.items():
            path = data.get("path", "")
            mode = data.get("mode", "model")
            
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(alias))
            self.table.setItem(row, 1, QTableWidgetItem(mode))
            self.table.setItem(row, 2, QTableWidgetItem(path))

    def add_folder(self):
        dlg = FolderDialog(self)
        if dlg.exec():
            alias, path, mode = dlg.get_data()
            if not alias or not path: return
            
            if alias in self.directories:
                QMessageBox.warning(self, "Error", "A folder with this name already exists.")
                return
            
            self.directories[alias] = {"path": path, "mode": mode}
            self.refresh_table()

    def edit_folder(self):
        row = self.table.currentRow()
        if row < 0: return
        alias = self.table.item(row, 0).text()
        data = self.directories.get(alias, {})
        
        dlg = FolderDialog(self, path=data.get("path", ""), mode=data.get("mode", "model"))
        if dlg.exec():
            new_alias, new_path, new_mode = dlg.get_data()
            if not new_alias or not new_path: return
            
            # If alias changed (because path changed), delete old key
            if new_alias != alias:
                if new_alias in self.directories:
                    QMessageBox.warning(self, "Error", "A folder with this name already exists.")
                    return
                del self.directories[alias]
                
            self.directories[new_alias] = {"path": new_path, "mode": new_mode}
            self.refresh_table()

    def remove_folder(self):
        row = self.table.currentRow()
        if row < 0: return
        alias = self.table.item(row, 0).text()
        
        if QMessageBox.question(self, "Remove", f"Remove '{alias}' from list?") == QMessageBox.Yes:
            if alias in self.directories:
                del self.directories[alias]
                self.refresh_table()

    def browse_cache_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Cache Folder", self.entry_cache.text())
        if d: self.entry_cache.setText(d)

    def accept(self):
        # Save state before closing
        self.settings["civitai_api_key"] = self.entry_civitai_key.text().strip()
        self.settings["hf_api_key"] = self.entry_hf_key.text().strip()
        self.settings["cache_path"] = self.entry_cache.text().strip()
        
        self.result_data = {
            "__settings__": self.settings,
            "directories": self.directories
        }
        super().accept()

    def get_data(self):
        # Return cached result or empty dict if cancelled/failed
        return hasattr(self, 'result_data') and self.result_data or {}

# ==========================================
# New Shared Components
# ==========================================
class MarkdownNoteWidget(QWidget):
    save_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5,5,5,5)
        
        # Stacked Widget to switch between View and Edit modes
        self.stack = QStackedWidget()
        
        # --- View Mode ---
        self.view_widget = QWidget()
        view_layout = QVBoxLayout(self.view_widget)
        view_layout.setContentsMargins(0,0,0,0)
        
        top_bar = QHBoxLayout()
        self.btn_edit = QPushButton("✏️ Edit")
        self.btn_edit.setToolTip("Edit Note")
        self.btn_edit.clicked.connect(self.switch_to_edit)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_edit)
        view_layout.addLayout(top_bar)
        
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        view_layout.addWidget(self.browser)
        
        # --- Edit Mode ---
        self.edit_widget = QWidget()
        edit_layout = QVBoxLayout(self.edit_widget)
        edit_layout.setContentsMargins(0,0,0,0)
        
        self.media_handler = None
        
        toolbar = QHBoxLayout()
        btn_img = QPushButton("🖼️ Image")
        btn_img.setToolTip("Insert Image")
        btn_img.clicked.connect(lambda: self.insert_media("image"))
        
        btn_link = QPushButton("🔗 Link")
        btn_link.setToolTip("Insert Link")
        btn_link.clicked.connect(lambda: self.insert_media("link"))
        
        for b in [btn_img, btn_link]:
            b.setFixedWidth(80)
            toolbar.addWidget(b)
        
        toolbar.addStretch()
        
        self.btn_save = QPushButton("💾 Save")
        self.btn_save.setToolTip("Save Note")
        self.btn_save.clicked.connect(self.request_save)
        self.btn_cancel = QPushButton("❌ Cancel")
        self.btn_cancel.setToolTip("Cancel Editing")
        self.btn_cancel.clicked.connect(self.switch_to_view)
        
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_cancel)
        edit_layout.addLayout(toolbar)
        
        self.editor = QTextEdit()
        edit_layout.addWidget(self.editor)
        
        self.stack.addWidget(self.view_widget)
        self.stack.addWidget(self.edit_widget)
        self.layout.addWidget(self.stack)

    def set_text(self, text):
        self.editor.setText(text)
        self.update_preview()

    def update_preview(self):
        text = self.editor.toPlainText()
        # Default font size logic or just let Qt handle it
        # Fixed reasonable default for preview
        font_size_pt = 10 
        css = f"<style>img {{ max-width: 100%; height: auto; }} body {{ color: black; background-color: white; font-size: {font_size_pt}pt; font-family: sans-serif; }}</style>"
        try:
            import markdown
            html = markdown.markdown(text)
            self.browser.setHtml(css + html)
        except ImportError:
            self.browser.setHtml(css + f"<pre>{text}</pre>")

    def switch_to_edit(self):
        self.stack.setCurrentIndex(1)

    def switch_to_view(self):
        self.update_preview()
        self.stack.setCurrentIndex(0)

    def request_save(self):
        text = self.editor.toPlainText()
        self.save_requested.emit(text)
        self.switch_to_view()

    def set_media_handler(self, handler):
        self.media_handler = handler

    def insert_media(self, mtype):
        if self.media_handler:
            result = self.media_handler(mtype)
            if result:
                cursor = self.editor.textCursor()
                cursor.insertText(result)
                self.editor.setFocus()
                return
            
        cursor = self.editor.textCursor()
        if mtype == "image":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif)")
            if file_path:
                file_path = file_path.replace("\\", "/") 
                name = os.path.basename(file_path)
                cursor.insertText(f"![{name}]({file_path})")
        elif mtype == "link":
            dlg = LinkInsertDialog(self)
            if dlg.exec():
                res = dlg.get_data()
                if res:
                    text, url = res
                    if not url: return
                    if not text: text = "Link"
                    cursor.insertText(f"[{text}]({url})")
        
        self.editor.setFocus()

class ZoomWindow(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zoom")
        self.setModal(True)
        # [Memory Fix] Ensure widget is destroyed on close
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet("background-color: black;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.lbl = QLabel()
        self.lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl)
        
        # Load pixmap
        self.pixmap = QPixmap(image_path)
        
        self.showMaximized()

    def resizeEvent(self, event):
        if self.pixmap and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl.setPixmap(scaled)
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        self.close()

    def closeEvent(self, event):
        # [Memory Fix] Explicitly clear heavy resources
        self.lbl.clear()
        self.pixmap = None
        super().closeEvent(event)
