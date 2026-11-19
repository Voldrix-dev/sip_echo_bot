#!/usr/bin/env python3
import os
import signal
import sys
import re
import glob
import shutil
import time
import subprocess
import threading
import logging
from pathlib import Path
from evdev import UInput, ecodes
from typing import Callable, Optional, List

logging.basicConfig(level=logging.DEBUG)
MEDIA_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".webm", ".wma"}


class MediaPlayerProcess:
    def __init__(self, process: subprocess.Popen, path: str, sink_name: str):
        self.process = process
        self.path = path
        self.sink_name = sink_name
        self._move_to_sink()

    def _move_to_sink(self):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                result = subprocess.run(
                    ["pactl", "list", "sink-inputs"],
                    text=True, capture_output=True, check=False, timeout=1,
                )
                input_id = self._find_sink_input_id(result.stdout)
                if input_id is not None:
                    moved = subprocess.run(
                        ["pactl", "move-sink-input", str(input_id), self.sink_name],
                        text=True, capture_output=True, check=False, timeout=1,
                    )
                    if moved.returncode == 0:
                        return
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(0.05)

    def _find_sink_input_id(self, output: str):
        input_id = None
        matches_process = False
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Sink Input #"):
                input_id = stripped.split("#", 1)[1]
                matches_process = False
            elif "application.process.id" in stripped:
                matches_process = f'"{self.process.pid}"' in stripped
            elif matches_process and stripped.startswith("media.name"):
                if self.sink_name in stripped:
                    return input_id
        return None

    def set_volume(self, volume_pct: int):
        try:
            result = subprocess.run(
                ["pactl", "list", "sink-inputs"],
                text=True, capture_output=True, check=False, timeout=1,
            )
            if result.returncode == 0:
                input_id = self._find_sink_input_id(result.stdout)
                if input_id is not None:
                    subprocess.run(
                        ["pactl", "set-sink-input-volume", str(input_id), f"{int(volume_pct)}%"],
                        text=True, capture_output=True, check=False, timeout=1,
                    )
        except Exception:
            pass

    def pause(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGSTOP)

    def resume(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGCONT)

    def stop(self):
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def is_running(self) -> bool:
        return self.process.poll() is None


class MediaController:
    def __init__(self):
        self._has_evdev = False
        self.ui = None
        self.KEYS = {}
        try:
            self.KEYS = {
                "play": ecodes.KEY_PLAYPAUSE,
                "next": ecodes.KEY_NEXTSONG,
                "prev": ecodes.KEY_PREVIOUSSONG,
                "stop": ecodes.KEY_STOPCD,
                "vol_up": ecodes.KEY_VOLUMEUP,
                "vol_down": ecodes.KEY_VOLUMEDOWN,
                "mute": ecodes.KEY_MUTE,
            }
            self.ui = UInput({ecodes.EV_KEY: list(self.KEYS.values())}, name="Python Media Controller")
            self._has_evdev = True
        except Exception:
            pass

    def control(self, name: str) -> bool:
        if self._has_evdev and self.ui and name in self.KEYS:
            code = self.KEYS[name]
            self.ui.write(ecodes.EV_KEY, code, 1)
            self.ui.write(ecodes.EV_KEY, code, 0)
            self.ui.syn()
            return True
        return False

    @staticmethod
    def pactl_set_sink_volume(delta: str):
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", delta],
                text=True, capture_output=True, check=False, timeout=2,
            )
        except Exception:
            pass

    @staticmethod
    def pactl_set_sink_mute():
        try:
            subprocess.run(
                ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
                text=True, capture_output=True, check=False, timeout=2,
            )
        except Exception:
            pass


