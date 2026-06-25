"""
Super Trader - Main Entry Point
"""
import sys
import os
import logging
from pathlib import Path

# Ensure app directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _setup_logging():
    """
    Configure file + console logging.

    Log file location:
      Windows EXE : same folder as SuperTrader.exe  (e.g. C:\\Users\\you\\Desktop\\super_trader.log)
      Dev (python) : same folder as main.py
      Fallback     : user home directory

    To view logs:
      - Open the log file in any text editor (Notepad, VS Code, etc.)
      - Or run from terminal: python main.py  and watch the console output
      - The log file is plain text, one entry per line with timestamp + level
    """
    # Determine log file path
    if getattr(sys, "frozen", False):
        # Running as PyInstaller EXE — log next to the EXE
        log_dir = Path(sys.executable).parent
    else:
        # Running as Python script — log next to main.py
        log_dir = Path(__file__).resolve().parent

    log_file = log_dir / "super_trader.log"

    # Fallback if directory is not writable
    try:
        log_file.touch(exist_ok=True)
    except (PermissionError, OSError):
        log_file = Path.home() / "super_trader.log"

    # Root logger — captures everything from all modules
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — keeps last 2 MB, 3 backups
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — INFO and above only (less noise on screen)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Log the file path so the user knows where to find it
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Super Trader starting")
    logger.info("Log file: %s", log_file)
    logger.info("=" * 60)

    return str(log_file)


def main():
    log_path = _setup_logging()

    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QFont, QPalette, QColor
    from PyQt5.QtCore import Qt
    from ui.login_window import LoginWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Super Trader")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(18, 18, 28))
    palette.setColor(QPalette.WindowText,      QColor(220, 220, 230))
    palette.setColor(QPalette.Base,            QColor(28, 28, 42))
    palette.setColor(QPalette.AlternateBase,   QColor(35, 35, 52))
    palette.setColor(QPalette.ToolTipBase,     QColor(28, 28, 42))
    palette.setColor(QPalette.ToolTipText,     QColor(220, 220, 230))
    palette.setColor(QPalette.Text,            QColor(220, 220, 230))
    palette.setColor(QPalette.Button,          QColor(35, 35, 52))
    palette.setColor(QPalette.ButtonText,      QColor(220, 220, 230))
    palette.setColor(QPalette.BrightText,      QColor(255, 100, 100))
    palette.setColor(QPalette.Link,            QColor(80, 160, 255))
    palette.setColor(QPalette.Highlight,       QColor(80, 120, 220))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    window = LoginWindow()
    # Pass log path so login window can show it to the user
    window._log_path = log_path
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
