"""Link between the LAN API (bot thread) and the player in the desktop window.

The window owns the audio player (Qt must live in the GUI thread). The API only
reads STATE and sends commands through CONTROLLER.command (a queued Qt signal).
"""
import json
import os
import threading
from pathlib import Path

import config
from modules.bot_preferences import atomic_json

AUDIO_EXT = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".wma"}
CONFIG_PATH = os.path.join(config.CONFIG_DIR, "player.json")
MAX_TRACKS = 2000
LOCK = threading.RLock()
# Updated by the window. cover: image bytes of the current track or None.
STATE = {"active": False, "title": "", "artist": "", "album": "", "status": "stopped",
         "position": 0.0, "duration": 0.0, "volume": 0.5, "cover": None, "cover_key": ""}
CONTROLLER = None  # set by the window (PlayerController)


def default_folder():
    return str(Path.home() / "Music")


def load_folders():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as stream:
            folders = json.load(stream).get("folders")
    except (OSError, ValueError, AttributeError):
        folders = None
    if not isinstance(folders, list):
        folders = [default_folder()]
    return [f for f in folders if isinstance(f, str)]


def save_folders(folders):
    atomic_json(CONFIG_PATH, {"folders": list(dict.fromkeys(folders))})


def scan_tracks():
    """Audio files in the library folders: [{path, title, folder}], sorted."""
    tracks = []
    for folder in load_folders():
        root = Path(folder)
        if not root.is_dir():
            continue
        for current, _dirs, files in os.walk(root):
            for name in files:
                if Path(name).suffix.lower() in AUDIO_EXT:
                    tracks.append({"path": str(Path(current) / name), "title": Path(name).stem,
                                   "folder": str(Path(current).relative_to(root)) if current != str(root) else root.name})
                    if len(tracks) >= MAX_TRACKS:
                        return sorted(tracks, key=lambda t: (t["folder"].casefold(), t["title"].casefold()))
    return sorted(tracks, key=lambda t: (t["folder"].casefold(), t["title"].casefold()))


def is_library_track(path):
    """Only audio files inside the library folders may be played from the phone."""
    target = Path(path).resolve()
    if target.suffix.lower() not in AUDIO_EXT or not target.is_file():
        return False
    return any(target.is_relative_to(Path(f).resolve()) for f in load_folders() if Path(f).is_dir())


def snapshot():
    with LOCK:
        return dict(STATE)


def send(command, value=None):
    if CONTROLLER is None:
        raise ValueError("Плеер Pulse PC недоступен: откройте приложение на ПК.")
    CONTROLLER.command.emit(command, value)
