#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
from PySide6.QtCore import QFile, QTextStream
from PySide6.QtWidgets import QApplication
from video_bot.gui.window import MainWindow

STYLE_PATH = PROJECT_DIR / "video_bot" / "data" / "dark.qss"


def load_style(app):
    if not STYLE_PATH.exists():
        print(f"[style] Не найден: {STYLE_PATH}")
        return
    style_file = QFile(str(STYLE_PATH))
    if style_file.open(QFile.ReadOnly | QFile.Text):
        app.setStyleSheet(QTextStream(style_file).readAll())
        style_file.close()
        print(f"[style] Loaded: {STYLE_PATH}")
    else:
        print(f"[style] Не удалось открыть: {STYLE_PATH}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Video bot")
    app.setDesktopFileName("video-bot")
    load_style(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
