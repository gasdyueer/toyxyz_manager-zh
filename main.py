import sys
import os

# Suppress verbose FFmpeg/Qt logs
os.environ["QT_LOGGING_RULES"] = "qt.multimedia*=false"

from PySide6.QtWidgets import QApplication
from src.main_window import ModelManagerWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ModelManagerWindow()
    window.show()
    sys.exit(app.exec())
