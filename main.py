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

    import logging
    import traceback

    # Argument Parsing
    debug_mode = "--debug" in sys.argv

    # Setup Logging
    if debug_mode:
        logging.basicConfig(
            filename="debug.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            encoding='utf-8' # Ensure UTF-8 for Windows
        )
        
        # Global Exception Hook
        def crash_handler(etype, value, tb):
            err_msg = "".join(traceback.format_exception(etype, value, tb))
            print(f"\nCRITICAL ERROR:\n{err_msg}")
            logging.critical(f"Uncaught Exception:\n{err_msg}")
            sys.exit(1)
            
        sys.excepthook = crash_handler
        logging.info("=== Application Started (Debug Mode) ===")

    window = ModelManagerWindow(debug_mode=debug_mode)
    window.show()
    sys.exit(app.exec())
