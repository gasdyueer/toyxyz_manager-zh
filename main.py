import sys
import os

# Suppress verbose FFmpeg/Qt logs
os.environ["QT_LOGGING_RULES"] = "qt.multimedia*=false"

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from src.main_window import ModelManagerWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Set App Icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = ModelManagerWindow()
    window.show()
    sys.exit(app.exec())
