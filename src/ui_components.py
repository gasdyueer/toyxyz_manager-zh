import os
import gc
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, 
    QSizePolicy, QDialog, QLineEdit, QFileDialog, QDialogButtonBox, 
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, 
    QFormLayout, QSpinBox, QListWidget, QInputDialog, QGridLayout, QGroupBox, 
    QApplication, QMessageBox, QComboBox, QTextBrowser, QTextEdit
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QMimeData, QSize, QBuffer, QByteArray
from PySide6.QtGui import QPixmap, QDrag, QBrush, QColor, QImageReader, QMovie
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from .core import VIDEO_EXTENSIONS, MAX_FILE_LOAD_BYTES

# ==========================================
# Smart Media Widget
# ==========================================
class SmartMediaWidget(QWidget):
    clicked = Signal()

    def __init__(self, parent=None, loader=None, player_type=None):
        """
        player_type: kept for API compatibility but no longer used.
        """
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

        self.lbl_image = QLabel("无媒体")
        self.lbl_image.setObjectName("media_label")
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self._original_pixmap = None
        self._movie = None  # [Animation]
        
        self.stack.addWidget(self.lbl_image)
        # Video components will be initialized lazily
        self.video_widget = None
        self.media_player = None

        if self.loader:
            self.loader.image_loaded.connect(self._on_image_loaded)

    def _init_video_components(self):
        if self.media_player: return
        
        self.video_widget = QVideoWidget()
        self.stack.addWidget(self.video_widget)
        
        self.media_player = QMediaPlayer()
        # [Memory Optimization] Disable audio completely to save memory
        self.media_player.setAudioOutput(None)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.setLoops(QMediaPlayer.Infinite)
        self.media_player.errorOccurred.connect(self._on_media_error)

    def _destroy_video_components(self):
        # [Memory] Explicitly cleanup Qt Multimedia objects
        if self.media_player:
            try:
                if self.media_player.playbackState() == QMediaPlayer.PlayingState:
                    self.media_player.stop()
                self.media_player.setSource(QUrl())
                self.media_player.setVideoOutput(None)
            except RuntimeError: pass
            self.media_player.deleteLater()
            self.media_player = None
            
        if self.video_widget:
            self.stack.removeWidget(self.video_widget)
            self.video_widget.setParent(None)
            self.video_widget.close() 
            self.video_widget.deleteLater()
            self.video_widget = None

    def closeEvent(self, event):
        self.clear_memory()
        super().closeEvent(event)

    def release_resources(self):
        """
        [Memory Optimization] Fully release video resources.
        Called when tab is hidden or widget is no longer needed.
        """
        if self.media_player or self.video_widget:
            generated_logger = logging.getLogger("ui_components")
            generated_logger.debug(f"[SmartMediaWidget] Release resources for: {self.current_path}")

        self._destroy_video_components()
        self._stop_movie()
        # Clear image as well if needed, but usually we just want to stop active media
        # self.lbl_image.clear() 

    def _stop_video_playback(self):
        """Stops playback and releases file lock without destroying components."""
        if self.media_player:
            self.media_player.stop()
            self.media_player.setSource(QUrl())
        self._stop_movie() # [Animation] Also stop movie


            # Do NOT detach video output here, to allow instant reuse.

    def set_media(self, path, target_width=1024):
        self.play_timer.stop()
        
        # [Memory] Force memory release check
        if not path:
             # Reuse: Just stop playback and show default image
             self._stop_video_playback()
             self._stop_movie() # [Animation] Stop
             self.lbl_image.clear()
             self._original_pixmap = None
             self.current_path = None
             self.is_video = False
             self.stack.setCurrentWidget(self.lbl_image)
             self.lbl_image.setText("无媒体")
             return
             
        self.current_path = path # Update current_path here

        if not os.path.exists(path):
            self._destroy_video_components()
            self.is_video = False
            self.stack.setCurrentWidget(self.lbl_image)
            self.lbl_image.setText("无媒体")
            return

        ext = os.path.splitext(path)[1].lower()
        
        if ext in VIDEO_EXTENSIONS:
            # Init video components if not already created
            if not self.media_player:
                self._init_video_components()
            
            # Stop previous if any
            if self.media_player and self.media_player.playbackState() == QMediaPlayer.PlayingState:
                self.media_player.stop()
            
            self._stop_movie() # [Animation] Ensure movie stopped
            
            self.is_video = True
            self.stack.setCurrentWidget(self.video_widget)
            
            self.media_player.setSource(QUrl.fromLocalFile(path))
            self.media_player.play()
            # The play_timer is no longer strictly needed for initial playback
            # as setSource and play are called directly.
            # However, if there's a specific reason for a delayed start, it can remain.
            # For now, we'll keep it as per the instruction, but its effect might be minimal.
            self.play_timer.start() 
        elif ext in {".webp"}:
             # [Animation]
             self.is_video = False
             if self.media_player and self.media_player.playbackState() == QMediaPlayer.PlayingState:
                 self.media_player.stop()
             
             self._stop_movie()
             
             self.stack.setCurrentWidget(self.lbl_image)
             self.lbl_image.setText("加载动画中...")
             
             self._start_movie(path)
        else:
            # Not a video -> Stop video but keep components for future reuse
            if self.is_video: 
                self._stop_video_playback()
            
            self._stop_movie() # [Animation]
            
            self.is_video = False
            self.stack.setCurrentWidget(self.lbl_image)
            self.lbl_image.setText("加载中...")
            if self.loader:
                self.loader.load_image(path, target_width)
            else:
                self._load_image_sync(path, target_width)

    def _start_movie(self, path):
        """Starts GIF/WEBP playback using QMovie."""
        try:
            # We must use QByteArray to avoid file locking on Windows
            with open(path, "rb") as f:
                data = f.read()
            
            byte_array = QByteArray(data)
            # We need to keep a reference to byte_array? 
            # QMovie documentation says "The buffer must remain valid execution". 
            # So we store it in self._movie_data
            self._movie_data = QBuffer(byte_array)
            self._movie_data.open(QBuffer.ReadOnly)
            
            self._movie = QMovie(self._movie_data, QByteArray())
            
            self._movie.setCacheMode(QMovie.CacheAll)
            
            # [Optimization] Manual frame scaling for smooth resizing
            # Instead of setScaledSize (which restarts movie), we scale the pixmap manually on each frame.
            self._movie.frameChanged.connect(self._on_movie_frame)
            
            self._movie.start()
            
        except Exception as e:
            logging.warning(f"Movie load error: {e}")
            self.lbl_image.setText("动画错误")

    def _stop_movie(self):
        if self._movie:
            try:
                self._movie.frameChanged.disconnect(self._on_movie_frame)
            except: pass
            
            self._movie.stop()
            self.lbl_image.setMovie(None) # Just in case
            self.lbl_image.clear()        # Clear manual pixmap
            self._movie = None
        
        if getattr(self, '_movie_data', None):
            self._movie_data.close()
            self._movie_data = None
            
    def _on_movie_frame(self):
        """Manually scale and set current movie frame."""
        if not self._movie: return
        
        pix = self._movie.currentPixmap()
        if pix.isNull(): return
        
        # Scale to fit label size
        view_size = self.lbl_image.size()
        if not view_size.isEmpty():
             scaled_pix = pix.scaled(view_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
             self.lbl_image.setPixmap(scaled_pix)
        else:
             self.lbl_image.setPixmap(pix)

    def clear_memory(self):
        """Explicitly release heavy resources."""
        self._original_pixmap = None
        self._stop_movie() # [Animation]
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
        self.lbl_image.setText("视频错误")
        self.stack.setCurrentWidget(self.lbl_image)

    def _load_image_sync(self, path, target_width=1024):
        # Synchrnous loading using QImageReader
        try:
            if not os.path.exists(path):
                self.lbl_image.setText("文件未找到")
                return

            # [Safety] Prevent freezing on large files
            if os.path.getsize(path) > MAX_FILE_LOAD_BYTES:
                self.lbl_image.setText("文件太大")
                return

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
                self.lbl_image.setText("加载失败")
                
            buffer.close()
        except Exception as e:
            logging.warning(f"Sync load error: {e}")
            self.lbl_image.setText("加载错误")

    def _on_image_loaded(self, path, image):
        if path == self.current_path and not self.is_video:
            if not image.isNull():
                self._original_pixmap = QPixmap.fromImage(image)
                self.lbl_image.setText("")
                self._perform_resize()
            else:
                self.lbl_image.setText("加载失败")

    def resizeEvent(self, event):
        if not self.is_video and self._original_pixmap:
            self._perform_resize()
            
        # [Animation] Update frame size immediately
        if self._movie:
             self._on_movie_frame()
             
        super().resizeEvent(event)

    def showEvent(self, event):
        """[Fix] Force resize when widget is shown (fixes initial load sizing issue)"""
        if not self.is_video and (self._original_pixmap or self._movie):
             # Use timer to let layout settle before resizing
             QTimer.singleShot(0, self._perform_resize)
             if self._movie:
                 QTimer.singleShot(0, self._on_movie_frame)
        super().showEvent(event)

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
    
    def get_media_info(self):
        """Returns detailed info about current media for debug logging."""
        if not self.current_path or not os.path.exists(self.current_path):
            return None
        
        info = {
            "path": self.current_path,
            "filename": os.path.basename(self.current_path),
            "size_mb": os.path.getsize(self.current_path) / (1024 * 1024),
            "type": "video" if self.is_video else ("animation" if self._movie else "image")
        }
        
        if self.is_video and self.media_player:
            # Video info
            from PySide6.QtMultimedia import QMediaPlayer
            info["playing"] = self.media_player.playbackState() == QMediaPlayer.PlayingState
            info["duration_sec"] = self.media_player.duration() / 1000.0 if self.media_player.duration() > 0 else 0
            # Resolution from video widget
            if self.video_widget:
                size = self.video_widget.size()
                info["resolution"] = f"{size.width()}x{size.height()}"
        else:
            # Image/Anim info
            if self._movie:
                 info["resolution"] = "animation" # Complex to get exact current frame size safely
            elif self._original_pixmap and not self._original_pixmap.isNull():
                info["resolution"] = f"{self._original_pixmap.width()}x{self._original_pixmap.height()}"
            else:
                info["resolution"] = "unknown"
        
        return info

# ==========================================
# Dialogs
# ==========================================
class FileCollisionDialog(QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文件已存在")
        # [Memory] Auto-delete off for safety
        self.resize(400, 150)
        self.result_value = "cancel"
        
        layout = QVBoxLayout(self)
        
        msg_container = QWidget()
        msg_layout = QHBoxLayout(msg_container)
        icon_label = QLabel("⚠️")
        icon_label.setObjectName("FileCollisionIcon")
        text_label = QLabel(f"文件 <b>'{filename}'</b> 已存在。\n您想要做什么？")
        text_label.setWordWrap(True)
        msg_layout.addWidget(icon_label)
        msg_layout.addWidget(text_label, 1)
        layout.addWidget(msg_container)
        
        btn_layout = QHBoxLayout()
        
        btn_overwrite = QPushButton("覆盖")
        btn_overwrite.setToolTip("替换现有文件。")
        btn_overwrite.clicked.connect(lambda: self.done_val("overwrite"))
        
        btn_rename = QPushButton("重命名（保留两者）")
        btn_rename.setToolTip("保存为新文件（带时间戳）。")
        btn_rename.clicked.connect(lambda: self.done_val("rename"))
        
        btn_cancel = QPushButton("取消")
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
        self.setWindowTitle("覆盖确认")
        # [Memory] Auto-delete on close
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.result_value = "cancel"
        layout = QVBoxLayout(self)
        msg = QLabel(f"<b>'{filename}'</b> 的数据已存在。<br>您想要覆盖它吗？")
        msg.setWordWrap(True)
        layout.addWidget(msg)
        btn_layout = QGridLayout()
        btn_yes = QPushButton("是")
        btn_no = QPushButton("否")
        btn_yes_all = QPushButton("全部是")
        btn_no_all = QPushButton("全部否")
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
        self.setWindowTitle("下载模型")
        # [Memory] Auto-delete off for safety
        self.resize(550, 180)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Civitai / HuggingFace URL:"))
        self.entry_url = QLineEdit()
        self.entry_url.setPlaceholderText("在此粘贴URL (Ctrl+V)...")
        layout.addWidget(self.entry_url)
        layout.addWidget(QLabel("保存位置:"))
        path_layout = QHBoxLayout()
        self.entry_path = QLineEdit(default_path)
        self.entry_path.setPlaceholderText("输入路径或选择文件夹...")
        btn_browse = QPushButton("📂 更改")
        btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(self.entry_path)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        btn_box.button(QDialogButtonBox.Ok).setText("下载")
        layout.addWidget(btn_box)
        
        self.result_data = None

    def browse_folder(self):
        current = self.entry_path.text()
        folder = QFileDialog.getExistingDirectory(self, "选择下载文件夹", current)
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
        self.setWindowTitle("插入链接")
        self.resize(400, 150)
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        self.entry_url = QLineEdit()
        self.entry_url.setPlaceholderText("https://...")
        self.entry_text = QLineEdit()
        self.entry_text.setPlaceholderText("显示文本（可选）")
        
        form.addRow("URL:", self.entry_url)
        form.addRow("文本:", self.entry_text)
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
        header_widget.setObjectName("task_header")
        header_widget.setFixedHeight(30)
        # header_widget.setStyleSheet(...) -> Moved to QSS 
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 0, 5, 0)
        self.lbl_title = QLabel("队列与历史")
        self.lbl_title.setObjectName("task_title")
        # self.lbl_title.setStyleSheet(...) -> Moved to QSS
        
        # [수정] 버튼 스타일 개선 (글자색 흰색)
        self.btn_clear = QPushButton("清除已完成")
        self.btn_clear.setObjectName("task_clear_btn")
        self.btn_clear.setToolTip("从列表中移除已完成的任务")
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
        self.table.setHorizontalHeaderLabels(["任务", "文件/信息", "状态", "%"])
        
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
        self.table.setObjectName("task_table")
        self.layout.addWidget(self.table)
        self.row_map = {} 
        self.table.setVisible(True)

    def add_row(self, key, task_type, detail_text, status="等待中"):
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
            item_status = QTableWidgetItem("等待中")
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

    def clear_finished_tasks(self):
        row_count = self.table.rowCount()
        for r in range(row_count - 1, -1, -1):
            item = self.table.item(r, 2)
            if not item: continue
            
            status = item.text().lower()
            if any(s in status for s in ["done", "processed", "skipped", "error", "cached", "complete", "not found", "fail"]):
                self.table.removeRow(r)
        
        self.row_map = {}
        for r in range(self.table.rowCount()):
            item_task = self.table.item(r, 0)
            if item_task:
                key = item_task.data(Qt.UserRole)
                if key:
                    self.row_map[key] = r

    def log_message(self, message):
        """Adds a simple log message to the monitor."""
        key = f"log_{self.table.rowCount()}"
        self.add_row(key, "Info", message, "完成")

class FolderDialog(QDialog):
    def __init__(self, parent=None, path="", mode="model", model_type="checkpoints", comfy_root=""):
        super().__init__(parent)
        self.setWindowTitle("Folder 设置")
        # [Memory] Auto-delete on close
        self.resize(500, 250)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.edit_path = QLineEdit(path)
        path_box = QHBoxLayout()
        path_box.addWidget(self.edit_path)
        btn_browse = QPushButton("📂")
        btn_browse.setToolTip("浏览文件夹")
        btn_browse.clicked.connect(self.browse)
        path_box.addWidget(btn_browse)
        form.addRow("路径:", path_box)
        
        # [Feature] ComfyUI Root Override
        self.lbl_comfy_root = QLabel("ComfyUI根目录:")
        self.edit_comfy_root = QLineEdit(comfy_root)
        self.edit_comfy_root.setPlaceholderText("可选：ComfyUI的根路径（完整绝对路径）")
        self.edit_comfy_root.setToolTip("If set, 'Copy Node' will use this path as the base for relative path calculation.\nUseful if your manager folders are different from ComfyUI's model roots.")
        
        cpath_box = QHBoxLayout()
        cpath_box.addWidget(self.edit_comfy_root)
        self.btn_browse_root = QPushButton("📂")
        self.btn_browse_root.clicked.connect(self.browse_root)
        cpath_box.addWidget(self.btn_browse_root)
        
        form.addRow(self.lbl_comfy_root, cpath_box)
        
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["model", "gallery", "workflow", "prompt"])
        self.combo_mode.setCurrentText(mode)
        form.addRow("模式:", self.combo_mode)

        # [Feature] 模型 类型 Selector
        self.combo_type = QComboBox()
        self.model_types = [
            "checkpoints", "loras", "vae", "controlnet", 
            "clip", "unet", "upscale_models", "embeddings", "diffusion_models"
        ]
        self.combo_type.addItems(self.model_types)
        self.combo_type.setCurrentText(model_type if model_type in self.model_types else "checkpoints")
        
        self.lbl_type = QLabel("模型 类型:")
        form.addRow(self.lbl_type, self.combo_type)
        
        # Logic: Show 模型 类型 only when 模式 is 'model'
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        self._on_mode_changed(mode)
        
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        self.result_data = None

    def _on_mode_changed(self, text):
        is_model = (text == "model")
        self.lbl_type.setVisible(is_model)
        self.combo_type.setVisible(is_model)
        
        # Toggle ComfyUI根目录 visibility (Label + Input + Button)
        self.lbl_comfy_root.setVisible(is_model)
        self.edit_comfy_root.setVisible(is_model)
        self.btn_browse_root.setVisible(is_model)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder", self.edit_path.text())
        if d: self.edit_path.setText(d)

    def browse_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select ComfyUI Root Folder", self.edit_comfy_root.text())
        if d: self.edit_comfy_root.setText(d)

    def accept(self):
        path = self.edit_path.text().strip()
        alias = os.path.basename(path) if path else ""
        mode = self.combo_mode.currentText()
        # Only save model_type if mode is 'model'
        m_type = self.combo_type.currentText() if mode == "model" else ""
        c_root = self.edit_comfy_root.text().strip() if mode == "model" else ""
        
        self.result_data = (alias, path, mode, m_type, c_root)
        super().accept()

    def get_data(self):
        return self.result_data if self.result_data else ("", "", "model", "", "")

