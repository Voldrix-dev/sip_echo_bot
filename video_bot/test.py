#!/usr/bin/env python3
import os
import sys

os.environ["MS2_V4L2_USE_ROTATION"] = "1"

import linphone
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

class CameraWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linphone Video / Camera Test")
        self.resize(900, 700)
        self.status_label = QLabel("Инициализация Linphone...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label = QLabel("Нажми «Запустить камеру»\nКамеру открывает Linphone / Mediastreamer2")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.start_button = QPushButton("Запустить камеру")
        self.stop_button = QPushButton("Остановить камеру")
        self.start_button.clicked.connect(self.start_camera)
        self.stop_button.clicked.connect(self.stop_camera)
        layout = QVBoxLayout()
        layout.addWidget(self.video_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.core = None
        self.preview_window = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.iterate_linphone)
        self.init_linphone()

    def init_linphone(self):
        try:
            self.core = linphone.Factory.get().create_core(None, None, None)
            if not self.core.video_supported():
                raise RuntimeError("Linphone сообщает, что video_supported() == False")
            devices = self.core.video_devices_list
            self.core.video_device = "V4L2: /dev/video0" # Камеру выбирает именно Linphone.
            self.core.video_capture_enabled = False # Пока камеру не запускаем.
            self.core.video_preview_enabled = False # Preview пока выключен.
            self.core.video_display_enabled = False # Display вызова пока выключен.
            self.status_label.setText(f"Linphone OK | video_supported=True | device={self.core.video_device}")
            self.video_label.setText(f"Linphone готов\n\nВидео устройства:\n{devices}")
        except Exception as e:
            self.core = None
            self.status_label.setText(f"ОШИБКА LINPHONE: {e}")
            self.video_label.setText("Не удалось создать Linphone Core")

    def start_camera(self):
        if self.core is None:
            self.status_label.setText("Linphone Core не создан")
            return
        try:
            self.core.video_device = "V4L2: /dev/video0" # Камеру выбирает именно Linphone.
            self.core.video_capture_enabled = True # Включаем захват камеры Linphone.
            self.core.video_preview_enabled = True # Включаем preview Linphone.
            self.core.video_display_enabled = False # Удалённый video display сейчас не нужен.
            self.core.enable_video_source_reuse(True) # Оставляем video source активным для preview.
            self.core.start() # Запускаем Linphone Core.
            self.status_label.setText(f"Linphone: камера запущена | {self.core.video_device}")
            self.video_label.setText("LINPHONE PREVIEW\nV4L2: /dev/video0\n\nMediastreamer2 захватывает камеру")
            self.timer.start(20)
        except Exception as e:
            self.status_label.setText(f"Ошибка запуска Linphone video: {e}")
            print(f"Ошибка запуска Linphone video: {e}")

    def stop_camera(self):
        self.timer.stop()
        if self.core is None:
            return
        try:
            self.core.video_preview_enabled = False # Выключаем preview Linphone.
            self.core.video_capture_enabled = False # Останавливаем захват камеры Linphone.
        except Exception:
            pass
        self.status_label.setText("Linphone: камера остановлена")
        self.video_label.setText("Камера остановлена")

    def iterate_linphone(self):
        if self.core is None:
            return
        try:
            self.core.iterate()
        except Exception as e:
            self.timer.stop()
            self.status_label.setText(f"Ошибка Linphone iterate(): {e}")

    def closeEvent(self, event):
        self.timer.stop()
        if self.core is not None:
            try:
                self.core.video_preview_enabled = False
            except Exception:
                pass
            try:
                self.core.video_capture_enabled = False
            except Exception:
                pass
            try:
                self.core.stop()
            except Exception:
                pass
            self.core = None
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = CameraWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()