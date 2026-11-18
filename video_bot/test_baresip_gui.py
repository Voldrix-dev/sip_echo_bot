#!/usr/bin/env python3
import os
import sys
import asyncio
import logging
import threading
import time
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget, QTextEdit
)
from baresip import Config, Runtime, Account, UserAgent
from baresip.errors import VideoNotActive

logging.basicConfig(level=logging.DEBUG)


def make_blank_i420(width: int, height: int) -> bytes:
    y = bytes(width * height)
    u = bytes((width // 2) * (height // 2))
    v = bytes((width // 2) * (height // 2))
    return y + u + v


class BaresipWorker(QObject):
    log_signal = Signal(str)
    status_signal = Signal(str)

    def __init__(self, video_size=(1280, 720), video_fps=30):
        super().__init__()
        self.video_size = video_size
        self.video_fps = video_fps
        self._stop_event = threading.Event()
        self._thread = None
        self.runtime = None
        self.loop = None
        self.ua = None
        self._active_call = None
        self._call_lock = threading.Lock()
        self._frame_thread = None
        self._frame_stop = threading.Event()
        self._call_established = threading.Event()

    @property
    def active_call(self):
        with self._call_lock:
            return self._active_call

    @active_call.setter
    def active_call(self, value):
        with self._call_lock:
            self._active_call = value

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._frame_stop.clear()
        self._call_established.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._frame_stop.set()
        self._call_established.set()
        if self._frame_thread is not None:
            self._frame_thread.join(timeout=2)
            self._frame_thread = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            config = Config(
                video_source="vidmem",
                native_log_level="debug",
                sip_trace=True,
                net_interface="br0",
                video_size=self.video_size,
                video_fps=self.video_fps,
                video_bitrate=2_000_000,
                extra_config_text="user_agent Mitel 6865i/5.0.0.1016\nvideo_codecs H264 VP8",
            )
            self.runtime = Runtime()
            self.runtime.subscribe(self._on_event)
            self.status_signal.emit("Baresip: запуск...")
            try:
                await self.runtime.start(config=config)
                self.status_signal.emit("Baresip запущен")
                self.log_signal.emit("Baresip runtime started successfully")
            except Exception as e:
                self.status_signal.emit(f"Baresip ошибка: {e}")
                self.log_signal.emit(f"Baresip start error: {e}")
                return

            account = Account(
                user="850",
                domain="10.10.2.125",
                password="850850",
                registrar="10.10.2.125",
                transport="udp",
            )
            self.log_signal.emit(f"Account created: {account.user}@{account.domain}")
            try:
                self.ua = await UserAgent.create(self.runtime, account)
                self.log_signal.emit("UserAgent created")
            except Exception as e:
                self.status_signal.emit(f"UA create error: {e}")
                self.log_signal.emit(f"UserAgent create error: {e}")
                return

            self.ua.on(self._on_ua_event)
            self.ua.on_incoming(self._on_incoming)
            try:
                await self.ua.register()
                self.status_signal.emit("Registered: 850@10.10.2.125")
                self.log_signal.emit("Registration successful")
            except Exception as e:
                self.status_signal.emit(f"Registration error: {e}")
                self.log_signal.emit(f"Registration error: {e}")

            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)

            self._frame_stop.set()
            self._call_established.set()
            if self._frame_thread is not None:
                self._frame_thread.join(timeout=2)
                self._frame_thread = None

            try:
                current = self.active_call
                if current is not None:
                    try:
                        await current.hangup()
                    except Exception:
                        pass
                    self.active_call = None
                await self.ua.unregister()
                self.log_signal.emit("Unregistered")
            except Exception:
                pass
            try:
                await self.runtime.close()
                self.status_signal.emit("Baresip: остановлен")
                self.log_signal.emit("Baresip runtime closed")
            except Exception as e:
                self.status_signal.emit(f"Baresip close error: {e}")
                self.log_signal.emit(f"Baresip close error: {e}")

        try:
            asyncio.run(main())
        except Exception as e:
            self.status_signal.emit(f"Baresip thread error: {e}")
            self.log_signal.emit(f"Baresip thread error: {e}")

    def _on_event(self, event):
        text = f"{event.event.name}"
        if event.text:
            text += f" | {event.text}"
        self.log_signal.emit(text)

    def _on_ua_event(self, event):
        text = f"[UA] {event.event.name}"
        if event.text:
            text += f" | {event.text}"
        self.log_signal.emit(text)

    def _on_incoming(self, call):
        peer = call.peer or "unknown"
        text = f"Incoming: {peer} | state={call.state.name}"
        self.log_signal.emit(text)
        self.active_call = call

        call.on(self._on_call_event)

        async def answer_call():
            try:
                await call.answer(video=True)
                self.log_signal.emit("Incoming call answered with video=True")
                self.status_signal.emit(f"В вызове: {peer}")
            except Exception as e:
                self.log_signal.emit(f"Call setup error: {e}")
                self.status_signal.emit(f"Call setup error: {e}")
                return

            try:
                await asyncio.to_thread(self._call_established.wait, 5.0)
                if not self._call_established.is_set():
                    self.log_signal.emit("Call established timeout")
                    return
            except Exception as e:
                self.log_signal.emit(f"Wait established error: {e}")
                return

            self.log_signal.emit("Priming video stream...")
            prime_deadline = time.time() + 12.0
            while time.time() < prime_deadline and not self._frame_stop.is_set():
                try:
                    call.video.write_frame(make_blank_i420(*self.video_size))
                    try:
                        info = call.video.info
                        self.log_signal.emit(f"Video active: {info.width}x{info.height}")
                        break
                    except Exception:
                        pass
                except Exception:
                    pass
                await asyncio.sleep(0.1)

            self._start_frame_reader(call)

        asyncio.run_coroutine_threadsafe(answer_call(), self.loop)

    def _on_call_event(self, event):
        text = f"[Call] {event.event.name}"
        if event.text:
            text += f" | {event.text}"
        self.log_signal.emit(text)

        if event.event.name == "CALL_ESTABLISHED":
            self._call_established.set()
        elif event.event.name == "CALL_CLOSED":
            self._frame_stop.set()
            self._call_established.set()
            self.active_call = None
            self.status_signal.emit("Вызов завершён")

    def _start_frame_reader(self, call):
        if self._frame_thread is not None and self._frame_thread.is_alive():
            return
        self._frame_stop.clear()
        self._frame_thread = threading.Thread(target=self._echo_loop, args=(call,), daemon=True)
        self._frame_thread.start()

    def _echo_loop(self, call):
        frame_interval = 1.0 / max(self.video_fps, 1)
        next_frame_time = time.monotonic()
        while not self._frame_stop.is_set():
            try:
                frame = call.video.read_frame()
                if frame is not None:
                    try:
                        call.video.write_frame(frame.data)
                    except Exception:
                        pass
                    next_frame_time += frame_interval
                    now = time.monotonic()
                    if next_frame_time > now:
                        time.sleep(next_frame_time - now)
                    else:
                        next_frame_time = now
                else:
                    time.sleep(0.005)
            except VideoNotActive:
                time.sleep(0.01)
            except Exception:
                time.sleep(0.01)
                break


class CameraWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Baresip Video Echo")
        self.resize(800, 600)

        self.status_label = QLabel("Инициализация...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(420)

        self.start_button = QPushButton("Запустить baresip")
        self.hangup_button = QPushButton("Завершить вызов")
        self.stop_button = QPushButton("Остановить всё")
        self.start_button.clicked.connect(self.start_worker)
        self.hangup_button.clicked.connect(self.hangup_call)
        self.stop_button.clicked.connect(self.stop_worker)
        self.hangup_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.start_button)
        layout.addWidget(self.hangup_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(QLabel("Логи baresip:"))
        layout.addWidget(self.log_text)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.worker = BaresipWorker()
        self.worker.log_signal.connect(self.append_log)
        self.worker.status_signal.connect(self.update_status)

    def append_log(self, text):
        self.log_text.append(text)

    def update_status(self, text):
        self.status_label.setText(text)

    def start_worker(self):
        self.append_log("Запуск baresip...")
        self.start_button.setEnabled(False)
        self.worker.start()

    def hangup_call(self):
        self.append_log("Завершение вызова...")
        call = self.worker.active_call
        if call is not None and self.worker.loop is not None:
            try:
                fut = asyncio.run_coroutine_threadsafe(call.hangup(), self.worker.loop)
                fut.result(timeout=5)
            except Exception as e:
                self.append_log(f"Hangup error: {e}")
        self.hangup_button.setEnabled(False)

    def stop_worker(self):
        self.start_button.setEnabled(True)
        self.hangup_button.setEnabled(False)
        self.worker.stop()

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = CameraWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
