import os
import re
import sys
import asyncio
import logging
import subprocess
import threading
import time
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal

from baresip import Config, Runtime, Account, UserAgent
from baresip.errors import VideoNotActive, VideoRestarted

from video_bot.audio_model import AudioManager, list_media_files, get_media_duration_seconds, MediaPlayerProcess


logging.basicConfig(level=logging.DEBUG)


def make_blank_i420(width: int, height: int) -> bytes:
    y = bytes(width * height)
    u = bytes((width // 2) * (height // 2))
    v = bytes((width // 2) * (height // 2))
    return y + u + v


class BotCore(QObject):
    log_signal = Signal(str)
    state_signal = Signal(str, str)
    calls_signal = Signal(list)

    def __init__(self, config: dict, log_fn=None, state_fn=None, calls_fn=None):
        super().__init__()
        self.config = config
        self.video_fps = 30
        self._running = False
        self._stop_event = threading.Event()
        self._thread = None
        self.runtime = None
        self.loop = None
        self.ua = None
        self._calls: dict[int, Any] = {}
        self._call_lock = threading.Lock()
        self._call_frames: dict[int, dict] = {}
        self.audio_manager = AudioManager(
            sink_name=config.get("loopback_sink_name", "sipbot_sink"),
            sink_description=config.get("loopback_sink_description", "SIPBotSink"),
            auto_create_sink=bool(config.get("loopback_auto_create_sink", True)),
            log_fn=log_fn,
        )
        self.media_files = []
        self.current_media_index = -1
        self.active_player: Optional[MediaPlayerProcess] = None
        self._media_timer = None

        if log_fn:
            self.log_signal.connect(log_fn)
        if state_fn:
            self.state_signal.connect(state_fn)
        if calls_fn:
            self.calls_signal.connect(calls_fn)

        self._runtime_settings = {
            "wav_dir": self.config.get("wav_dir", ""),
            "media_source": self.config.get("media_source", "media"),
            "playback_mode": self.config.get("playback_mode", "loop"),
            "transmit_volume_pct": self.config.get("transmit_volume_pct", 100),
            "loopback_capture_dev": self.config.get("loopback_capture_dev", -1),
            "monitor_call_audio": self.config.get("monitor_call_audio", False),
        }

    def is_running(self) -> bool:
        return self._running

    def update_runtime_settings(self, **kwargs):
        for key, value in kwargs.items():
            if key in self._runtime_settings:
                self._runtime_settings[key] = value
                self.config[key] = value

    def get_runtime_settings(self) -> dict:
        return dict(self._runtime_settings)

    def start(self) -> bool:
        if self._running:
            return False
        self._running = True
        self._stop_event.clear()
        self._calls.clear()
        self._call_frames.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if not self._running:
            return False
        self._stop_event.set()
        for frame_info in list(self._call_frames.values()):
            frame_info["stop"].set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._stop_current_player()
        return True

    def _stop_current_player(self):
        if self.active_player:
            try:
                self.active_player.stop()
            except Exception:
                pass
            self.active_player = None

    def _run(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            video_size = tuple(self.config.get("video_size", [1280, 720]))
            video_fps = float(self.config.get("video_fps", 30))
            media_source = str(self.config.get("media_source", "media"))
            audio_source = "aumem,default"
            if media_source == "loopback":
                audio_source = "alsa,default"
                self.audio_manager.ensure_loopback_sink()

            config = Config(
                video_source="vidmem",
                native_log_level="debug",
                sip_trace=True,
                net_interface=str(self.config.get("net_interface", "") or None),
                video_size=video_size,
                video_fps=video_fps,
                video_bitrate=2_000_000,
                audio_source=audio_source,
                audio_player=str(self.config.get("audio_player", "aumem,default")),
                extra_config_text=(
                    "user_agent Mitel 6865i/5.0.0.1016\n"
                    "video_codecs H264 VP8\n"
                    "audio_alert none,none\n"
                    f"audio_clock_rate {int(self.config.get('audio_clock_rate', 16000))}\n"
                    f"audio_snd_clock_rate {int(self.config.get('audio_snd_clock_rate', 48000))}\n"
                    f"audio_frame_ptime {int(self.config.get('audio_frame_ptime', 10))}\n"
                    f"audio_snd_rec_latency {int(self.config.get('audio_snd_rec_latency', 40))}\n"
                    f"audio_snd_play_latency {int(self.config.get('audio_snd_play_latency', 40))}\n"
                    f"audio_snd_auto_close_time {int(self.config.get('audio_snd_auto_close_time', 0))}\n"
                    f"audio_ec_tail_len {int(self.config.get('audio_ec_tail_len', 64))}"
                ),
            )
            self.runtime = Runtime()
            self.runtime.subscribe(self._on_event)
            self.state_signal.emit("process", "starting")
            try:
                await self.runtime.start(config=config)
                self.state_signal.emit("process", "running")
                self.log_signal.emit("Baresip runtime started successfully")
            except Exception as e:
                self.state_signal.emit("process", "stopped")
                self.log_signal.emit(f"Baresip start error: {e}")
                return

            account = Account(
                user=str(self.config.get("sip_user", "850")),
                domain=str(self.config.get("sip_domain", "10.10.2.125")),
                password=str(self.config.get("sip_pass", "850850")),
                registrar=str(self.config.get("sip_domain", "10.10.2.125")),
                transport="udp",
            )
            self.log_signal.emit(f"Account created: {account.user}@{account.domain}")
            try:
                self.ua = await UserAgent.create(self.runtime, account)
                self.log_signal.emit("UserAgent created")
            except Exception as e:
                self.log_signal.emit(f"UA create error: {e}")
                return

            self.ua.on(self._on_ua_event)
            self.ua.on_incoming(self._on_incoming)
            try:
                await self.ua.register()
                self.state_signal.emit("registration", "ok")
                self.log_signal.emit("Registration successful")
            except Exception as e:
                self.state_signal.emit("registration", "failed")
                self.log_signal.emit(f"Registration error: {e}")

            wav_dir = str(self.config.get("wav_dir", "") or "")
            if wav_dir and os.path.isdir(wav_dir):
                self.media_files = list_media_files(wav_dir)
                if self.media_files:
                    self.current_media_index = 0

            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)

            for frame_info in list(self._call_frames.values()):
                frame_info["stop"].set()
            for frame_info in list(self._call_frames.values()):
                thread = frame_info.get("thread")
                if thread is not None and thread.is_alive():
                    thread.join(timeout=2)

            try:
                with self._call_lock:
                    calls = list(self._calls.values())
                for call in calls:
                    try:
                        await call.hangup()
                    except Exception:
                        pass
                self._calls.clear()
                self._call_frames.clear()
                self._emit_call_update([])
                await self.ua.unregister()
                self.log_signal.emit("Unregistered")
            except Exception:
                pass
            try:
                await self.runtime.close()
                self.state_signal.emit("process", "stopped")
                self.log_signal.emit("Baresip runtime closed")
            except Exception as e:
                self.log_signal.emit(f"Baresip close error: {e}")

        try:
            asyncio.run(main())
        except Exception as e:
            self.state_signal.emit("process", "stopped")
            self.log_signal.emit(f"Baresip thread error: {e}")
        finally:
            self._running = False

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
        call_id = getattr(call, "handle", None)
        if call_id is None:
            call_id = id(call)
        with self._call_lock:
            self._calls[call_id] = call
            self._call_frames[call_id] = {
                "stop": threading.Event(),
                "thread": None,
                "established": threading.Event(),
                "outgoing": False,
                "echo_started": False,
            }

        call.on(self._on_call_event)

        async def answer_call():
            existing_call_ids = []
            with self._call_lock:
                existing_call_ids = [cid for cid in self._calls if cid != call_id]
            if existing_call_ids:
                self.log_signal.emit(f"Active calls detected ({len(existing_call_ids)}), hanging up before answering new call")
                for cid in existing_call_ids:
                    call_obj = self._calls.get(cid)
                    if call_obj is not None and self.loop is not None:
                        try:
                            hangup_fut = asyncio.run_coroutine_threadsafe(call_obj.hangup(), self.loop)
                            hangup_fut.result(timeout=5)
                        except Exception as he:
                            self.log_signal.emit(f"Error hanging up existing call {cid}: {he}")

            try:
                await call.answer(video=True)
                self.log_signal.emit("Incoming call answered with video=True")
                self.state_signal.emit("call", "incoming")
            except Exception as e:
                self.log_signal.emit(f"Call setup error: {e}")
                return

            try:
                await asyncio.to_thread(self._call_frames[call_id]["established"].wait, 5.0)
                if not self._call_frames[call_id]["established"].is_set():
                    self.log_signal.emit("Call established timeout")
                    return
            except Exception as e:
                self.log_signal.emit(f"Wait established error: {e}")
                return

            await self._start_echo_for_established_call(call_id, call)
            self._emit_call_update([{
                "id": call_id,
                "uri": peer,
                "state": "CONFIRMED",
                "duration": 0,
                "connected_at": time.time(),
            }])

        future = asyncio.run_coroutine_threadsafe(answer_call(), self.loop)
        future.add_done_callback(lambda f: f.exception() and self.log_signal.emit(f"Answer call error: {f.exception()}"))

    def _on_call_event(self, event):
        text = f"[Call] {event.event.name}"
        if event.text:
            text += f" | {event.text}"
        self.log_signal.emit(text)

        call_id = getattr(event, "call", None)
        call = None
        if call_id is not None:
            with self._call_lock:
                call = self._calls.get(call_id)

        if event.event.name == "CALL_ESTABLISHED":
            if call_id is not None and call_id in self._call_frames:
                frame_info = self._call_frames[call_id]
                frame_info["established"].set()
                if frame_info.get("outgoing") and call is not None and self.loop is not None:
                        future = asyncio.run_coroutine_threadsafe(
                            self._start_echo_for_established_call(call_id, call), self.loop
                        )
                        future.add_done_callback(lambda f: f.exception() and self.log_signal.emit(f"Echo start error: {f.exception()}"))
            self.state_signal.emit("call", "confirmed")
            if call is not None:
                self._emit_call_update([{
                    "id": call_id,
                    "uri": getattr(call, "peer", "") or "unknown",
                    "state": "CONFIRMED",
                    "duration": 0,
                    "connected_at": time.time(),
                }])
        elif event.event.name == "CALL_CLOSED":
            if call_id is not None:
                self._stop_call_frame(call_id)
                with self._call_lock:
                    self._calls.pop(call_id, None)
                    self._call_frames.pop(call_id, None)
            self._emit_call_update(self._build_calls_snapshot())
            if not self._calls:
                self.state_signal.emit("call", "terminated")
            else:
                self._restart_video_for_remaining()

    def _build_calls_snapshot(self):
        result = []
        with self._call_lock:
            for cid, call in list(self._calls.items()):
                try:
                    result.append({
                        "id": cid,
                        "uri": getattr(call, "peer", "") or "",
                        "state": getattr(getattr(call, "state", None), "name", ""),
                        "duration": 0,
                        "connected_at": time.time(),
                    })
                except Exception:
                    pass
        return result

    def _emit_call_update(self, calls):
        try:
            self.calls_signal.emit(calls)
        except Exception:
            pass

    def _start_frame_reader(self, call_id, call):
        frame_info = self._call_frames.get(call_id)
        if frame_info is None:
            return
        if frame_info["thread"] is not None and frame_info["thread"].is_alive():
            return
        frame_info["stop"].clear()
        frame_info["established"].set()
        frame_info["thread"] = threading.Thread(
            target=self._echo_loop, args=(call_id, call), daemon=True
        )
        frame_info["thread"].start()

    async def _start_echo_for_established_call(self, call_id, call):
        """Request a decodable start frame, then begin video echo once per call."""
        frame_info = self._call_frames.get(call_id)
        if frame_info is None or frame_info.get("echo_started"):
            return
        frame_info["echo_started"] = True
        # Waiting for the peer's periodic H.264 IDR can otherwise leave the
        # echo black for several seconds. Video TX is already ready at call
        # establishment, so no black-frame priming is required.
        try:
            await call.video.request_keyframe()
            self.log_signal.emit("Requested video keyframe from peer")
        except Exception as e:
            self.log_signal.emit(f"Video keyframe request failed: {e}")
        try:
            info = call.video.info()
            self.log_signal.emit(f"Video stream: {info.width}x{info.height} @ {info.fps:.1f}fps (tx={info.tx_ready}, rx={info.rx_ready})")
        except Exception as e:
            self.log_signal.emit(f"Video info probe failed: {e}")
        self._start_frame_reader(call_id, call)

    def _stop_call_frame(self, call_id):
        frame_info = self._call_frames.get(call_id)
        if frame_info is None:
            return
        frame_info["stop"].set()
        frame_info["established"].set()
        thread = frame_info.get("thread")
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)

    def _echo_loop(self, call_id, call):
        frame_info = self._call_frames.get(call_id)
        _video_logged = False
        while frame_info is not None and not frame_info["stop"].is_set():
            try:
                frame = call.video.read_frame()
                if frame is not None:
                    if not _video_logged:
                        self.log_signal.emit(f"Video received: {frame.width}x{frame.height} from peer")
                        _video_logged = True
                    try:
                        call.video.write_frame(frame.data)
                    except (VideoRestarted, VideoNotActive):
                        pass
                    except Exception:
                        pass
                else:
                    time.sleep(0.005)
            except (VideoNotActive, VideoRestarted):
                time.sleep(0.01)
            except Exception:
                time.sleep(0.01)
                break

    def _restart_video_for_remaining(self):
        with self._call_lock:
            calls = dict(self._calls)
        for call_id, call in calls.items():
            frame_info = self._call_frames.get(call_id)
            if frame_info is None:
                continue
            if frame_info["thread"] is not None and frame_info["thread"].is_alive():
                continue
            try:
                self._start_frame_reader(call_id, call)
                if call.video is not None:
                    try:
                        info = call.video.info()
                        call.video.write_frame(make_blank_i420(info.width, info.height))
                    except Exception:
                        pass
            except Exception:
                pass

    def hangup_call(self, call_id):
        with self._call_lock:
            call = self._calls.get(call_id)
        if call is not None and self.loop is not None:
            try:
                fut = asyncio.run_coroutine_threadsafe(call.hangup(), self.loop)
                fut.result(timeout=5)
                return True
            except Exception as e:
                self.log_signal.emit(f"Hangup error: {e}")
        return False

    def hangup_all_calls(self):
        with self._call_lock:
            calls = list(self._calls.values())
        for call in calls:
            if call is not None and self.loop is not None:
                try:
                    fut = asyncio.run_coroutine_threadsafe(call.hangup(), self.loop)
                    fut.result(timeout=5)
                except Exception as e:
                    self.log_signal.emit(f"Hangup all error: {e}")

    def make_outgoing_call(self, target: str) -> bool:
        if self.ua is None or self.loop is None:
            return False
        target = target.strip()
        if not target:
            return False
        if not target.lower().startswith(("sip:", "sips:")):
            if "@" in target:
                target = f"sip:{target}"
            else:
                target = f"sip:{target}@{self.config.get('sip_domain', '')}"

        async def dial_with_video():
            call = await self.ua.dial(target, video=True)
            call_id = getattr(call, "handle", None)
            if call_id is None:
                call_id = id(call)
            with self._call_lock:
                self._calls[call_id] = call
                self._call_frames[call_id] = {
                    "stop": threading.Event(),
                    "thread": None,
                    "established": threading.Event(),
                    "outgoing": True,
                    "echo_started": False,
                }
            call.on(self._on_call_event)
            self._emit_call_update(self._build_calls_snapshot())

        try:
            fut = asyncio.run_coroutine_threadsafe(dial_with_video(), self.loop)
            fut.result(timeout=10)
            return True
        except Exception as e:
            self.log_signal.emit(f"Outgoing call error: {e}")
            return False
