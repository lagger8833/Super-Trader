"""
mStock Trading Platform - Main Entry Point
"""
import sys
import os

# Ensure app directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtCore import Qt
from ui.login_window import LoginWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Super Trader")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    # Global font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Dark palette
    from PyQt5.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(18, 18, 28))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 230))
    palette.setColor(QPalette.Base, QColor(28, 28, 42))
    palette.setColor(QPalette.AlternateBase, QColor(35, 35, 52))
    palette.setColor(QPalette.ToolTipBase, QColor(28, 28, 42))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 230))
    palette.setColor(QPalette.Text, QColor(220, 220, 230))
    palette.setColor(QPalette.Button, QColor(35, 35, 52))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 230))
    palette.setColor(QPalette.BrightText, QColor(255, 100, 100))
    palette.setColor(QPalette.Link, QColor(80, 160, 255))
    palette.setColor(QPalette.Highlight, QColor(80, 120, 220))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    window = LoginWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
