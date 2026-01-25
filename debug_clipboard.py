import sys
import time
import json
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QClipboard
from PySide6.QtCore import QTimer

def monitor_clipboard():
    app = QApplication(sys.argv)
    clipboard = app.clipboard()
    
    last_text = ""
    log_file = "clipboard_dump.txt"
    
    print("Updates will be written to clipboard_dump.txt")
    print("Waiting for clipboard changes... (Copy from ComfyUI now!)")

    # Keep track of last change count to detect changes
    # But QClipboard doesn't always have a change count signal reliable on all platforms?
    # We'll use polling + signal.
    
    def on_change():
        mime = clipboard.mimeData()
        formats = mime.formats()
        
        print(f"\n[Clipboard Changed]")
        print(f"Formats: {formats}")
        
        # Dump content
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"Formats: {formats}\n")
            f.write("-" * 20 + "\n")
            
            if mime.hasText():
                text = mime.text()
                print(f"Text Content: {text[:50]}...")
                f.write(f"[text/plain]:\n{text}\n")
            
            # Check for other common types
            for fmt in formats:
                if fmt != "text/plain":
                    try:
                        data = mime.data(fmt)
                        # Try to decode as text
                        decoded = str(data, 'utf-8', errors='ignore')
                        f.write(f"\n[{fmt}]:\n{decoded}\n")
                    except Exception as e:
                        f.write(f"\n[{fmt}]: (Binary/Error: {e})\n")

    clipboard.dataChanged.connect(on_change)
    
    # Keep alive
    sys.exit(app.exec())

if __name__ == "__main__":
    monitor_clipboard()