class SettingsDialog(QDialog):
    def __init__(self, parent=None, settings=None, directories=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        # [Memory] Auto-delete on close
        self.resize(700, 600)
        self.settings = settings or {}
        self.directories = directories or {}
        layout = QVBoxLayout(self)
        
        # 通用设置组
        grp_gen = QGroupBox("通用")
        form_layout = QFormLayout(grp_gen)
        self.entry_civitai_key = QLineEdit(self.settings.get("civitai_api_key", ""))
        self.entry_civitai_key.setPlaceholderText("在此粘贴您的Civitai API密钥")
        form_layout.addRow("Civitai API密钥:", self.entry_civitai_key)
        self.entry_hf_key = QLineEdit(self.settings.get("hf_api_key", ""))
        self.entry_hf_key.setPlaceholderText("在此粘贴您的Hugging Face令牌（可选）")
        form_layout.addRow("Hugging Face令牌:", self.entry_hf_key)
        self.entry_cache = QLineEdit(self.settings.get("cache_path", ""))
        self.entry_cache.setPlaceholderText("默认: ./cache（留空使用默认）")
        btn_browse_cache = QPushButton("📂")
        btn_browse_cache.setToolTip("浏览缓存文件夹")
        btn_browse_cache.setFixedWidth(40)
        btn_browse_cache.clicked.connect(self.browse_cache_folder)
        cache_layout = QHBoxLayout()
        cache_layout.addWidget(self.entry_cache)
        cache_layout.addWidget(btn_browse_cache)
        form_layout.addRow("缓存文件夹:", cache_layout)
        layout.addWidget(grp_gen)
        

        
        # 目录设置组
        grp_dir = QGroupBox("已注册文件夹")
        dir_layout = QVBoxLayout(grp_dir)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["名称", "模式", "类型", "路径"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        dir_layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 添加文件夹")
        self.btn_add.setToolTip("注册新文件夹进行管理")
        self.btn_edit = QPushButton("✏️ 编辑选中")
        self.btn_edit.setToolTip("编辑选中文件夹的路径或模式")
        self.btn_del = QPushButton("➖ 移除选中")
        self.btn_del.setToolTip("取消注册选中的文件夹")
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
        self.btn_save = QPushButton("💾 保存并关闭")
        self.btn_save.setToolTip("保存更改并关闭设置")
        self.btn_save.clicked.connect(self.accept)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_save)
        layout.addLayout(action_layout)
        
        self.refresh_table()

    def refresh_table(self):
        self.table.setRowCount(0)
        # [Update] Added ComfyUI根目录 Column
        if self.table.columnCount() < 5:
             self.table.setColumnCount(5)
             self.table.setHorizontalHeaderLabels(["名称", "模式", "类型", "路径", "ComfyUI根目录"])
             self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
             
        for alias, data in self.directories.items():
            path = data.get("path", "")
            mode = data.get("mode", "model")
            m_type = data.get("model_type", "")
            c_root = data.get("comfy_root", "")
            
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(alias))
            self.table.setItem(row, 1, QTableWidgetItem(mode))
            self.table.setItem(row, 2, QTableWidgetItem(m_type))
            self.table.setItem(row, 3, QTableWidgetItem(path))
            self.table.setItem(row, 4, QTableWidgetItem(c_root))

    def add_folder(self):
        dlg = FolderDialog(self)
        if dlg.exec():
            alias, path, mode, m_type, c_root = dlg.get_data()
            if not alias or not path: return
            
            # [Auto-Rename] Handle duplicates
            original_alias = alias
            counter = 2
            while alias in self.directories:
                alias = f"{original_alias} ({counter})"
                counter += 1
            
            self.directories[alias] = {
                "path": path, 
                "mode": mode, 
                "model_type": m_type,
                "comfy_root": c_root
            }
            self.refresh_table()

    def edit_folder(self):
        row = self.table.currentRow()
        if row < 0: return
        alias = self.table.item(row, 0).text()
        data = self.directories.get(alias, {})
        
        dlg = FolderDialog(
            self, 
            path=data.get("path", ""), 
            mode=data.get("mode", "model"), 
            model_type=data.get("model_type", ""),
            comfy_root=data.get("comfy_root", "")
        )
        if dlg.exec():
            new_alias, new_path, new_mode, new_type, new_c_root = dlg.get_data()
            if not new_alias or not new_path: return
            
            # If alias changed (or was auto-renamed), we treat it as a move/rename
            if new_alias != alias:
                # [Auto-Rename] Handle duplicates for the NEW alias
                original_alias = new_alias
                counter = 2
                while new_alias in self.directories:
                     # Check if we collided with OURSELVES (unlikely in edit, but safe)
                     if new_alias == alias: break 
                     new_alias = f"{original_alias} ({counter})"
                     counter += 1
                
                # Delete old key
                if alias in self.directories:
                     del self.directories[alias]
                
            self.directories[new_alias] = {
                "path": new_path, 
                "mode": new_mode, 
                "model_type": new_type,
                "comfy_root": new_c_root
            }
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
        
        # --- View 模式 ---
        self.view_widget = QWidget()
        view_layout = QVBoxLayout(self.view_widget)
        view_layout.setContentsMargins(0,0,0,0)
        
        top_bar = QHBoxLayout()
        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_edit.setToolTip("编辑笔记")
        self.btn_edit.clicked.connect(self.switch_to_edit)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_edit)
        view_layout.addLayout(top_bar)
        
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        view_layout.addWidget(self.browser)
        
        # --- Edit 模式 ---
        self.edit_widget = QWidget()
        edit_layout = QVBoxLayout(self.edit_widget)
        edit_layout.setContentsMargins(0,0,0,0)
        
        self.media_handler = None
        
        toolbar = QHBoxLayout()
        btn_img = QPushButton("🖼️ 图片")
        btn_img.setToolTip("插入图片")
        btn_img.clicked.connect(lambda: self.insert_media("image"))
        
        btn_link = QPushButton("🔗 链接")
        btn_link.setToolTip("插入链接")
        btn_link.clicked.connect(lambda: self.insert_media("link"))
        
        for b in [btn_img, btn_link]:
            b.setFixedWidth(80)
            toolbar.addWidget(b)
        
        toolbar.addStretch()
        
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setToolTip("保存笔记")
        self.btn_save.clicked.connect(self.request_save)
        self.btn_cancel = QPushButton("❌ 取消")
        self.btn_cancel.setToolTip("取消编辑")
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
        # Let Qt/QSS handle the font size
        css = f"<style>img {{ max-width: 100%; height: auto; }} body {{ color: black; background-color: white; font-family: sans-serif; }}</style>"
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
            file_path, _ = QFileDialog.getOpenFile名称(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif)")
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
        self.setWindowTitle("缩放")
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
