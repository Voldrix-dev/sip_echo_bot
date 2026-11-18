from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    log_signal = Signal(str)
    state_signal = Signal(str, str)
    calls_signal = Signal(list)
    media_state_signal = Signal(str)
    track_changed_signal = Signal(str)
