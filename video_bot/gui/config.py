import os
import json
from typing import Any, Dict

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

LOG_COLORS = {
    "CALL": "#66BB6A",
    "REGISTER": "#42A5F5",
    "ERROR": "#EF5350",
    "AUDIO": "#FFB74D",
    "VIDEO": "#AB47BC",
    "SYSTEM": "#B0BEC5",
}


def load_cfg() -> Dict[str, Any]:
    if not os.path.isfile(CONFIG_PATH):
        return default_cfg()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return default_cfg()
        merged = default_cfg()
        merged.update({k: v for k, v in data.items() if k in merged})
        return merged
    except (OSError, json.JSONDecodeError):
        return default_cfg()


def save_cfg(data: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def default_cfg() -> Dict[str, Any]:
    return {
        "sip_domain": "10.10.2.125",
        "sip_user": "850",
        "sip_pass": "850850",
        "sip_realm": "*",
        "sip_port": 5060,
        "wav_dir": os.path.join(PROJECT_DIR, "media"),
        "media_source": "media",
        "playback_mode": "loop",
        "transmit_volume_pct": 100,
        "loopback_capture_dev": -1,
        "monitor_call_audio": False,
        "audio_playback_dev": -1,
        "audio_capture_dev": -1,
        "loopback_auto_create_sink": True,
        "loopback_sink_name": "sipbot_sink",
        "loopback_sink_description": "SIPBotSink",
        "loopback_auto_select_capture": True,
        "audio_clock_rate": 16000,
        "audio_snd_clock_rate": 48000,
        "audio_frame_ptime": 10,
        "audio_snd_rec_latency": 40,
        "audio_snd_play_latency": 40,
        "audio_snd_auto_close_time": 0,
        "audio_ec_tail_len": 64,
        "audio_player": "aumem,default",
        "net_interface": "",
        "ui_tooltip_ptime": "Размер кадра аудио в миллисекундах. Меньше = меньше задержка, но больше overhead. Обычно 10-20 ms.",
        "ui_tooltip_rec_lat": "Задержка буфера захвата аудио (ALSA capture). Меньше = быстрее прием, но выше риск подергиваний. Обычно 40-200 ms.",
        "ui_tooltip_play_lat": "Задержка буфера воспроизведения аудио (ALSA playback). Меньше = быстрее отдача, но выше риск разрывов. Обычно 40-200 ms.",
        "ui_tooltip_ec_tail": "Длина эхоподавления в миллисекундах. 0 = выключено. Больше = лучше подавление эха, но больше задержка. Обычно 64-128 ms.",
    }