class AudioManager:
    def __init__(
        self,
        sink_name: str = "sipbot_sink",
        sink_description: str = "SIPBotSink",
        auto_create_sink: bool = True,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.sink_name = sink_name
        self.sink_description = sink_description
        self.auto_create_sink = auto_create_sink
        self.log_fn = log_fn

    def log(self, text: str):
        if self.log_fn:
            self.log_fn(text)

    def start_media_file(self, path: str, level: float = 1.0) -> MediaPlayerProcess:
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(path)
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg is not installed")
        process = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-re",
                "-i", path, "-vn", "-af", f"volume={max(0.0, float(level))}",
                "-f", "pulse", self.sink_name,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "PULSE_SINK": self.sink_name},
        )
        return MediaPlayerProcess(process, path, self.sink_name)

    def ensure_pipewire_sink_config(self) -> bool:
        """Persist the null sink in pipewire-pulse config (survives reboots)."""
        config_dir = Path.home() / ".config" / "pipewire" / "pipewire-pulse.conf.d"
        config_path = config_dir / "99-sipbot-sink.conf"
        sink_line = f"module-null-sink sink_name={self.sink_name}"
        try:
            if config_path.exists():
                current = config_path.read_text(encoding="utf-8", errors="replace")
                if sink_line in current:
                    self.log(f"[AUDIO] pipewire sink config already present: {config_path}")
                    return True
                self.log(
                    f"[AUDIO] pipewire sink config exists but does not declare "
                    f"{self.sink_name}; leaving untouched: {config_path}"
                )
                return False

            config_dir.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "pulse.cmd = [\n"
                "    {\n"
                '        cmd = "load-module"\n'
                f'        args = "{sink_line} '
                f'sink_properties=device.description={self.sink_description}"\n'
                "    }\n"
                "]\n",
                encoding="utf-8",
            )
            self.log(f"[AUDIO] pipewire sink config created: {config_path}")
            return True
        except Exception as e:
            self.log(f"[AUDIO] pipewire sink config failed: {e}")
            return False

    def ensure_loopback_sink(self) -> bool:
        if not self.auto_create_sink:
            return False

        self.ensure_pipewire_sink_config()

        try:
            existing = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                text=True, capture_output=True, check=False, timeout=3,
            )
        except FileNotFoundError:
            self.log("[AUDIO] pactl not found, cannot auto-create loopback sink")
            return False
        except Exception as e:
            self.log(f"[AUDIO] pactl list sinks failed: {e}")
            return False

        if existing.returncode == 0:
            matches = [
                line for line in existing.stdout.splitlines()
                if len(line.split()) > 1 and line.split()[1] == self.sink_name
            ]
            if matches:
                if len(matches) > 1:
                    self.log(
                        f"[AUDIO] duplicate sinks named {self.sink_name} detected "
                        f"({len(matches)}); using existing, not creating another"
                    )
                else:
                    self.log(f"[AUDIO] loopback sink already exists: {self.sink_name}")
                if not self._wait_loopback_sink_ready(self.sink_name):
                    return False
                return self._set_default_source(self.sink_name)

        try:
            created = subprocess.run(
                [
                    "pactl", "load-module", "module-null-sink",
                    f"sink_name={self.sink_name}",
                    f"sink_properties=device.description={self.sink_description}",
                ],
                text=True, capture_output=True, check=False, timeout=5,
            )
        except Exception as e:
            self.log(f"[AUDIO] loopback sink create failed: {e}")
            return False
        if created.returncode != 0:
            err = (created.stderr or created.stdout or "").strip()
            self.log(f"[AUDIO] loopback sink create failed: {err}")
            return False
        self.log(f"[AUDIO] loopback sink created: {self.sink_name} module={created.stdout.strip()}")
        if not self._wait_loopback_sink_ready(self.sink_name):
            return False
        return self._set_default_source(self.sink_name)

    def _set_default_source(self, sink_name: str) -> bool:
        source_name = f"{sink_name}.monitor"
        try:
            result = subprocess.run(
                ["pactl", "set-default-source", source_name],
                text=True, capture_output=True, check=False, timeout=3,
            )
        except Exception as e:
            self.log(f"[AUDIO] set default source failed: {e}")
            return False
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "").strip()
            self.log(f"[AUDIO] set default source failed: {error}")
            return False
        self.log(f"[AUDIO] default source set: {source_name}")
        return True

    def _wait_loopback_sink_ready(self, sink_name: str, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["pactl", "list", "short", "sources"],
                    text=True, capture_output=True, check=False, timeout=2,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if len(parts) > 1 and (
                            parts[1] == f"{sink_name}.monitor"
                            or parts[1].startswith(f"{sink_name}.monitor")
                        ):
                            self.log(f"[AUDIO] loopback monitor ready: {parts[1]}")
                            return True
            except Exception as e:
                self.log(f"[AUDIO] loopback monitor check failed: {e}")
            time.sleep(0.1)
        self.log(f"[AUDIO] loopback monitor readiness timeout: {sink_name}.monitor")
        return False


def list_media_files(dir_path: str) -> List[str]:
    dir_path = dir_path or "."
    files = []
    for path in glob.glob(os.path.join(dir_path, "*")):
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS:
            if os.path.basename(path).lower() != "x.wav":
                files.append(path)

    def sort_key(path: str):
        basename = os.path.basename(path)
        match = re.match(r"^(\d+)", basename)
        number = int(match.group(1)) if match else 10**9
        return number, basename.lower()

    return sorted(files, key=sort_key)


def get_media_duration_seconds(path: str) -> Optional[float]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            text=True, capture_output=True, check=False, timeout=5,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    return None
