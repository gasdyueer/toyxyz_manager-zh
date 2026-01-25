import sys
import logging
import os
from datetime import datetime

# [Infra] Setup Logging
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_file = os.path.join(LOG_DIR, "app.log")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# ... PySide6 imports ...

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

    # Apply Styles
    from src.utils.style_manager import StyleManager
    style_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "styles.qss")
    StyleManager.apply_styles(app, style_path)

    import logging
    import traceback

    # Argument Parsing
    debug_mode = "--debug" in sys.argv

    # Setup Logging
    # Setup Logging
    if debug_mode:
        # Force set level to DEBUG
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Add a specific file handler for debug.log
        debug_handler = logging.FileHandler("debug.log", encoding='utf-8')
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root_logger.addHandler(debug_handler)
        
        logging.info("=== Switching to DEBUG Level ===")
        
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
