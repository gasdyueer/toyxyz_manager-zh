import sys
import logging
import os

# [Infra] Setup Logging
# Argument Parsing
debug_mode = "--debug" in sys.argv

# [Infra] Setup Logging
handlers = [logging.StreamHandler(sys.stdout)]

if debug_mode:
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
        
    log_file = os.path.join(LOG_DIR, "debug.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s"))
    handlers.append(file_handler)
    
    log_level = logging.DEBUG
else:
    log_level = logging.INFO

logging.basicConfig(
    level=log_level,
    format="[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s",
    handlers=handlers
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

    import traceback

    # Debug Mode Extras (Crash Handler)
    if debug_mode:
        logging.info("=== Application Started (Debug Mode) ===")
        
        # Global Exception Hook
        def crash_handler(etype, value, tb):
            err_msg = "".join(traceback.format_exception(etype, value, tb))
            print(f"\nCRITICAL ERROR:\n{err_msg}")
            logging.critical(f"Uncaught Exception:\n{err_msg}")
            sys.exit(1)
            
        sys.excepthook = crash_handler

    window = ModelManagerWindow(debug_mode=debug_mode)
    window.show()
    sys.exit(app.exec())
