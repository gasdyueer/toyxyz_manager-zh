import os
import logging
from PySide6.QtWidgets import QApplication

class StyleManager:
    @staticmethod
    def apply_styles(app: QApplication, style_path="assets/styles.qss"):
        """Loads and applies the QSS stylesheet to the application."""
        if os.path.exists(style_path):
            try:
                with open(style_path, "r", encoding="utf-8") as f:
                    qss = f.read()
                    app.setStyleSheet(qss)
                    logging.info(f"[StyleManager] Loaded stylesheet from {style_path}")
            except Exception as e:
                logging.error(f"[StyleManager] Failed to load stylesheet: {e}")
        else:
            logging.warning(f"[StyleManager] Stylesheet not found at {style_path}")
