"""Paired phones and settings of the mobile access server (config/local_api.json).

Shared by the LAN API (bot thread) and the desktop window, so every change goes
through one lock. Phone tokens are stored only as SHA-256 hashes.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime

import config
from modules.bot_preferences import atomic_json

PATH = os.path.join(config.CONFIG_DIR, "local_api.json")
DEFAULT_PORT = 8765
DISCOVERY_PORT = 8766
MAX_DEVICES = 10
LOCK = threading.RLock()
# Filled in by the running server; read by the window.
STATE = {"running": False, "port": DEFAULT_PORT, "addresses": []}
_last_touch = {}


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def load():
    with LOCK:
        try:
            with open(PATH, encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        changed = data.pop("token", None) is not None  # old shared token is retired
        if not isinstance(data.get("port"), int):
            data["port"], changed = DEFAULT_PORT, True
        for key, default in (("enabled", True), ("allow_pairing", True)):
            if type(data.get(key)) is not bool:
                data[key], changed = default, True
        devices = data.get("devices")
        if not isinstance(devices, list):
            data["devices"], changed = [], True
        if changed:
            atomic_json(PATH, data)
        return data


def save(data):
    with LOCK:
        atomic_json(PATH, data)


def set_option(key, value):
    with LOCK:
        data = load()
        data[key] = value
        save(data)


def add_device(name):
    """Register a phone and return its token (shown only once)."""
    with LOCK:
        data = load()
        if len(data["devices"]) >= MAX_DEVICES:
            raise ValueError("Слишком много устройств. Отзовите ненужные в окне Pulse PC.")
        token = secrets.token_urlsafe(24)
        data["devices"].append({
            "id": secrets.token_hex(6), "name": name[:40] or "Телефон", "hash": _hash(token),
            "added": datetime.now().isoformat(timespec="seconds"), "last_seen": ""})
        save(data)
        return token


def remove_device(device_id):
    with LOCK:
        data = load()
        data["devices"] = [d for d in data["devices"] if d.get("id") != device_id]
        save(data)


def authenticate(token):
    """Return the device record for a valid token, else None."""
    if not token:
        return None
    digest = _hash(token)
    with LOCK:
        devices = load()["devices"]
    found = None
    for device in devices:
        if hmac.compare_digest(str(device.get("hash", "")), digest):
            found = device
    if found:
        now = time.monotonic()
        if now - _last_touch.get(found["id"], -999) > 60:
            _last_touch[found["id"]] = now
            with LOCK:
                data = load()
                for device in data["devices"]:
                    if device.get("id") == found["id"]:
                        device["last_seen"] = datetime.now().isoformat(timespec="seconds")
                save(data)
    return found
